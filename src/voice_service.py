"""SnowLuma 语音通话公开服务。"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
from time import perf_counter
from typing import Any

from src.app.plugin_system.api import adapter_api
from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.base import BaseService

from .handlers.utils import get_stranger_info

logger = get_logger("snowluma_adapter.voice")


class VoiceCallError(RuntimeError):
    """语音 action 或流协议失败。"""

    def __init__(
        self,
        message: str,
        *,
        outcome_unknown: bool = False,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.outcomeUnknown = outcome_unknown
        self.requestId = request_id


class SnowLumaVoiceService(BaseService):
    """通过 SnowLuma OneBot action 提供语音通话能力。"""

    name = "voice_call"
    description = "SnowLuma 私聊语音通话与实时音频流"

    def __init__(self, plugin: Any) -> None:
        super().__init__(plugin)

    def _adapter(self, signature: str) -> Any:
        """获取当前插件拥有的 SnowLuma adapter。"""
        adapter = adapter_api.get_adapter(signature)
        if adapter is None or adapter.plugin is not self.plugin:
            raise RuntimeError(f"未找到本插件的 SnowLuma adapter: {signature}")
        return adapter

    async def _action(
        self,
        adapter_signature: str,
        action: str,
        params: dict[str, Any],
        *,
        dial: bool = False,
    ) -> dict[str, Any]:
        """发送普通 OneBot action 并校验成功响应。"""
        adapter = self._adapter(adapter_signature)
        try:
            response = await adapter.send_snowluma_api(action, params)
        except Exception as error:
            if dial:
                raise VoiceCallError(
                    "拨号 action 结果未知；必须先查询通话状态，不得自动重拨",
                    outcome_unknown=True,
                ) from error
            raise
        data = response.get("data")
        if response.get("status") != "ok" or response.get("retcode") != 0:
            raise VoiceCallError(
                str(response.get("message") or response.get("wording") or f"{action} failed"),
                outcome_unknown=dial and bool(isinstance(data, dict) and data.get("outcomeUnknown")),
                request_id=data.get("requestId") if isinstance(data, dict) else None,
            )
        if not isinstance(data, dict):
            raise VoiceCallError(f"{action} returned invalid data")
        return data

    async def get_status(self, adapter_signature: str) -> dict[str, Any]:
        """获取语音服务状态及音频格式。"""
        return await self._action(adapter_signature, "voice_get_status", {})

    async def get_call(self, adapter_signature: str) -> dict[str, Any]:
        """获取当前通话快照。"""
        return await self._action(adapter_signature, "voice_get_call", {})

    async def dial_call(self, adapter_signature: str, user_id: str) -> dict[str, Any]:
        """显式拨打指定 QQ 用户。"""
        return await self._action(
            adapter_signature,
            "voice_dial_call",
            {"user_id": user_id},
            dial=True,
        )

    async def accept_call(self, adapter_signature: str, call_id: str) -> dict[str, Any]:
        """接听指定来电。"""
        return await self._control(adapter_signature, "voice_accept_call", call_id)

    async def reject_call(self, adapter_signature: str, call_id: str) -> dict[str, Any]:
        """拒接指定来电。"""
        return await self._control(adapter_signature, "voice_reject_call", call_id)

    async def hangup_call(self, adapter_signature: str, call_id: str) -> dict[str, Any]:
        """挂断指定通话。"""
        return await self._control(adapter_signature, "voice_hangup_call", call_id)

    async def _control(self, adapter_signature: str, action: str, call_id: str) -> dict[str, Any]:
        """执行绑定当前通话 ID 的控制 action。"""
        return await self._action(adapter_signature, action, {"call_id": call_id})

    async def get_peer(self, adapter_signature: str, user_id: str) -> dict[str, Any]:
        """按 QQ 号读取公开资料中的 UID、QQ 号与昵称。"""
        if not user_id.isdigit():
            raise TypeError("user_id 必须是数字 QQ 号字符串")
        adapter = self._adapter(adapter_signature)
        info = await get_stranger_info(int(user_id), adapter=adapter)
        if not isinstance(info, dict):
            raise TypeError(f"get_stranger_info 返回了无效资料：{user_id}")
        return {
            key: info[key]
            for key in ("uid", "user_id", "nickname")
            if key in info
        }

    async def _assert_current(self, adapter_signature: str, call_id: str, generation: int) -> None:
        """要求指定通话仍处于同一已接通代次。"""
        call = await self.get_call(adapter_signature)
        if call.get("callId") != call_id or call.get("generation") != generation or call.get("phase") != "connected":
            raise VoiceCallError("语音通话已变化或未接通")

    async def capture_audio(
        self,
        adapter_signature: str,
        call_id: str,
        generation: int,
    ) -> AsyncIterator[bytes]:
        """通过 adapter 主连接以 16 kHz 单声道 S16LE 产生音频帧。"""
        await self._assert_current(adapter_signature, call_id, generation)
        adapter = self._adapter(adapter_signature)
        sequence = 0
        info_seen = False
        total_bytes = 0
        stream = adapter.stream_snowluma_api(
            "voice_capture_audio_stream",
            {"call_id": call_id},
            capture_key=(call_id, generation),
        )
        try:
            async for frame in stream:
                if frame.get("status") != "ok" or frame.get("retcode") != 0:
                    raise VoiceCallError("SnowLuma 采音流返回失败")
                data = frame.get("data")
                if not isinstance(data, dict):
                    raise VoiceCallError("SnowLuma 采音帧缺少 data")
                kind = data.get("data_type")
                if data.get("type") == "error" or kind == "error":
                    raise VoiceCallError(str(frame.get("message") or "SnowLuma 采音流失败"))
                if kind == "audio_info":
                    if data.get("call_id") != call_id or data.get("format") != "s16le" or data.get("sample_rate") != 16000 or data.get("channels") != 1:
                        raise VoiceCallError("SnowLuma 采音格式或通话 ID 无效")
                    info_seen = True
                elif kind == "audio_keepalive":
                    if data.get("call_id") != call_id:
                        raise VoiceCallError("SnowLuma 采音 keepalive 通话 ID 无效")
                elif kind == "audio_chunk":
                    if not info_seen or data.get("call_id") != call_id or data.get("sequence") != sequence:
                        raise VoiceCallError("SnowLuma 采音帧顺序或通话 ID 无效")
                    try:
                        chunk = base64.b64decode(data["data"], validate=True)
                    except (KeyError, ValueError, TypeError) as error:
                        raise VoiceCallError("SnowLuma 采音帧 Base64 无效") from error
                    if len(chunk) != data.get("size") or len(chunk) > 65536 or len(chunk) % 2:
                        raise VoiceCallError("SnowLuma 采音帧大小无效")
                    sequence += 1
                    total_bytes += len(chunk)
                    yield chunk
                elif kind == "audio_complete" and data.get("type") == "response":
                    if not info_seen or data.get("call_id") != call_id or data.get("total_chunks") != sequence or data.get("total_bytes") != total_bytes:
                        raise VoiceCallError("SnowLuma 采音终结帧无效")
                    if sequence == 0 or total_bytes == 0:
                        raise VoiceCallError("SnowLuma 采音流为空")
                    return
                else:
                    raise VoiceCallError(f"SnowLuma 采音流出现未知帧：{kind}")
            raise VoiceCallError("SnowLuma 采音流在终结帧前结束")
        finally:
            await stream.aclose()

    async def play_audio(
        self,
        adapter_signature: str,
        call_id: str,
        generation: int,
        chunks: AsyncIterator[bytes],
        trace_id: str = "",
    ) -> dict[str, Any]:
        """按背压上传 48 kHz 单声道 S16LE PCM 并等待播放排空。"""
        started = perf_counter()
        await self._assert_current(adapter_signature, call_id, generation)
        status = await self.get_status(adapter_signature)
        playback_format = status.get("audioFormats", {}).get("playback", {})
        if playback_format != {"format": "s16le", "sampleRate": 48000, "channels": 1}:
            raise VoiceCallError("SnowLuma 播放格式不是 48 kHz 单声道 S16LE")
        opened = await self._action(adapter_signature, "voice_open_playback", {"call_id": call_id, "format": "pcm"})
        stream_id = opened["streamId"]
        accepted_bytes = 0
        append_chunks = 0
        try:
            control_wait = perf_counter() - started
            max_bytes = min(opened["maxChunkBytes"], 32768)
            max_bytes -= max_bytes % 2
            if max_bytes < 2 or opened.get("callId") != call_id or opened.get("generation") != generation:
                raise VoiceCallError("SnowLuma 播放流参数无效")
            sequence = opened["nextSequence"]
            upstream_wait = 0.0
            append_wait = 0.0
            pending = bytearray()

            async def append(part: bytes) -> None:
                """串行确认音频，代次有效性由已绑定的上游播放流检查。"""
                nonlocal sequence, accepted_bytes, append_chunks, append_wait
                requested_at = perf_counter()
                result = await self._action(adapter_signature, "voice_append_audio", {
                    "call_id": call_id,
                    "stream_id": stream_id,
                    "sequence": sequence,
                    "data": base64.b64encode(part).decode("ascii"),
                })
                append_wait += perf_counter() - requested_at
                if result.get("nextSequence") != sequence + 1 or result.get("acceptedBytes") != len(part):
                    raise VoiceCallError("SnowLuma 播放 append 回执序号或字节数无效")
                sequence += 1
                accepted_bytes += len(part)
                append_chunks += 1

            source = aiter(chunks)
            while True:
                read_started = perf_counter()
                try:
                    chunk = await anext(source)
                except StopAsyncIteration:
                    break
                finally:
                    upstream_wait += perf_counter() - read_started
                if not isinstance(chunk, bytes):
                    raise VoiceCallError("播放音频源必须产生 bytes")
                offset = 0
                while offset < len(chunk):
                    take = min(max_bytes - len(pending), len(chunk) - offset)
                    pending.extend(chunk[offset:offset + take])
                    offset += take
                    if len(pending) == max_bytes:
                        await append(bytes(pending))
                        pending.clear()
            if len(pending) % 2:
                raise VoiceCallError("播放 PCM 末尾不是完整采样")
            if pending:
                await append(bytes(pending))
            if accepted_bytes == 0:
                raise VoiceCallError("播放音频源不能为空")
            checked_at = perf_counter()
            await self._assert_current(adapter_signature, call_id, generation)
            control_wait += perf_counter() - checked_at
            drain_started = perf_counter()
            finished = await self._action(adapter_signature, "voice_finish_playback", {
                "call_id": call_id,
                "stream_id": stream_id,
            })
            if finished.get("drained") is not True or finished.get("bytes") != accepted_bytes:
                raise VoiceCallError("SnowLuma 播放未完整排空")
            trace_field = f"trace_id={trace_id} " if trace_id else ""
            logger.info(
                f"QQ PCM 播放结束 {trace_field}pcm_bytes={accepted_bytes} "
                f"call_id={call_id}, generation={generation}, "
                f"append_chunks={append_chunks} audio_seconds={accepted_bytes / 96000:.3f} end_reason=drained "
                f"upstream_wait={upstream_wait:.3f}s, append_ack_wait={append_wait:.3f}s, "
                f"control_wait={control_wait:.3f}s, "
                f"drain_wait={perf_counter() - drain_started:.3f}s, elapsed={perf_counter() - started:.3f}s"
            )
            return finished
        except BaseException as error:
            end_reason = (
                "cancelled" if isinstance(error, asyncio.CancelledError)
                else "consumer_closed" if isinstance(error, GeneratorExit)
                else "error"
            )
            if trace_id:
                logger.info(
                    f"QQ PCM 播放结束 trace_id={trace_id} pcm_bytes={accepted_bytes} "
                    f"append_chunks={append_chunks} end_reason={end_reason}"
                )
            try:
                await self._action(adapter_signature, "voice_cancel_playback", {
                    "call_id": call_id,
                    "stream_id": stream_id,
                })
            except asyncio.CancelledError as cancel_error:
                raise VoiceCallError("播放失败且取消未确认", outcome_unknown=True) from BaseExceptionGroup(
                    "playback and cancellation errors", [error, cancel_error]
                )
            except Exception as cancel_error:  # noqa: BLE001
                raise VoiceCallError("播放失败且取消未确认", outcome_unknown=True) from BaseExceptionGroup(
                    "playback and cancellation errors", [error, cancel_error]
                )
            raise