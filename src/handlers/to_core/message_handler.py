"""消息处理器 - 将 SnowLuma 消息转换为 MessageEnvelope"""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import httpx
import orjson
from mofox_wire import MessageBuilder, MessageEnvelope, SegPayload
from mofox_wire.types import UserRole

from src.app.plugin_system.api.log_api import get_logger
from src.core.utils.base64_helper import base64_encode_bytes

from ....config import SnowLumaAdapterConfig
from ...event_models import ACCEPT_FORMAT, QQ_FACE, RealMessageType
from ..utils import (
    fetch_ptt_text,
    get_forward_message,
    get_group_info,
    get_image_base64,
    get_member_info,
    get_message_detail,
    get_record_detail,
    get_self_info,
    sanitize_text,
)

if TYPE_CHECKING:
    from ....plugin import SnowLumaAdapter

logger = get_logger("snowluma_adapter")


class MessageHandler:
    """处理来自 SnowLuma 的消息事件"""

    def __init__(self, adapter: "SnowLumaAdapter"):
        self.adapter = adapter

    async def handle_raw_message(self, raw: dict[str, Any]) -> MessageEnvelope | None:
        """
        处理原始消息并转换为 MessageEnvelope

        Args:
            raw: SnowLuma 原始消息数据

        Returns:
            MessageEnvelope (dict) or None

        Note:
            黑白名单过滤已移动到 SnowLumaAdapter.from_platform_message 顶层执行，
            确保所有类型的事件（消息、通知等）都能被统一过滤。
        """

        message_type = raw.get("message_type")
        message_id = str(raw.get("message_id", ""))
        message_time = time.time()

        msg_builder = MessageBuilder()

        # 构造用户信息（不修改原始 raw 数据）
        sender_info = raw.get("sender", {})
        role_str = sender_info.get("role", "")
        if role_str == "owner":
            role = UserRole.OWNER
        elif role_str == "admin":
            role = UserRole.OPERATOR
        elif role_str == "member":
            role = UserRole.MEMBER
        else:
            role = role_str

        (
            msg_builder.direction("incoming")
            .message_id(message_id)
            .timestamp_ms(int(message_time * 1000))
            .from_user(
                user_id=str(sender_info.get("user_id", "")),
                platform="qq",
                nickname=sanitize_text(sender_info.get("nickname", "")),
                cardname=sanitize_text(sender_info.get("card", "")),
                user_avatar=sender_info.get("avatar", ""),
                role=role,
            )
        )

        # 构造群组信息（如果是群消息）
        if message_type == "group":
            group_id = raw.get("group_id")
            if group_id:
                fetched_group_info = await get_group_info(group_id)
                (
                    msg_builder.from_group(
                        group_id=str(group_id),
                        platform="qq",
                        name=(
                            fetched_group_info.get("group_name", "")
                            if fetched_group_info
                            else raw.get("group_name", "")
                        ),
                    )
                )

        # 解析消息段
        message_segments = raw.get("message", [])
        seg_list: list[SegPayload] = []

        # 提取引用回复的目标消息 ID（用于填充 reply_to）
        reply_target_id: str | None = None
        reply_target_sender_id: str | None = None

        for segment in message_segments:
            # 检测 reply 段，提取被回复消息的 ID
            if isinstance(segment, dict) and segment.get("type") == "reply":
                reply_seg_data = segment.get("data", {})
                if isinstance(reply_seg_data, dict):
                    reply_target_id = str(reply_seg_data.get("id", "")) or None

            seg_message = await self.handle_single_segment(segment, raw)
            if seg_message:
                seg_list.append(seg_message)

        # 如果检测到引用回复，获取被回复消息的发送者 ID
        if reply_target_id:
            try:
                reply_detail = await get_message_detail(reply_target_id)
                if reply_detail:
                    reply_sender = reply_detail.get("sender", {})
                    reply_target_sender_id = str(reply_sender.get("user_id", "")) or None
            except Exception:
                pass

        # 防御性检查：确保至少有一个消息段，避免消息为空导致构建失败
        if not seg_list:
            logger.warning("消息内容为空，添加占位符文本")
            seg_list.append({"type": "text", "data": "[消息内容为空]"})

        msg_builder.format_info(
            content_format=[seg["type"] for seg in seg_list],
            accept_format=ACCEPT_FORMAT,
        )

        msg_builder.seg_list(seg_list)

        # 通过 metadata 传递 reply_to 信息给框架
        if reply_target_id:
            reply_meta: dict[str, Any] = {"reply_to": reply_target_id}
            if reply_target_sender_id:
                reply_meta["reply_target_sender_id"] = reply_target_sender_id
            msg_builder.metadata(reply_meta)

        return msg_builder.build()

    async def handle_single_segment(
        self, segment: dict, raw_message: dict, in_reply: bool = False
    ) -> SegPayload | None:
        """
        处理单一消息段并转换为 MessageEnvelope

        Args:
            segment: 单一原始消息段
            raw_message: 完整的原始消息数据

        Returns:
            SegPayload | None
        """
        seg_type = segment.get("type")
        
        match seg_type:
            case RealMessageType.text:
                return await self._handle_text_message(segment)
            case RealMessageType.image:
                return await self._handle_image_message(segment)
            case RealMessageType.face:
                return await self._handle_face_message(segment)
            case RealMessageType.at:
                return await self._handle_at_message(segment, raw_message)
            case RealMessageType.reply:
                return await self._handle_reply_message(segment, raw_message, in_reply)
            case RealMessageType.record:
                return await self._handle_record_message(segment, raw_message)
            case RealMessageType.video:
                # 检查是否启用了视频处理
                if self.adapter.plugin and self.adapter.plugin.config:
                    config = cast(SnowLumaAdapterConfig, self.adapter.plugin.config)
                    if not config.features.enable_video_processing:
                        logger.debug("视频消息处理已禁用，跳过")
                        return {"type": "text", "data": "[视频消息]"}
                return await self._handle_video_message(segment)
            case RealMessageType.rps:
                return await self._handle_rps_message(segment)
            case RealMessageType.dice:
                return await self._handle_dice_message(segment)
            case RealMessageType.forward:
                messages = await get_forward_message(segment, adapter=self.adapter)
                if not messages:
                    logger.warning("转发消息内容为空或获取失败")
                    return None
                return await self.handle_forward_message(messages)  # type: ignore[arg-type]
            case RealMessageType.json:
                return await self._handle_json_message(segment)
            case RealMessageType.contact:
                return await self._handle_contact_message(segment)
            case RealMessageType.file:
                return await self._handle_file_message(segment)

            case _:
                logger.warning(f"Unsupported segment type: {seg_type}")
                return None

    # Utility methods for handling different message types

    async def _handle_text_message(self, segment: dict) -> SegPayload:
        """处理纯文本消息"""
        message_data = segment.get("data", {})
        plain_text = message_data.get("text", "")
        return {"type": "text", "data": plain_text}

    async def _handle_face_message(self, segment: dict) -> SegPayload | None:
        """处理表情消息"""
        message_data = segment.get("data", {})
        face_raw_id = str(message_data.get("id", ""))
        if face_raw_id in QQ_FACE:
            face_content = QQ_FACE.get(face_raw_id, "[未知表情]")
            return {"type": "text", "data": face_content}
        else:
            logger.warning(f"不支持的表情：{face_raw_id}")
            return None

    async def _handle_image_message(self, segment: dict) -> SegPayload | None:
        """处理图片消息与表情包消息"""
        message_data = segment.get("data", {})
        image_sub_type = message_data.get("sub_type")
        image_url = message_data.get("url", "")

        if not image_url:
            logger.warning("图片消息缺少URL")
            return None

        try:
            image_base64 = await get_image_base64(image_url)
        except httpx.TimeoutException:
            logger.error(f"图片消息处理超时: {image_url}")
            return {"type": "text", "data": "[图片处理超时]"}
        except Exception as e:
            logger.error(f"图片消息处理失败: {e!s}")
            return None
        if image_sub_type == 0:
            return {"type": "image", "data": image_base64}
        elif image_sub_type not in [4, 9]:
            return {"type": "emoji", "data": image_base64}
        else:
            logger.warning(f"不支持的图片子类型：{image_sub_type}")
            return None

    async def _handle_at_message(self, segment: dict, raw_message: dict) -> SegPayload | None:
        """处理@消息"""
        seg_data = segment.get("data", {})
        if not seg_data:
            return None

        qq_id = seg_data.get("qq")
        self_id = raw_message.get("self_id")
        group_id = raw_message.get("group_id")

        if str(self_id) == str(qq_id):
            logger.debug("机器人被at")
            self_info = await get_self_info()
            if self_info:
                return {"type": "at", "data": f"{self_info.get('nickname')}:{self_info.get('user_id')}"}
            return None
        else:
            if qq_id and group_id:
                member_info = await get_member_info(group_id=group_id, user_id=qq_id)
                if member_info:
                    return {"type": "at", "data": f"{member_info.get('nickname')}:{member_info.get('user_id')}"}
                return None

    async def _handle_reply_message(self, segment: dict, raw_message: dict, in_reply: bool) -> SegPayload | None:
        """处理回复消息。

        返回的 seglist 会前置一个 ``reply`` 段（data 为被引用消息 ID），
        以便框架 ``MessageConverter`` 解析出 ``Message.reply_to``；其后保留
        可读的 ``[回复<昵称(QQ号)>：...]`` 文本预览。

        与 onebot 适配器不同，本方法通过查数据库 ``processed_plain_text`` 获取
        被引用消息的已识别内容（含 VLM/ASR 识别结果），而非 ``get_message_detail``
        的原始段，避免媒体消息只有 ``[图片]`` 占位符而无识别描述。
        """
        if in_reply:
            return None

        seg_data = segment.get("data", {})
        if not seg_data:
            return None

        message_id = seg_data.get("id")
        if not message_id:
            return None

        # 查数据库获取被引用消息的已识别内容
        reply_text = ""
        sender_nickname = "未知用户"
        sender_id_str = ""
        try:
            from src.core.models.sql_alchemy import Messages, PersonInfo
            from src.kernel.db import QueryBuilder

            msg_record = cast(Messages | None, await (
                QueryBuilder(Messages)
                .filter(message_id=str(message_id))
                .first()
            ))
            if msg_record:
                reply_text = msg_record.processed_plain_text or ""
                person_id = msg_record.person_id

                # Bot 消息 person_id 为 "bot"
                if person_id == "bot":
                    self_id = raw_message.get("self_id")
                    sender_nickname = "你"
                    sender_id_str = str(self_id) if self_id else ""
                elif person_id:
                    person_record = cast(PersonInfo | None, await (
                        QueryBuilder(PersonInfo)
                        .filter(person_id=person_id)
                        .first()
                    ))
                    if person_record:
                        nickname = person_record.nickname or ""
                        cardname = person_record.cardname or ""
                        sender_id_str = person_record.user_id or ""
                        # 优先使用群名片
                        sender_nickname = cardname or nickname or "未知用户"
        except Exception as e:
            logger.warning(f"查询被引用消息记录失败: {e!s}")

        prefix_text = f"[回复<{sender_nickname}({sender_id_str})>：" if sender_id_str else f"[回复<{sender_nickname}>："
        suffix_text = "]，说："

        # 被引用消息内容为空时的占位
        brief_text = reply_text or "[无法获取被引用的消息]"

        return {
            "type": "seglist",
            "data": [
                {"type": "reply", "data": str(message_id)},
                {"type": "text", "data": prefix_text},
                {"type": "text", "data": brief_text},
                {"type": "text", "data": suffix_text},
            ],
        }

    async def _handle_record_message(
        self, segment: dict, raw_message: dict
    ) -> SegPayload | None:
        """处理语音消息。

        优先使用 SnowLuma 原生 ``fetch_ptt_text`` 进行语音转文字；
        失败时通过 ``get_record`` 下载 WAV 并返回 voice 段，交由框架 ASR 识别；
        均失败则返回 ``[语音(识别失败)]`` 占位符。

        在语音消息识别成功后，会向当前聊天流注入一条提示词，
        提醒 LLM 注意语音识别结果可能存在同音/近形字错误。
        """
        message_id = str(raw_message.get("message_id", ""))
        segment_data = segment.get("data", {})
        file = segment_data.get("file", "")
        file_id = segment_data.get("file_id", "")

        def _inject_voice_hint() -> None:
            """向当前流注入一条 once 语音提示词，框架消费后自动从 store 删除。"""
            try:
                from src.app.plugin_system.api.prompt_api import add_stream_reminder
                from src.core.prompt import (
                    SystemReminderInsertType,
                    SystemReminderConsumeType,
                )
                from src.core.models.stream import ChatStream

                msg_type = raw_message.get("message_type")
                group_id = raw_message.get("group_id")
                sender_info = raw_message.get("sender", {})
                user_id = sender_info.get("user_id", "")

                if msg_type == "group" and group_id:
                    stream_id = ChatStream.generate_stream_id(
                        platform="qq", group_id=str(group_id)
                    )
                else:
                    stream_id = ChatStream.generate_stream_id(
                        platform="qq", user_id=str(user_id)
                    )

                add_stream_reminder(
                    stream_id=stream_id,
                    bucket="actor",
                    name="voice_asr_hint",
                    content=(
                        "当前对话中包含语音消息，其内容由语音识别（ASR）自动转换，"
                        "可能存在同音字、近形字或识别偏差。请根据上下文理解用户语音的真实内容，"
                        "不要纠错字或指出识别错误，因为这些大概率是 ASR 识别错误而非用户问题，如果为空则是没识别出来，"
                        "对于这种情况静默处理，不要主动提及。"
                        "以及你在听语音时，不要说是系统识别之类的话，就当是自己真的听完了一样。"
                    ),
                    insert_type=SystemReminderInsertType.DYNAMIC,
                    consume=SystemReminderConsumeType.ONCE,
                )
            except Exception as e:
                logger.debug(f"注入语音提示词失败（忽略）: {e!s}")

        # 检查是否启用 SnowLuma 原生语音转文字
        sl_voice_enabled = True
        if self.adapter.plugin and self.adapter.plugin.config:
            config = cast(SnowLumaAdapterConfig, self.adapter.plugin.config)
            sl_voice_enabled = config.features.enable_sl_voice_to_text

        # 优先：SnowLuma 原生 fetch_ptt_text
        sl_voice_text: str | None = None
        if sl_voice_enabled and message_id:
            try:
                sl_voice_text = await fetch_ptt_text(message_id)
                if sl_voice_text:
                    logger.debug(f"SL 语音转文字成功: {sl_voice_text[:50]}")
                else:
                    logger.debug("SL 语音转文字返回空结果")
            except Exception as e:
                logger.warning(f"SL 语音转文字失败: {e!s}")

        # 获取语音 base64 数据，返回 voice 段让框架注入 media_id
        if file or file_id:
            try:
                record_data = await get_record_detail(file, file_id, adapter=self.adapter)
                if record_data:
                    base64_data = record_data.get("base64") or record_data.get("data") or ""
                    if base64_data:
                        # SL 转文字成功时，预先把识别结果写入 Voices 表和缓存表，避免框架重复 ASR
                        if sl_voice_text:
                            try:
                                from src.app.plugin_system.api.media_api import save_media_info
                                from src.core.managers.media_manager import get_media_manager

                                manager = get_media_manager()
                                voice_hash = manager.compute_media_hash(base64_data)
                                # 写入 Voices 表（asr_processed=True）
                                await save_media_info(
                                    media_hash=voice_hash,
                                    media_type="voice",
                                    description=sl_voice_text,
                                    vlm_processed=True,
                                )
                                # 写入 VoiceDescriptions 缓存表，让 recognize_media 缓存命中跳过 ASR
                                await manager._save_voice_description_cache(voice_hash, sl_voice_text)
                                logger.debug(f"SL 语音识别结果已写入缓存: {voice_hash[:8]}...")
                            except Exception as e:
                                logger.warning(f"写入语音缓存失败: {e!s}")

                        logger.debug("通过 get_record 获取到语音 base64 数据，返回 voice 段")
                        _inject_voice_hint()
                        return {"type": "voice", "data": base64_data}
                    logger.debug("get_record 返回数据中未找到 base64 字段")
            except Exception as e:
                logger.warning(f"get_record 获取语音失败: {e!s}")

        # 无法获取 base64 数据时，用 SL 转文字结果作为 text 段兜底
        if sl_voice_text:
            _inject_voice_hint()
            return {"type": "text", "data": f"[语音:{sl_voice_text}]"}

        # 兜底：返回占位符，不丢弃语音段
        return {"type": "text", "data": "[语音(识别失败)]"}

    async def _handle_video_message(self, segment: dict) -> SegPayload | None:
        """处理视频消息"""
        message_data = segment.get("data", {})

        video_url = message_data.get("url")
        file_path = message_data.get("filePath") or message_data.get("file_path")

        video_source = file_path if file_path else video_url
        if not video_source:
            logger.warning("视频消息缺少URL或文件路径信息")
            return {"type": "text", "data": "[视频消息]"}

        # 从配置读取视频处理参数
        io_timeout = 30.0
        max_size_mb = 100
        download_timeout = 60
        if self.adapter.plugin and self.adapter.plugin.config:
            config = cast(SnowLumaAdapterConfig, self.adapter.plugin.config)
            io_timeout = max(1.0, float(config.features.video_download_timeout))
            max_size_mb = config.features.video_max_size_mb
            download_timeout = config.features.video_download_timeout

        try:
            if file_path and Path(file_path).exists():
                # 本地文件处理
                async with asyncio.timeout(io_timeout):
                    video_data = await asyncio.to_thread(Path(file_path).read_bytes)
                video_base64 = await asyncio.to_thread(
                    base64_encode_bytes,
                    video_data,
                )
                logger.debug(f"视频文件大小: {len(video_data) / (1024 * 1024):.2f} MB")

                return {  # type: ignore[return-value]
                    "type": "video",
                    "data": {
                        "base64": video_base64,
                        "filename": Path(file_path).name,
                        "size_mb": len(video_data) / (1024 * 1024),
                    },
                }
            elif video_url:
                # URL下载处理 - 使用配置参数创建下载器
                from ..video_handler import VideoDownloader
                downloader = VideoDownloader(
                    max_size_mb=max_size_mb,
                    download_timeout=download_timeout,
                )

                download_result = await downloader.download_video(video_url)

                if not download_result["success"]:
                    logger.warning(f"视频下载失败: {download_result.get('error', '未知错误')}")
                    return {"type": "text", "data": f"[视频消息] ({download_result.get('error', '下载失败')})"}

                video_base64 = await asyncio.to_thread(
                    base64_encode_bytes,
                    download_result["data"],
                )
                logger.debug(f"视频下载成功，大小: {len(download_result['data']) / (1024 * 1024):.2f} MB")

                return {  # type: ignore[return-value]
                    "type": "video",
                    "data": {
                        "base64": video_base64,
                        "filename": download_result.get("filename", "video.mp4"),
                        "size_mb": len(download_result["data"]) / (1024 * 1024),
                        "url": video_url,
                    },
                }
            else:
                logger.warning("既没有有效的本地文件路径，也没有有效的视频URL")
                return {"type": "text", "data": "[视频消息]"}

        except TimeoutError:
            logger.error(f"视频消息处理超时: {video_source}")
            return {"type": "text", "data": "[视频处理超时]"}
        except Exception as e:
            logger.error(f"视频消息处理失败: {e!s}")
            return {"type": "text", "data": "[视频消息处理出错]"}

    async def _handle_rps_message(self, segment: dict) -> SegPayload:
        """处理猜拳消息"""
        message_data = segment.get("data", {})
        res = message_data.get("result", "")
        shape_map = {"1": "布", "2": "剪刀"}
        shape = shape_map.get(res, "石头")
        return {"type": "text", "data": f"[发送了一个魔法猜拳表情，结果是：{shape}]"}

    async def _handle_dice_message(self, segment: dict) -> SegPayload:
        """处理骰子消息"""
        message_data = segment.get("data", {})
        res = message_data.get("result", "")
        return {"type": "text", "data": f"[扔了一个骰子，点数是{res}]"}


    async def handle_forward_message(self, message_list: list[dict[str, Any]]) -> SegPayload | None:
        """
        递归处理转发消息，并按照动态方式确定图片处理方式

        Args:
            message_list: 转发消息列表

        Returns:
            处理后的消息段，失败返回 None
        """
        handled_message, image_count = await self._handle_forward_message(message_list, 0)
        if not handled_message:
            return None

        if 0 < image_count < 5:
            logger.debug("图片数量小于5，开始解析图片为base64")
            processed_message = await self._recursive_parse_image_seg(handled_message, True)
        elif image_count > 0:
            logger.debug("图片数量大于等于5，开始解析图片为占位符")
            processed_message = await self._recursive_parse_image_seg(handled_message, False)
        else:
            logger.debug("没有图片，直接返回")
            processed_message = handled_message

        forward_hint = {"type": "text", "data": "这是一条转发消息：\n"}
        # 扁平化：将内层 seglist 内容直接展开，避免额外嵌套层级
        if isinstance(processed_message, dict) and processed_message.get("type") == "seglist":
            return {"type": "seglist", "data": [forward_hint, *processed_message["data"]]}  # type: ignore[return-value]
        return {"type": "seglist", "data": [forward_hint, processed_message]}  # type: ignore[return-value]

    async def _recursive_parse_image_seg(
        self, seg_data: SegPayload, to_image: bool
    ) -> SegPayload:
        # sourcery skip: merge-else-if-into-elif
        if seg_data.get("type") == "seglist":
            new_seg_list = []
            for i_seg in seg_data.get("data", []):
                parsed_seg = await self._recursive_parse_image_seg(i_seg, to_image)  # type: ignore[arg-type]
                new_seg_list.append(parsed_seg)
            return {"type": "seglist", "data": new_seg_list}

        if to_image:
            if seg_data.get("type") == "image":
                image_url = seg_data.get("data")
                try:
                    encoded_image = await get_image_base64(str(image_url))
                except Exception as e:
                    logger.error(f"图片处理失败: {e!s}")
                    return {"type": "text", "data": "[图片]"}
                return {"type": "image", "data": encoded_image}
            if seg_data.get("type") == "emoji":
                image_url = seg_data.get("data")
                try:
                    encoded_image = await get_image_base64(str(image_url))
                except Exception as e:
                    logger.error(f"图片处理失败: {e!s}")
                    return {"type": "text", "data": "[表情包]"}
                return {"type": "emoji", "data": encoded_image}
            logger.debug(f"不处理类型: {seg_data.get('type')}")
            return seg_data

        if seg_data.get("type") == "image":
            return {"type": "text", "data": "[图片]"}
        if seg_data.get("type") == "emoji":
            return {"type": "text", "data": "[动画表情]"}
        logger.debug(f"不处理类型: {seg_data.get('type')}")
        return seg_data

    async def _handle_forward_message(
        self, message_list: list[dict[str, Any]] | None, layer: int
    ) -> tuple[SegPayload | None, int]:
        # sourcery skip: low-code-quality
        """
        递归处理实际转发消息
        Parameters:
            message_list: list: 转发消息列表，首层对应messages字段，后面对应content字段
            layer: int: 当前层级
        Returns:
            seg_data: Seg: 处理后的消息段
            image_count: int: 图片数量
        """
        seg_list: list[SegPayload] = []
        image_count = 0
        if message_list is None:
            return None, 0
        for sub_message in message_list:
            sender_info: dict = sub_message.get("sender", {})
            user_nickname: str = sender_info.get("nickname") or sender_info.get("card") or "QQ用户"
            user_id: str = str(sender_info.get("user_id") or "")
            user_nickname_str = f"【{user_nickname}({user_id})】:" if user_id else f"【{user_nickname}】:"
            break_seg: SegPayload = {"type": "text", "data": "\n"}
            nickname_prefix = ("--" * layer) + user_nickname_str if layer > 0 else user_nickname_str
            message_of_sub_message_list: list[dict[str, Any]] = sub_message.get("message", [])
            if not message_of_sub_message_list:
                logger.warning("转发消息内容为空")
                continue

            # 遍历子消息中的所有消息段（支持多段消息，如"文字+图片"）
            sub_segs: list[SegPayload] = []
            for msg_seg in message_of_sub_message_list:
                msg_type = msg_seg.get("type")
                if msg_type == RealMessageType.forward:
                    if layer >= 3:
                        sub_segs.append({"type": "text", "data": "【转发消息】\n"})
                    else:
                        sub_seg_data = msg_seg.get("data")
                        if not sub_seg_data:
                            continue
                        # 嵌套转发消息可能只有 id（需要再次调用 API 获取）或已有 content（内联展开）
                        contents = sub_seg_data.get("content")
                        if contents is None:
                            # 嵌套转发段只有 id，调用 get_forward_msg 获取内容
                            contents = await get_forward_message(msg_seg, adapter=self.adapter)
                            if contents is None:
                                logger.warning(f"嵌套转发消息获取失败(layer={layer})，使用占位符: id={sub_seg_data.get('id')}")
                                sub_segs.append({"type": "text", "data": "【转发消息】\n"})
                                continue
                        seg_data_opt, count = await self._handle_forward_message(contents, layer + 1)
                        if seg_data_opt is None:
                            continue
                        image_count += count
                        # 扁平化：文本前缀 + 内层 seglist 内容直接展开到 sub_segs，避免额外嵌套层级
                        sub_segs.append({"type": "text", "data": "合并转发消息内容：\n"})
                        if isinstance(seg_data_opt, dict) and seg_data_opt.get("type") == "seglist":
                            sub_segs.extend(seg_data_opt["data"])  # type: ignore[arg-type]
                        else:
                            sub_segs.append(seg_data_opt)
                elif msg_type == RealMessageType.text:
                    sub_seg_data = msg_seg.get("data")
                    if not sub_seg_data:
                        continue
                    text_message = sub_seg_data.get("text")
                    sub_segs.append({"type": "text", "data": text_message})
                elif msg_type == RealMessageType.image:
                    image_count += 1
                    image_data = msg_seg.get("data", {})
                    image_url = image_data.get("url")
                    if not image_url:
                        logger.warning("转发消息图片缺少URL")
                        continue
                    sub_type = image_data.get("sub_type")
                    if sub_type == 0:
                        sub_segs.append({"type": "image", "data": image_url})
                    else:
                        sub_segs.append({"type": "emoji", "data": image_url})
                else:
                    logger.debug(f"合并转发中未处理段类型: {msg_type}")

            if sub_segs:
                # 扁平化：将 nickname_prefix + sub_segs + break_seg 直接展开到 seg_list，避免每条子消息额外包一层 seglist
                seg_list.append({"type": "text", "data": nickname_prefix})
                seg_list.extend(sub_segs)
                seg_list.append(break_seg)
        return {"type": "seglist", "data": seg_list}, image_count

    async def _handle_contact_message(self, segment: dict) -> SegPayload | None:
        """处理推荐名片/群名片消息（OneBot v11 contact 段）。

        OneBot v11 的 ``contact`` 段有 ``type`` 字段区分 ``qq``（个人名片）和 ``group``（群名片），
        data 中包含 ``user_id``/``nickname`` 或 ``group_id``/``group_name``。
        """
        message_data = segment.get("data", {})
        if not message_data:
            logger.warning("名片消息缺少 data 字段")
            return None

        contact_type = message_data.get("type", "qq")
        if contact_type == "group":
            group_id = message_data.get("group_id", "")
            group_name = message_data.get("group_name") or message_data.get("name", "")
            logger.debug(f"收到群名片: id={group_id}, name={group_name}")
            if not group_id and not group_name:
                logger.warning("群名片消息缺少 group_id 和 group_name")
                return None
            return {"type": "text", "data": f"[群名片：{group_name}({group_id})]"}
        else:
            user_id = message_data.get("user_id", "")
            nickname = message_data.get("nickname") or message_data.get("name", "")
            logger.debug(f"收到个人名片: id={user_id}, name={nickname}")
            if not user_id and not nickname:
                logger.warning("个人名片消息缺少 user_id 和 nickname")
                return None
            return {"type": "text", "data": f"[个人名片：{nickname}({user_id})]"}

    async def _handle_file_message(self, segment: dict) -> SegPayload | None:
        """处理文件消息"""
        message_data = segment.get("data", {})
        if not message_data:
            logger.warning("文件消息缺少 data 字段")
            return None

        # 提取文件信息
        file_name = message_data.get("file")
        file_size = message_data.get("file_size")
        file_id = message_data.get("file_id")

        logger.info(f"收到文件消息: name={file_name}, size={file_size}, id={file_id}")

        # 将文件信息打包成字典
        file_data = {
            "name": file_name,
            "size": file_size,
            "id": file_id,
        }

        return {"type": "file", "data": file_data}  # type: ignore[return-value]

    async def _handle_json_message(self, segment: dict) -> SegPayload | None:
        """
        处理JSON消息
        Parameters:
            segment: dict: 消息段
        Returns:
            SegPayload | None: 处理后的消息段
        """
        message_data = segment.get("data", {})
        json_data = message_data.get("data", "")

        # 检查JSON消息格式
        if not message_data or "data" not in message_data:
            logger.warning("JSON消息格式不正确")
            return {"type": "json", "data": str(message_data)}

        try:
            # 尝试将json_data解析为Python对象
            nested_data = orjson.loads(json_data)

            # 检查是否是机器人自己上传文件的回声
            if self._is_file_upload_echo(nested_data):
                logger.info("检测到机器人发送文件的回声消息，将作为文件消息处理")
                # 从回声消息中提取文件信息
                file_info = self._extract_file_info_from_echo(nested_data)
                if file_info:
                    return {"type": "file", "data": file_info}  # type: ignore[return-value]

            # 检查是否是QQ小程序分享消息
            if "app" in nested_data and "com.tencent.miniapp" in str(nested_data.get("app", "")):
                logger.debug("检测到QQ小程序分享消息，开始提取信息")

                # 提取目标字段
                extracted_info = {}

                # 提取 meta.detail_1 中的信息
                meta = nested_data.get("meta", {})
                detail_1 = meta.get("detail_1", {})

                if detail_1:
                    extracted_info["title"] = detail_1.get("title", "")
                    extracted_info["desc"] = detail_1.get("desc", "")
                    qqdocurl = detail_1.get("qqdocurl", "")

                    # 从qqdocurl中提取b23.tv短链接
                    if qqdocurl and "b23.tv" in qqdocurl:
                        # 查找b23.tv链接的起始位置
                        start_pos = qqdocurl.find("https://b23.tv/")
                        if start_pos != -1:
                            # 提取从https://b23.tv/开始的部分
                            b23_part = qqdocurl[start_pos:]
                            # 查找第一个?的位置，截取到?之前
                            question_pos = b23_part.find("?")
                            if question_pos != -1:
                                extracted_info["short_url"] = b23_part[:question_pos]
                            else:
                                extracted_info["short_url"] = b23_part
                        else:
                            extracted_info["short_url"] = qqdocurl
                    else:
                        extracted_info["short_url"] = qqdocurl

                # 如果成功提取到关键信息，返回格式化的文本
                if extracted_info.get("title") or extracted_info.get("desc") or extracted_info.get("short_url"):
                    content_parts = []

                    if extracted_info.get("title"):
                        content_parts.append(f"来源: {extracted_info['title']}")

                    if extracted_info.get("desc"):
                        content_parts.append(f"标题: {extracted_info['desc']}")

                    if extracted_info.get("short_url"):
                        content_parts.append(f"链接: {extracted_info['short_url']}")

                    formatted_content = "\n".join(content_parts)
                    return{
                        "type": "text",
                        "data": f"这是一条小程序分享消息，可以根据来源，考虑使用对应解析工具\n{formatted_content}",
                    }



            # 检查是否是音乐分享 (QQ音乐类型)
            if nested_data.get("view") == "music" and "com.tencent.music" in str(nested_data.get("app", "")):
                meta = nested_data.get("meta", {})
                music = meta.get("music", {})
                if music:
                    tag = music.get("tag", "未知来源")
                    logger.debug(f"检测到【{tag}】音乐分享消息 (music view)，开始提取信息")

                    title = music.get("title", "未知歌曲")
                    desc = music.get("desc", "未知艺术家")
                    jump_url = music.get("jumpUrl", "")
                    preview_url = music.get("preview", "")

                    artist = "未知艺术家"
                    song_title = title

                    if "网易云音乐" in tag:
                        artist = desc
                    elif "QQ音乐" in tag:
                        if " - " in title:
                            parts = title.split(" - ", 1)
                            song_title = parts[0]
                            artist = parts[1]
                        else:
                            artist = desc

                    formatted_content = (
                        f"这是一张来自【{tag}】的音乐分享卡片：\n"
                        f"歌曲: {song_title}\n"
                        f"艺术家: {artist}\n"
                        f"跳转链接: {jump_url}\n"
                        f"封面图: {preview_url}"
                    )
                    return {"type": "text", "data": formatted_content}

            # 检查是否是新闻/图文分享 (网易云音乐可能伪装成这种)
            elif nested_data.get("view") == "news" and "com.tencent.tuwen" in str(nested_data.get("app", "")):
                meta = nested_data.get("meta", {})
                news = meta.get("news", {})
                if news and "网易云音乐" in news.get("tag", ""):
                    tag = news.get("tag")
                    logger.debug(f"检测到【{tag}】音乐分享消息 (news view)，开始提取信息")

                    title = news.get("title", "未知歌曲")
                    desc = news.get("desc", "未知艺术家")
                    jump_url = news.get("jumpUrl", "")
                    preview_url = news.get("preview", "")

                    formatted_content = (
                        f"这是一张来自【{tag}】的音乐分享卡片：\n"
                        f"标题: {title}\n"
                        f"描述: {desc}\n"
                        f"跳转链接: {jump_url}\n"
                        f"封面图: {preview_url}"
                    )
                    return {"type": "text", "data": formatted_content}

            # 检查是否是名片分享卡片 (com.tencent.contact.lua)
            # 群名片和个人名片都使用此 app 类型，通过 bizsrc / tag 区分
            if "com.tencent.contact" in str(nested_data.get("app", "")):
                logger.debug("检测到名片JSON消息，开始提取信息")
                meta = nested_data.get("meta", {})
                contact = meta.get("contact", {})
                if not contact:
                    logger.warning("名片JSON缺少 meta.contact 字段")
                    return None

                bizsrc = str(nested_data.get("bizsrc", ""))
                tag = str(contact.get("tag", ""))
                nickname = contact.get("nickname", "") or contact.get("name", "")
                jump_url = str(contact.get("jumpUrl", ""))
                legacy_url = str(contact.get("legacyUrl", ""))

                # 判断是群名片还是个人名片：
                # 群名片 bizsrc="qun.share"，jumpUrl 含 card_type=group，legacyUrl 含 group_code=
                is_group_card = (
                    bizsrc == "qun.share"
                    or "card_type=group" in jump_url
                    or "group_code=" in legacy_url
                    or tag == "群名片"
                )

                if is_group_card:
                    logger.debug(f"识别为群名片: nickname={nickname}")
                    # 从 legacyUrl 提取 group_code，从 jumpUrl 提取 uin
                    group_id = ""
                    if "group_code=" in legacy_url:
                        group_id = self._extract_param(legacy_url, "group_code")
                    if not group_id and "uin=" in jump_url:
                        group_id = self._extract_param(jump_url, "uin")
                    group_memo = contact.get("contact", "")

                    parts = []
                    if nickname:
                        parts.append(f"群名: {nickname}")
                    if group_id:
                        parts.append(f"群号: {group_id}")
                    if group_memo:
                        parts.append(f"简介: {group_memo}")
                    return {
                        "type": "text",
                        "data": f"这是一条群名片分享消息\n{chr(10).join(parts)}",
                    }
                else:
                    logger.debug(f"识别为个人名片: nickname={nickname}")
                    # 从 contact 字段 "账号：1936860600" 或 jumpUrl 的 uin 提取 user_id
                    user_id = ""
                    contact_text = str(contact.get("contact", ""))
                    if "账号" in contact_text:
                        # 提取冒号后的数字
                        match = re.search(r"(\d+)", contact_text)
                        if match:
                            user_id = match.group(1)
                    if not user_id and "uin=" in jump_url:
                        user_id = self._extract_param(jump_url, "uin")

                    parts = []
                    if nickname:
                        parts.append(f"昵称: {nickname}")
                    if user_id:
                        parts.append(f"QQ号: {user_id}")
                    return {
                        "type": "text",
                        "data": f"这是一条个人名片分享消息\n{chr(10).join(parts)}",
                    }

            # 如果没有提取到关键信息，返回None
            return None

        except orjson.JSONDecodeError:
            # 如果解析失败，我们假设它不是我们关心的任何一种结构化JSON，
            # 而是普通的文本或者无法解析的格式。
            logger.debug(f"无法将data字段解析为JSON: {json_data}")
            return None
        except Exception as e:
            logger.error(f"处理JSON消息时发生未知错误: {e}")
            return None

    @staticmethod
    def _extract_param(url: str, param: str) -> str:
        """从 URL 查询字符串中提取指定参数值。

        Args:
            url: 包含查询参数的 URL 字符串
            param: 要提取的参数名

        Returns:
            参数值字符串，未找到时返回空字符串
        """
        if not url or not param:
            return ""
        # 用正则提取 param=value，值匹配到 & 或字符串末尾或 # 之前
        pattern = rf"{re.escape(param)}=([^&#]+)"
        match = re.search(pattern, url)
        return match.group(1) if match else ""

    def _is_file_upload_echo(self, nested_data: Any) -> bool:
        """检查一个JSON对象是否是机器人自己上传文件的回声消息"""
        if not isinstance(nested_data, dict):
            return False

        # 检查 'app' 和 'meta' 字段是否存在
        if "app" not in nested_data or "meta" not in nested_data:
            return False

        # 检查 'app' 字段是否包含 'com.tencent.miniapp'
        if "com.tencent.miniapp" not in str(nested_data.get("app", "")):
            return False

        # 检查 'meta' 内部的 'detail_1' 的 'busi_id' 是否为 '1014'
        meta = nested_data.get("meta", {})
        detail_1 = meta.get("detail_1", {})
        if detail_1.get("busi_id") == "1014":
            return True

        return False

    def _extract_file_info_from_echo(self, nested_data: dict) -> dict | None:
        """从文件上传的回声消息中提取文件信息"""
        try:
            meta = nested_data.get("meta", {})
            detail_1 = meta.get("detail_1", {})

            # 文件名在 'desc' 字段
            file_name = detail_1.get("desc")

            # 文件大小在 'summary' 字段，格式为 "大小：1.7MB"
            summary = detail_1.get("summary", "")
            file_size_str = summary.replace("大小：", "").strip() # 移除前缀和空格

            # QQ API有时返回的大小不标准，这里我们只提取它给的字符串
            # 实际大小已经由 SnowLuma 在发送时记录，这里主要是为了保持格式一致

            if file_name and file_size_str:
                return {"file": file_name, "file_size": file_size_str, "file_id": None} # file_id在回声中不可用
        except Exception as e:
            logger.error(f"从文件回声中提取信息失败: {e}")

        return None

