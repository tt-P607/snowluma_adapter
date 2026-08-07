"""通知事件处理器。

将 notice 事件构建为 Message 并注入到内存 ChatStream 上下文的
unread_messages 中，不写入数据库，仅在当前运行态可见。
"""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING, Any

from mofox_wire import SegPayload, UserInfoPayload
from mofox_wire.types import UserRole

from src.app.plugin_system.api.log_api import get_logger
from src.core.models.message import Message, MessageType

from ...event_models import QQ_FACE, NoticeType, RealMessageType
from ..utils import (
    get_group_info,
    get_image_base64,
    get_member_info,
    get_message_detail,
    get_self_info,
    get_stranger_info,
    sanitize_text,
)

if TYPE_CHECKING:
    from ....plugin import SnowLumaAdapter

logger = get_logger("snowluma_adapter")


class NoticeHandler:
    """处理 SnowLuma 通知事件（戳一戳、表情回复、禁言、文件上传等）"""

    def __init__(self, adapter: "SnowLumaAdapter"):
        self.adapter = adapter
        # 戳一戳防抖时间戳
        self.last_poke_time: float = 0.0

    async def handle_notice(self, raw: dict[str, Any]) -> None:
        """处理通知事件并注入到内存上下文。

        构建 Message（MessageType.NOTICE）后插入到 ChatStream 的
        unread_messages 中，确保在下次对话时 LLM 能看到。

        - 不写入数据库（重启后丢失）
        - 不会主动唤醒 Bot（notice 不 @bot，不触发回复）
        - content 前缀 [notice] 标记类型，LLM 能区分系统通知和普通消息

        Args:
            raw: SnowLuma 原始通知数据
        """
        notice_type = raw.get("notice_type")
        message_time: float = time.time()

        self_id = raw.get("self_id")
        group_id = raw.get("group_id")
        user_id = raw.get("user_id")
        target_id = raw.get("target_id")

        handled_segment: SegPayload | None = None
        user_info: UserInfoPayload | None = None
        notice_config: dict[str, Any] = {
            "is_notice": False,
            "is_public_notice": False,
            "target_id": target_id,
        }

        match notice_type:
            case NoticeType.friend_recall:
                if (
                    not self.adapter.plugin
                    or not self.adapter.plugin.config
                    or self.adapter.plugin.config.features.enable_recall  # type: ignore[attr-defined]
                ):
                    logger.info("[#FAB387]好友撤回一条消息[/#FAB387]")
                    await self._handle_recall(raw, is_group=False, message_time=message_time)
                return

            case NoticeType.group_recall:
                if (
                    not self.adapter.plugin
                    or not self.adapter.plugin.config
                    or self.adapter.plugin.config.features.enable_recall  # type: ignore[attr-defined]
                ):
                    logger.info("[#FAB387]群内用户撤回一条消息[/#FAB387]")
                    await self._handle_recall(raw, is_group=True, message_time=message_time)
                return

            case NoticeType.notify:
                sub_type = raw.get("sub_type")
                match sub_type:
                    case NoticeType.Notify.poke:
                        # 检查是否启用戳一戳功能
                        if (
                            not self.adapter.plugin
                            or not self.adapter.plugin.config
                            or self.adapter.plugin.config.features.enable_poke  # type: ignore[attr-defined]
                        ):
                            logger.debug("处理戳一戳消息")
                            handled_segment, user_info = await self._handle_poke_notify(raw, group_id, user_id)
                            if handled_segment and user_info:
                                notice_config["notice_type"] = "poke"
                                notice_config["is_notice"] = True
                            else:
                                logger.debug("戳一戳消息被忽略（非针对自己或防抖），跳过")
                                return
                        else:
                            logger.warning("戳一戳消息被禁用，取消戳一戳处理")
                            return

                    case NoticeType.Notify.input_status:
                        # 正在输入状态通知，无需处理
                        return

                    case _:
                        logger.warning(f"不支持的notify类型: {notice_type}.{sub_type}，将原始数据包装为消息后抛出")
                        handled_segment, user_info = await self._handle_raw_passthrough(raw, notice_type)
                        if handled_segment and user_info:
                            notice_config["notice_type"] = str(notice_type)
                            notice_config["raw"] = raw
                        else:
                            return

            case NoticeType.group_msg_emoji_like:
                # 检查是否启用表情回复功能
                if (
                    not self.adapter.plugin
                    or not self.adapter.plugin.config
                    or self.adapter.plugin.config.features.enable_emoji_like  # type: ignore[attr-defined]
                ):
                    # 过滤机器人自己贴表情的回声，避免重复动作
                    if str(user_id) == str(self_id):
                        logger.debug("忽略机器人自己贴表情的notice回声")
                        return
                    logger.debug("处理群聊表情回复")
                    handled_segment, user_info = await self._handle_group_emoji_like_notify(
                        raw, group_id, user_id
                    )
                    if handled_segment and user_info:
                        notice_config["notice_type"] = "emoji_like"
                        notice_config["is_notice"] = True
                    else:
                        logger.debug("表情回复消息处理失败，跳过")
                        return
                else:
                    logger.warning("群聊表情回复被禁用，取消群聊表情回复处理")
                    return

            case NoticeType.group_ban:
                sub_type = raw.get("sub_type")
                match sub_type:
                    case NoticeType.GroupBan.ban:
                        logger.info("[#FAB387]处理群禁言[/#FAB387]")
                        handled_segment, user_info = await self._handle_ban_notify(raw, group_id)
                        if handled_segment and user_info:
                            user_id_in_ban = raw.get("user_id")
                            if user_id_in_ban == 0:
                                notice_config["notice_type"] = "group_whole_ban"
                            else:
                                notice_config["notice_type"] = "group_ban"
                            notice_config["is_notice"] = True
                        else:
                            return

                    case NoticeType.GroupBan.lift_ban:
                        logger.info("[#FAB387]处理解除群禁言[/#FAB387]")
                        handled_segment, user_info = await self._handle_lift_ban_notify(raw, group_id)
                        if handled_segment and user_info:
                            user_id_in_ban = raw.get("user_id")
                            if user_id_in_ban == 0:
                                notice_config["notice_type"] = "group_whole_lift_ban"
                            else:
                                notice_config["notice_type"] = "group_lift_ban"
                            notice_config["is_notice"] = True
                        else:
                            return

                    case _:
                        logger.warning(f"不支持的group_ban类型: {notice_type}.{sub_type}，将原始数据包装为消息后抛出")
                        handled_segment, user_info = await self._handle_raw_passthrough(raw, notice_type)
                        if handled_segment and user_info:
                            notice_config["notice_type"] = str(notice_type)
                            notice_config["raw"] = raw
                        else:
                            return

            case NoticeType.group_upload:
                logger.info("[#FAB387]群文件上传[/#FAB387]")
                if user_id == self_id:
                    logger.info("检测到机器人自己上传文件，忽略此通知")
                    return
                handled_segment, user_info = await self._handle_group_upload_notify(
                    raw, group_id, user_id, self_id
                )
                if handled_segment and user_info:
                    notice_config["notice_type"] = "group_upload"
                    notice_config["is_notice"] = True
                else:
                    return

            case NoticeType.group_increase:
                logger.info("[#FAB387]群成员入群[/#FAB387]")
                handled_segment, user_info = await self._handle_group_increase_notify(
                    raw, group_id, user_id
                )
                if handled_segment and user_info:
                    notice_config["notice_type"] = "group_increase"
                    notice_config["is_notice"] = True
                else:
                    return

            case NoticeType.group_decrease:
                logger.info("[#FAB387]群成员退群[/#FAB387]")
                handled_segment, user_info = await self._handle_group_decrease_notify(
                    raw, group_id, user_id
                )
                if handled_segment and user_info:
                    notice_config["notice_type"] = "group_decrease"
                    notice_config["is_notice"] = True
                else:
                    return

            case NoticeType.group_admin:
                logger.info("[#FAB387]群管理员变动[/#FAB387]")
                handled_segment, user_info = await self._handle_group_admin_notify(
                    raw, group_id, user_id
                )
                if handled_segment and user_info:
                    notice_config["notice_type"] = "group_admin"
                    notice_config["is_notice"] = True
                else:
                    return

            case NoticeType.essence:
                logger.info("[#FAB387]精华消息变动[/#FAB387]")
                handled_segment, user_info = await self._handle_essence_notify(
                    raw, group_id, user_id
                )
                if handled_segment and user_info:
                    notice_config["notice_type"] = "essence"
                    notice_config["is_notice"] = True
                else:
                    return

            case _:
                logger.warning(f"不支持的notice类型: {notice_type}，将原始数据包装为消息后抛出")
                handled_segment, user_info = await self._handle_raw_passthrough(raw, notice_type)
                if handled_segment and user_info:
                    notice_config["notice_type"] = str(notice_type)
                    notice_config["raw"] = raw
                else:
                    return

        if not handled_segment or not user_info:
            logger.warning("notice处理失败或不支持")
            return

        # 生成可读的 text_description
        seg_type = handled_segment.get("type", "text")
        seg_data_content = handled_segment.get("data", "")
        if seg_type == "text" and isinstance(seg_data_content, str):
            notice_config["text_description"] = seg_data_content
        elif seg_type == "notify" and isinstance(seg_data_content, dict):
            operator_name = (
                user_info.get("user_nickname")
                or user_info.get("user_cardname")
                or "某人"
            )
            sub_type_in_data = seg_data_content.get("sub_type", "")
            if sub_type_in_data == "ban":
                banned = seg_data_content.get("banned_user_info") or {}
                banned_name = banned.get("user_nickname") or "某人"
                duration = seg_data_content.get("duration", 0)
                notice_config["text_description"] = (
                    f"{operator_name}将{banned_name}禁言了{duration}秒"
                )
            elif sub_type_in_data == "whole_ban":
                notice_config["text_description"] = f"{operator_name}开启了全体禁言"
            elif sub_type_in_data == "lift_ban":
                lifted = seg_data_content.get("lifted_user_info") or {}
                lifted_name = lifted.get("user_nickname") or "某人"
                notice_config["text_description"] = (
                    f"{operator_name}解除了{lifted_name}的禁言"
                )
            elif sub_type_in_data == "whole_lift_ban":
                notice_config["text_description"] = f"{operator_name}关闭了全体禁言"
            else:
                notice_config["text_description"] = str(seg_data_content)
        else:
            notice_config["text_description"] = str(seg_data_content)

        # 生成唯一 notice ID
        _notice_id_raw = f"notice_{notice_type}_{user_id}_{group_id}_{message_time}"
        unique_notice_id = "notice_" + hashlib.md5(_notice_id_raw.encode()).hexdigest()[:16]

        # 构建 notice Message 并注入内存历史
        text_desc = notice_config.get("text_description", "")

        # 获取群名
        group_name: str | None = None
        if group_id:
            fetched_group_info = await get_group_info(group_id)
            if fetched_group_info:
                group_name = fetched_group_info.get("group_name")

        # 构建 stream_id
        from src.core.models.stream import ChatStream

        if group_id:
            stream_id = ChatStream.generate_stream_id(platform="qq", group_id=str(group_id))
            chat_type = "group"
        else:
            stream_id = ChatStream.generate_stream_id(
                platform="qq", user_id=str(user_info.get("user_id", ""))
            )
            chat_type = "private"

        # 构建 [notice] {类型标签} {内容} 格式的文本
        _NOTICE_TYPE_LABELS: dict[str, str] = {
            "poke": "戳一戳",
            "emoji_like": "贴表情",
            "group_ban": "禁言",
            "group_whole_ban": "全体禁言",
            "group_lift_ban": "解除禁言",
            "group_whole_lift_ban": "解除全体禁言",
            "group_upload": "文件上传",
            "group_increase": "入群",
            "group_decrease": "退群",
            "group_admin": "管理员变动",
            "essence": "精华消息",
        }
        _notice_type_str = str(notice_config.get("notice_type", "notice"))
        _type_label = _NOTICE_TYPE_LABELS.get(_notice_type_str, _notice_type_str)
        _notice_content = f"[notice] {_type_label} {text_desc}"

        notice_message = Message(
            message_id=unique_notice_id,
            time=message_time,
            content=_notice_content,
            processed_plain_text=_notice_content,
            message_type=MessageType.NOTICE,
            sender_id=str(user_info.get("user_id", "")),
            sender_name=user_info.get("user_nickname", ""),
            sender_cardname=user_info.get("user_cardname"),
            platform="qq",
            chat_type=chat_type,
            stream_id=stream_id,
            raw_data=raw,
            extra={
                "is_notice": True,
                "notice_type": notice_config.get("notice_type", "unknown"),
                "group_id": str(group_id) if group_id else "",
                "group_name": group_name or "",
                **({"raw": notice_config["raw"]} if "raw" in notice_config else {}),
            },
        )

        await self._inject_notice_to_unread(stream_id, notice_message)
        logger.info(f"notice 已注入未读消息: [#FAB387]{_notice_content}[/#FAB387]")

    async def _inject_notice_to_unread(self, stream_id: str, message: Message) -> None:
        """将 notice 消息注入到 ChatStream 的 unread_messages。

        写入 unread_messages 确保 LLM 在下次对话时能看到。
        不调用 StreamManager.add_message()，因此不写入数据库。

        Args:
            stream_id: 聊天流 ID
            message: 已构建好的 notice Message 对象
        """
        from src.core.managers.stream_manager import get_stream_manager

        sm = get_stream_manager()
        chat_stream = sm._streams.get(stream_id)
        if chat_stream is None:
            logger.debug(f"stream_id={stream_id[:8]}... 尚未创建，跳过 notice 注入")
            return

        chat_stream.context.add_unread_message(message)
        chat_stream.update_active_time()

    async def _handle_raw_passthrough(
        self, raw: dict[str, Any], notice_type: Any
    ) -> tuple[SegPayload | None, UserInfoPayload | None]:
        """将不支持的 notice 原始数据转换为消息段与用户信息。

        对于暂未实现具体转换逻辑的 notice 类型，不丢弃数据，而是构造一个
        text 消息段承载可读描述，并返回最小化的用户信息。原始 raw 数据由
        调用方写入 ``notice_config["raw"]``，最终携带在 ``Message.raw_data``
        中供下游自行解析。

        Args:
            raw: SnowLuma 原始通知数据。
            notice_type: notice 类型字符串。

        Returns:
            包含可读描述的 text 消息段与最小化用户信息；处理失败返回 None。
        """
        user_id = raw.get("user_id") or raw.get("self_id") or ""
        group_id = raw.get("group_id")

        user_nickname = ""
        user_cardname = ""
        if group_id and user_id:
            user_qq_info: dict | None = await get_member_info(int(group_id), int(user_id))
        else:
            user_qq_info = await get_stranger_info(user_id) if user_id else None

        if user_qq_info:
            user_nickname = user_qq_info.get("nickname", "")
            user_cardname = sanitize_text(user_qq_info.get("card", "")) or ""
        else:
            logger.debug("无法获取未支持notice类型的用户昵称")

        user_info: UserInfoPayload = {
            "platform": "qq",
            "role": UserRole.MEMBER,  # type: ignore[typeddict-item]
            "user_id": str(user_id),
            "user_nickname": user_nickname,
            "user_cardname": user_cardname,
        }

        seg_data: SegPayload = {
            "type": "text",
            "data": f"[未支持的notice类型: {notice_type}]",
        }
        return seg_data, user_info

    async def _handle_recall(
        self, raw: dict[str, Any], *, is_group: bool, message_time: float
    ) -> None:
        """处理撤回通知，注入到内存历史。

        撤回通知格式：[notice] {操作者}撤回了消息[{message_id}]: {前5字}...
        会尝试通过 get_message_detail 获取被撤回消息的内容。

        Args:
            raw: SnowLuma 原始通知数据
            is_group: 是否群聊撤回
            message_time: 事件时间戳
        """
        recall_msg_id = str(raw.get("message_id", ""))
        operator_id = raw.get("operator_id") or raw.get("user_id", "")
        group_id = raw.get("group_id")

        # 获取操作者信息
        operator_name: str = "某人"
        if is_group and group_id:
            member_info: dict | None = await get_member_info(
                int(group_id) if group_id else 0,
                int(operator_id) if operator_id else 0,
            )
            if member_info:
                operator_name = member_info.get("card") or member_info.get("nickname", "某人")
        elif operator_id:
            stranger_info: dict | None = await get_stranger_info(operator_id)
            if stranger_info:
                operator_name = stranger_info.get("nickname", "某人")

        # 尝试获取被撤回消息的内容
        msg_preview = ""
        if recall_msg_id:
            try:
                msg_detail = await get_message_detail(recall_msg_id)
                if msg_detail:
                    # 提取消息文本内容
                    segments = msg_detail.get("message", [])
                    text_parts: list[str] = []
                    for seg in segments:
                        if seg.get("type") == "text":
                            text_parts.append(seg.get("data", {}).get("text", ""))
                    full_text = "".join(text_parts).strip()
                    if full_text:
                        msg_preview = full_text[:5] + ("..." if len(full_text) > 5 else "")
            except Exception as e:
                logger.debug(f"获取撤回消息内容失败: {e!s}")

        # 构建撤回通知文本
        recall_text = f"[notice] 撤回 {operator_name}撤回了消息[{recall_msg_id}]"
        if msg_preview:
            recall_text += f": {msg_preview}"

        # 生成唯一 notice ID
        _notice_id_raw = f"recall_{recall_msg_id}_{operator_id}_{group_id}_{message_time}"
        unique_notice_id = "notice_" + hashlib.md5(_notice_id_raw.encode()).hexdigest()[:16]

        # 构建 stream_id
        from src.core.models.stream import ChatStream

        if group_id:
            stream_id = ChatStream.generate_stream_id(platform="qq", group_id=str(group_id))
            chat_type = "group"
        else:
            stream_id = ChatStream.generate_stream_id(platform="qq", user_id=str(operator_id))
            chat_type = "private"

        notice_message = Message(
            message_id=unique_notice_id,
            time=message_time,
            content=recall_text,
            processed_plain_text=recall_text,
            message_type=MessageType.NOTICE,
            sender_id=str(operator_id),
            sender_name=operator_name,
            platform="qq",
            chat_type=chat_type,
            stream_id=stream_id,
            raw_data=raw,
            extra={
                "is_notice": True,
                "notice_type": "recall",
                "recall_message_id": recall_msg_id,
                "group_id": str(group_id) if group_id else "",
            },
        )

        await self._inject_notice_to_unread(stream_id, notice_message)
        logger.info(f"撤回通知已注入未读消息: [#FAB387]{recall_text}[/#FAB387]")

    async def _handle_poke_notify(
        self, raw: dict[str, Any], group_id: Any, user_id: Any
    ) -> tuple[SegPayload | None, UserInfoPayload | None]:
        """处理戳一戳通知"""
        self_info: dict | None = await get_self_info()

        if not self_info:
            logger.error("自身信息获取失败")
            return None, None

        self_id = raw.get("self_id")
        target_id = raw.get("target_id")

        # 防抖检查：如果是针对机器人的戳一戳，检查防抖时间
        if self_id == target_id:
            current_time = time.time()
            # 获取防抖时间配置
            debounce_seconds = 2.0
            if self.adapter.plugin and self.adapter.plugin.config:
                debounce_seconds = self.adapter.plugin.config.features.poke_debounce_seconds  # type: ignore[attr-defined]

            if self.last_poke_time > 0:
                time_diff = current_time - self.last_poke_time
                if time_diff < debounce_seconds:
                    logger.debug(
                        f"戳一戳防抖：用户 {user_id} 的戳一戳被忽略（距离上次戳一戳 {time_diff:.2f} 秒）"
                    )
                    return None, None

            self.last_poke_time = current_time

        target_name: str | None = None
        raw_info: list = raw.get("raw_info", [])

        if group_id:
            user_qq_info: dict | None = await get_member_info(int(group_id) if group_id else 0, int(user_id) if user_id else 0)
        else:
            user_qq_info: dict | None = await get_stranger_info(user_id)

        if user_qq_info:
            user_name = user_qq_info.get("nickname", "QQ用户")
            user_cardname = sanitize_text(user_qq_info.get("card", ""))
        else:
            user_name = "QQ用户"
            user_cardname = ""
            logger.debug("无法获取戳一戳对方的用户昵称")

        # 计算显示名称：群聊优先使用群名片（card），无名片时用昵称，并附带 QQ 号
        display_name = ""
        if self_id == target_id:
            target_name = self_info.get("nickname", "")
        elif self_id == user_id:
            # 不发送机器人戳别人的消息
            return None, None
        else:
            # 如果配置为忽略不是针对自己的戳一戳，则直接返回None
            if (
                self.adapter.plugin
                and self.adapter.plugin.config
                and self.adapter.plugin.config.features.ignore_non_self_poke  # type: ignore[attr-defined]
            ):
                logger.debug("忽略不是针对自己的戳一戳消息")
                return None, None

            if group_id:
                fetched_member_info: dict | None = await get_member_info(int(group_id) if group_id else 0, int(target_id) if target_id else 0)
                if fetched_member_info:
                    target_card = sanitize_text(fetched_member_info.get("card", ""))
                    target_name = target_card or fetched_member_info.get("nickname", "QQ用户")
                else:
                    target_name = "QQ用户"
                    logger.debug("无法获取被戳一戳方的用户昵称")
                # 发送者优先群名片，无名片用昵称，并附带 QQ 号便于识别
                sender_display = user_cardname or user_name
                display_name = f"{sender_display}({user_id})" if user_id else sender_display
                if target_id:
                    target_name = f"{target_name}({target_id})"
            else:
                return None, None

        # 解析戳一戳文本
        first_txt: str = "戳了戳"
        second_txt: str = ""
        try:
            if len(raw_info) > 2:
                first_txt = raw_info[2].get("txt", "戳了戳")
            if len(raw_info) > 4:
                second_txt = raw_info[4].get("txt", "")
        except Exception as e:
            logger.warning(f"解析戳一戳消息失败: {e!s}，将使用默认文本")

        user_info: UserInfoPayload = {
            "platform": "qq",
            "user_id": str(user_id),
            "user_nickname": user_name,
            "user_cardname": user_cardname,
            "role": "",  # type: ignore[typeddict-item]
        }

        seg_data: SegPayload = {
            "type": "text",
            "data": f"{display_name}{first_txt}{target_name}{second_txt}（这是QQ的一个功能，用于提及某人，但没那么明显）",
        }
        return seg_data, user_info

    async def _handle_group_emoji_like_notify(
        self, raw: dict[str, Any], group_id: Any, user_id: Any
    ) -> tuple[SegPayload | None, UserInfoPayload | None]:
        """处理群聊表情回复通知"""
        if not group_id:
            logger.error("群ID不能为空，无法处理群聊表情回复通知")
            return None, None

        user_qq_info: dict | None = await get_member_info(int(group_id) if group_id else 0, int(user_id) if user_id else 0)
        if user_qq_info:
            user_name = user_qq_info.get("nickname", "QQ用户")
            user_cardname = sanitize_text(user_qq_info.get("card", ""))
        else:
            user_name = "QQ用户"
            user_cardname = ""
            logger.debug("无法获取表情回复对方的用户昵称")

        # 触发事件
        from src.app.plugin_system.api import event_api

        from ...event_types import SnowLumaEvent

        target_message_id = raw.get("message_id", "")
        target_message_text = await self._get_message_preview(target_message_id)

        # 获取被回应消息的发送者。优先从服务端原始消息段解析 sender
        # （真实 user_id + 昵称），数据库 PersonInfo 仅作回退，避免 person_id
        # 非标准哈希时错位显示（如把媒体哈希或错误的 QQ 号拼到昵称后）。
        target_sender_name = ""
        if target_message_id:
            try:
                detail = await get_message_detail(target_message_id)
                detail_sender = (detail or {}).get("sender", {}) if detail else {}
                detail_user_id = str(detail_sender.get("user_id") or "")
                detail_nickname = str(
                    detail_sender.get("card") or detail_sender.get("nickname") or ""
                ).strip().replace("\n", " ").replace("\r", " ")
                if detail_user_id or detail_nickname:
                    target_sender_name = (
                        f"{detail_nickname}({detail_user_id})"
                        if detail_nickname and detail_user_id
                        else (detail_nickname or detail_user_id)
                    )
            except Exception as e:
                logger.debug(f"获取被回应消息发送者失败: {e!s}")

            # 服务端未提供 sender 时，回退到数据库 PersonInfo
            if not target_sender_name:
                try:
                    from src.core.models.sql_alchemy import Messages, PersonInfo
                    from src.kernel.db import QueryBuilder
                    from typing import cast

                    msg_record = cast(Messages | None, await (
                        QueryBuilder(Messages)
                        .filter(message_id=str(target_message_id))
                        .first()
                    ))
                    if msg_record:
                        person_id = msg_record.person_id
                        if person_id == "bot":
                            target_sender_name = "Bot"
                        elif person_id:
                            person_record = cast(PersonInfo | None, await (
                                QueryBuilder(PersonInfo)
                                .filter(person_id=person_id)
                                .first()
                            ))
                            if person_record:
                                nickname = (person_record.nickname or "").replace("\n", " ").replace("\r", " ")
                                cardname = (person_record.cardname or "").replace("\n", " ").replace("\r", " ")
                                display = cardname or nickname or ""
                                user_id = person_record.user_id or ""
                                target_sender_name = (
                                    f"{display}({user_id})" if display and user_id else display
                                )
                except Exception as e:
                    logger.debug(f"查询被回应消息记录失败: {e!s}")

        if not target_message_text:
            logger.error("未找到对应消息")
            return None, None

        # 发送者优先群名片，无名片用昵称，并附带 QQ 号便于识别
        sender_display = user_cardname or user_name
        sender_with_id = f"{sender_display}({user_id})" if user_id else sender_display

        user_info: UserInfoPayload = {
            "platform": "qq",
            "user_id": str(user_id),
            "user_nickname": user_name,
            "user_cardname": user_cardname,
            "role": "",  # type: ignore[typeddict-item]
        }

        likes_list = raw.get("likes", [])
        like_emoji_id = ""
        if likes_list and len(likes_list) > 0:
            like_emoji_id = str(likes_list[0].get("emoji_id", ""))

        # 触发表情回复事件
        await event_api.publish_event(
            SnowLumaEvent.ON_RECEIVED.EMOJI_LIEK,
            {
                "message_id": raw.get("message_id", ""), 
                "emoji_id": like_emoji_id, 
                "group_id": group_id, 
                "user_id": user_id
             }
        )

        emoji_text = QQ_FACE.get(like_emoji_id, f"[表情{like_emoji_id}]")
        seg_data: SegPayload = {
            "type": "text",
            "data": (
                f"{sender_with_id}使用Emoji表情{emoji_text}回应了{target_sender_name}的消息[{target_message_text}]"
                if target_sender_name
                else f"{sender_with_id}使用Emoji表情{emoji_text}回应了消息[{target_message_text}]"
            ),
        }
        return seg_data, user_info

    async def _get_message_preview(self, message_id: str) -> str | None:
        """获取消息预览文本。

        优先取数据库 ``processed_plain_text``——Bot 发送的媒体消息入库时
        已含 VLM/ASR 识别结果（如 ``[表情包:描述]``），比从服务端重取更
        可靠且省一次 API 调用。数据库仅含占位符（如 ``[图片]``）时，再
        从服务端 ``get_message_detail`` 取原始段并回查媒体描述。

        Args:
            message_id: 消息 ID

        Returns:
            消息预览文本；查询失败返回 None
        """
        if not message_id:
            return None

        db_preview: str | None = None
        try:
            from src.core.models.sql_alchemy import Messages
            from src.kernel.db import QueryBuilder
            from typing import cast

            msg_record = cast(Messages | None, await (
                QueryBuilder(Messages)
                .filter(message_id=message_id)
                .first()
            ))
            if msg_record and msg_record.processed_plain_text:
                db_preview = msg_record.processed_plain_text
        except Exception as e:
            logger.debug(f"查询消息预览失败: {e!s}")

        # DB 预览是纯占位符或 [picid:uuid] 形式时，尝试回查媒体描述
        if db_preview and db_preview not in ("[图片]", "[表情包]"):
            # 仅当预览是 [picid:uuid] 这类纯 ID 占位符时才回查描述，
            # 避免误伤普通文本（如含冒号的时间戳）
            if db_preview.startswith("[picid:") and db_preview.endswith("]"):
                try:
                    import re

                    uuid_match = re.search(r"picid:([0-9a-fA-F-]{36})", db_preview)
                    if uuid_match:
                        from src.app.plugin_system.api import media_api

                        info = await media_api.get_media_info(uuid_match.group(1))
                        description = (info or {}).get("description") if info else None
                        if isinstance(description, str) and description.strip():
                            return f"[图片:{self._truncate_preview(description.strip())}]"
                except Exception as e:
                    logger.debug(f"从 picid 回查媒体描述失败: {e!s}")
            return self._truncate_preview(db_preview)

        # DB 缺描述时，从服务端取原始消息段并回查媒体描述
        try:
            msg_detail = await get_message_detail(message_id)
            if msg_detail:
                preview = await self._extract_message_preview(msg_detail)
                if preview and preview != "[消息]":
                    return preview
        except Exception as e:
            logger.debug(f"获取消息详情失败: {e!s}")

        return db_preview or None

    async def _extract_message_preview(self, message_detail: dict[str, Any], depth: int = 0) -> str:
        """提取被表情回应消息的可读摘要，支持多层嵌套"""
        if depth > 3:
            return "..."

        preview_parts: list[str] = []
        for seg in message_detail.get("message", []):
            seg_type = seg.get("type")
            seg_data = seg.get("data", {})

            if seg_type == RealMessageType.text:
                preview_parts.append(seg_data.get("text", ""))
            elif seg_type == RealMessageType.face:
                face_id = str(seg_data.get("id", ""))
                preview_parts.append(QQ_FACE.get(face_id, f"[表情{face_id}]"))
            elif seg_type == RealMessageType.image:
                preview_parts.append(
                    await self._format_image_preview(seg_data)
                )
            elif seg_type == RealMessageType.at:
                at_name = seg_data.get("text") or seg_data.get("qq") or "未知对象"
                preview_parts.append(f"@{at_name}")
            elif seg_type == RealMessageType.reply:
                reply_id = seg_data.get("id")
                if reply_id:
                    reply_detail = await get_message_detail(reply_id)
                    nested_preview = await self._extract_message_preview(reply_detail or {}, depth + 1)
                    preview_parts.append(f"[回复:{nested_preview}]")
            elif seg_type == RealMessageType.forward:
                preview_parts.append("[转发消息]")
            elif seg_type == RealMessageType.file:
                file_name = seg_data.get("file") or seg_data.get("name") or "文件"
                preview_parts.append(f"[文件:{file_name}]")
            elif seg_type == RealMessageType.json:
                preview_parts.append("[卡片消息]")
            elif seg_type:
                preview_parts.append(f"[{seg_type}]")

        preview = "".join(preview_parts).strip() or "[消息]"
        # 含媒体占位符（[图片(hash):描述]）时放宽上限，保留完整 media_id；
        # 纯文本预览维持较短限制
        if preview.startswith(("[图片(", "[表情包(")):
            return self._truncate_preview(preview, max_len=130)
        return self._truncate_preview(preview)

    async def _format_image_preview(self, seg_data: dict[str, Any]) -> str:
        """格式化图片/表情包段预览，输出与框架多模态一致的占位符格式。

        从图片段的 ``file``（可能带 ``base64://`` 前缀）或 ``url`` 获取
        base64，计算媒体 SHA256，并经 ``media_api.recognize_media`` 命中
        VLM 描述缓存。命中描述输出 ``[图片(sha256):描述]``，仅有哈希输出
        ``[图片(sha256)]``，均无法获取时保留 ``[图片]`` 占位符。

        Args:
            seg_data: 图片段 data 字典

        Returns:
            格式化后的预览文本
        """
        is_emoji = seg_data.get("sub_type") != 0
        label = "表情包" if is_emoji else "图片"
        media_type = "emoji" if is_emoji else "image"

        # 优先从图片段取到 base64（file 可能带 base64:// 前缀，url 需下载）
        media_data: str | None = None
        file_raw = str(seg_data.get("file") or "").strip()
        if file_raw.startswith("base64://"):
            media_data = file_raw[len("base64://"):]
        elif file_raw.startswith(("http://", "https://")):
            try:
                media_data = await get_image_base64(file_raw)
            except Exception as e:
                logger.debug(f"下载图片失败: url={file_raw[:40]}, error={e!s}")
        else:
            url = str(seg_data.get("url") or "").strip()
            if url and url.startswith(("http://", "https://")):
                try:
                    media_data = await get_image_base64(url)
                except Exception as e:
                    logger.debug(f"下载图片失败: url={url[:40]}, error={e!s}")

        # 拿到 base64 后，计算媒体 SHA256 并回查 VLM 描述缓存，
        # 输出与框架多模态一致的标准格式 [图片(sha256):描述] / [图片(sha256)]
        if media_data:
            try:
                from src.core.managers.media_manager import MediaManager
                from src.app.plugin_system.api import media_api

                media_hash = MediaManager.compute_media_hash(media_data)
                if media_hash:
                    description = await media_api.recognize_media(
                        base64_data=media_data,
                        media_type=media_type,
                        use_cache=True,
                    )
                    desc_text = (
                        description.strip()
                        if isinstance(description, str) and description.strip()
                        else ""
                    )
                    # 预览用途，限制描述长度避免刷屏（媒体项整体可稍长以保留 hash）
                    if desc_text:
                        desc_text = self._truncate_preview(desc_text, max_len=40)
                        return f"[{label}({media_hash}):{desc_text}]"
                    return f"[{label}({media_hash})]"
            except Exception as e:
                logger.debug(f"识别媒体失败: error={e!s}")

        return f"[{label}]"

    @staticmethod
    def _truncate_preview(text: str, max_len: int = 60) -> str:
        """截断预览文本，超出部分以省略号结尾。

        Args:
            text: 原始文本
            max_len: 最大长度

        Returns:
            截断后的文本
        """
        text = text.replace("\n", " ").replace("\r", " ")
        if len(text) <= max_len:
            return text
        return text[:max_len] + "..."

    async def _handle_group_upload_notify(
        self, raw: dict[str, Any], group_id: Any, user_id: Any, self_id: Any
    ) -> tuple[SegPayload | None, UserInfoPayload | None]:
        """处理群文件上传通知"""
        if not group_id:
            logger.error("群ID不能为空，无法处理群文件上传通知")
            return None, None

        user_qq_info: dict | None = await get_member_info(int(group_id) if group_id else 0, int(user_id) if user_id else 0)
        if user_qq_info:
            user_name = user_qq_info.get("nickname", "QQ用户")
            user_cardname = sanitize_text(user_qq_info.get("card", ""))
        else:
            user_name = "QQ用户"
            user_cardname = ""
            logger.debug("无法获取上传文件的用户昵称")

        file_info = raw.get("file")
        if not file_info:
            logger.error("群文件上传通知中缺少文件信息")
            return None, None

        user_info: UserInfoPayload = {
            "platform": "qq",
            "user_id": str(user_id),
            "user_nickname": user_name,
            "user_cardname": user_cardname,
            "role": "",  # type: ignore[typeddict-item]
        }

        file_name = file_info.get("name", "未知文件")
        file_size = file_info.get("size", 0)

        seg_data: SegPayload = {
            "type": "text",
            "data": f"{user_name} 上传了文件: {file_name} (大小: {file_size} 字节)",
        }
        return seg_data, user_info

    async def _handle_ban_notify(
        self, raw: dict[str, Any], group_id: Any
    ) -> tuple[SegPayload | None, UserInfoPayload | None]:
        """处理群禁言通知"""
        if not group_id:
            logger.error("群ID不能为空，无法处理禁言通知")
            return None, None

        # 获取操作者信息
        operator_id = raw.get("operator_id")
        operator_nickname: str = "QQ用户"
        operator_cardname: str = ""

        member_info: dict | None = await get_member_info(int(group_id) if group_id else 0, int(operator_id) if operator_id else 0)
        if member_info:
            operator_nickname = member_info.get("nickname", "QQ用户")
            operator_cardname = sanitize_text(member_info.get("card", "")) or ""
        else:
            logger.warning("无法获取禁言执行者的昵称，消息可能会无效")

        operator_info: UserInfoPayload = {
            "platform": "qq",
            "user_id": str(operator_id),
            "user_nickname": operator_nickname,
            "user_cardname": operator_cardname,
            "role": "",  # type: ignore[typeddict-item]
        }

        # 获取被禁言者信息
        user_id = raw.get("user_id")
        banned_user_info: dict[str, Any] | None = None
        user_nickname: str = "QQ用户"
        user_cardname: str = ""
        sub_type: str = ""

        duration = raw.get("duration")
        if duration is None:
            logger.error("禁言时长不能为空，无法处理禁言通知")
            return None, None

        if user_id == 0:  # 全体禁言
            sub_type = "whole_ban"
        else:  # 单人禁言
            sub_type = "ban"
            fetched_member_info: dict | None = await get_member_info(int(group_id) if group_id else 0, int(user_id) if user_id else 0)
            if fetched_member_info:
                user_nickname = fetched_member_info.get("nickname", "QQ用户")
                user_cardname = sanitize_text(fetched_member_info.get("card", "")) or ""
            banned_user_info = {
                "platform": "qq",
                "user_id": str(user_id),
                "user_nickname": user_nickname,
                "user_cardname": user_cardname,
            }

        seg_data: SegPayload = {
            "type": "notify",
            "data": {  # type: ignore[typeddict-item]
                "sub_type": sub_type,
                "duration": duration,
                "banned_user_info": banned_user_info,
            },
        }

        return seg_data, operator_info

    async def _handle_lift_ban_notify(
        self, raw: dict[str, Any], group_id: Any
    ) -> tuple[SegPayload | None, UserInfoPayload | None]:
        """处理解除群禁言通知"""
        if not group_id:
            logger.error("群ID不能为空，无法处理解除禁言通知")
            return None, None

        # 获取操作者信息
        operator_id = raw.get("operator_id")
        operator_nickname: str = "QQ用户"
        operator_cardname: str = ""

        member_info: dict | None = await get_member_info(int(group_id) if group_id else 0, int(operator_id) if operator_id else 0)
        if member_info:
            operator_nickname = member_info.get("nickname", "QQ用户")
            operator_cardname = sanitize_text(member_info.get("card", "")) or ""
        else:
            logger.warning("无法获取解除禁言执行者的昵称，消息可能会无效")

        operator_info: UserInfoPayload = {
            "platform": "qq",
            "user_id": str(operator_id),
            "user_nickname": operator_nickname,
            "user_cardname": operator_cardname,
            "role": "",  # type: ignore[typeddict-item]
        }

        # 获取被解除禁言者信息
        sub_type: str = ""
        user_nickname: str = "QQ用户"
        user_cardname: str = ""
        lifted_user_info: dict[str, Any] | None = None

        user_id = raw.get("user_id")
        if user_id == 0:  # 全体禁言解除
            sub_type = "whole_lift_ban"
        else:  # 单人禁言解除
            sub_type = "lift_ban"
            fetched_member_info: dict | None = await get_member_info(int(group_id) if group_id else 0, int(user_id) if user_id else 0)
            if fetched_member_info:
                user_nickname = fetched_member_info.get("nickname", "QQ用户")
                user_cardname = sanitize_text(fetched_member_info.get("card", "")) or ""
            else:
                logger.warning("无法获取解除禁言消息发送者的昵称，消息可能会无效")
            lifted_user_info = {
                "platform": "qq",
                "user_id": str(user_id),
                "user_nickname": user_nickname,
                "user_cardname": user_cardname,
            }

        seg_data: SegPayload = {
            "type": "notify",
            "data": {  # type: ignore[typeddict-item]

                "sub_type": sub_type,
                "lifted_user_info": lifted_user_info,
            }
        }
        return seg_data, operator_info

    async def _handle_group_increase_notify(
        self, raw: dict[str, Any], group_id: Any, user_id: Any
    ) -> tuple[SegPayload | None, UserInfoPayload | None]:
        """处理群成员入群通知。

        OneBot v11 ``group_increase`` 事件字段：
        - ``sub_type``: ``approve``（审批通过）/ ``invite``（被邀请）
        - ``operator_id``: 操作者（审批人/邀请人）
        - ``user_id``: 入群者

        Args:
            raw: 原始通知数据
            group_id: 群 ID
            user_id: 入群者 user_id

        Returns:
            text 消息段与入群者用户信息；处理失败返回 None。
        """
        if not group_id:
            logger.warning("群ID为空，无法处理入群通知")
            return None, None

        sub_type = raw.get("sub_type", "approve")
        operator_id = raw.get("operator_id") or user_id

        # 获取入群者信息
        user_nickname: str = "QQ用户"
        user_cardname: str = ""
        member_info: dict | None = await get_member_info(
            int(group_id) if group_id else 0, int(user_id) if user_id else 0
        )
        if member_info:
            user_nickname = member_info.get("nickname", "QQ用户")
            user_cardname = sanitize_text(member_info.get("card", "")) or ""
        else:
            logger.debug("无法获取入群者的群成员信息")

        # 获取操作者信息（含群角色，用于显示是谁批准/邀请的）
        operator_name: str = "QQ用户"
        operator_role: str = ""
        if operator_id and str(operator_id) != str(user_id):
            op_info: dict | None = await get_member_info(
                int(group_id) if group_id else 0, int(operator_id) if operator_id else 0
            )
            if op_info:
                operator_name = op_info.get("card") or op_info.get("nickname", "QQ用户")
                op_role_raw = op_info.get("role", "")
                if op_role_raw == "owner":
                    operator_role = "群主"
                elif op_role_raw == "admin":
                    operator_role = "管理员"
        else:
            operator_name = user_nickname

        user_info: UserInfoPayload = {
            "platform": "qq",
            "user_id": str(user_id),
            "user_nickname": user_nickname,
            "user_cardname": user_cardname,
            "role": "",  # type: ignore[typeddict-item]
        }

        # 拼接入群者显示名（昵称 + QQ号）
        user_display: str = f" {user_nickname}({user_id}) " if user_id else f" {user_nickname} "

        # 拼接操作者显示名（[角色] + 昵称 + QQ号）
        if operator_id and str(operator_id) != str(user_id):
            role_prefix = f"[{operator_role}]" if operator_role else ""
            operator_display = f" {role_prefix}{operator_name}({operator_id}) "
        else:
            operator_display = f" {operator_name} "

        action_text = "被邀请" if sub_type == "invite" else "通过审批"
        operator_label = "邀请人" if sub_type == "invite" else "审批人"
        seg_data: SegPayload = {
            "type": "text",
            "data": f"{user_display}加入了本群（{action_text}，{operator_label}：{operator_display}）",
        }
        return seg_data, user_info

    async def _handle_group_decrease_notify(
        self, raw: dict[str, Any], group_id: Any, user_id: Any
    ) -> tuple[SegPayload | None, UserInfoPayload | None]:
        """处理群成员退群通知。

        OneBot v11 ``group_decrease`` 事件字段：
        - ``sub_type``: ``leave``（主动退群）/ ``kick``（被踢）/ ``kick_me``（Bot被踢）
        - ``operator_id``: 操作者（踢人者）
        - ``user_id``: 退群者

        Args:
            raw: 原始通知数据
            group_id: 群 ID
            user_id: 退群者 user_id

        Returns:
            text 消息段与退群者用户信息；处理失败返回 None。
        """
        if not group_id:
            logger.warning("群ID为空，无法处理退群通知")
            return None, None

        sub_type = raw.get("sub_type", "leave")
        operator_id = raw.get("operator_id") or user_id

        # 获取退群者信息（退群后可能查不到群成员信息）
        user_nickname: str = "QQ用户"
        member_info: dict | None = await get_member_info(
            int(group_id) if group_id else 0, int(user_id) if user_id else 0
        )
        if member_info:
            user_nickname = member_info.get("card") or member_info.get("nickname", "") or "QQ用户"
        else:
            # 退群后成员已不在群中，改用陌生人信息接口获取昵称
            stranger_info: dict | None = await get_stranger_info(
                int(user_id) if user_id else 0
            )
            if stranger_info:
                user_nickname = stranger_info.get("nickname", "") or "QQ用户"
            logger.debug("退群者已退群，通过陌生人信息接口获取昵称")

        # 拼接退群者显示名（昵称 + QQ号）
        user_display: str = f" {user_nickname}({user_id}) " if user_id else f" {user_nickname} "

        # 获取操作者信息（含群角色）
        operator_name: str = "QQ用户"
        operator_role: str = ""
        if sub_type in ("kick", "kick_me") and operator_id:
            op_info: dict | None = await get_member_info(
                int(group_id) if group_id else 0, int(operator_id) if operator_id else 0
            )
            if op_info:
                operator_name = op_info.get("card") or op_info.get("nickname", "") or "QQ用户"
                op_role_raw = op_info.get("role", "")
                if op_role_raw == "owner":
                    operator_role = "群主"
                elif op_role_raw == "admin":
                    operator_role = "管理员"
        else:
            operator_name = user_nickname

        # 拼接操作者显示名（角色 + 昵称 + QQ号）
        if sub_type in ("kick", "kick_me") and operator_id:
            role_prefix = f"[{operator_role}]" if operator_role else ""
            operator_display = f" {role_prefix}{operator_name}({operator_id}) "
        else:
            operator_display = f" {operator_name} "

        user_info: UserInfoPayload = {
            "platform": "qq",
            "user_id": str(user_id),
            "user_nickname": user_nickname,
            "user_cardname": "",
            "role": "",  # type: ignore[typeddict-item]
        }

        if sub_type == "leave":
            action_text = f"{user_display}主动退出了本群"
        elif sub_type == "kick":
            action_text = f"{user_display}被{operator_display}踢出了本群"
        elif sub_type == "kick_me":
            action_text = f"Bot被{operator_display}踢出了群"
        else:
            action_text = f"{user_display}离开了本群"

        seg_data: SegPayload = {
            "type": "text",
            "data": action_text,
        }
        return seg_data, user_info

    async def _handle_group_admin_notify(
        self, raw: dict[str, Any], group_id: Any, user_id: Any
    ) -> tuple[SegPayload | None, UserInfoPayload | None]:
        """处理群管理员变动通知。

        OneBot v11 ``group_admin`` 事件字段：
        - ``sub_type``: ``set``（设置管理员）/ ``unset``（取消管理员）
        - ``user_id``: 被操作者

        Args:
            raw: 原始通知数据
            group_id: 群 ID
            user_id: 被操作者 user_id

        Returns:
            text 消息段与被操作者用户信息；处理失败返回 None。
        """
        if not group_id:
            logger.warning("群ID为空，无法处理管理员变动通知")
            return None, None

        sub_type = raw.get("sub_type", "set")

        # 获取被操作者信息
        user_nickname: str = "QQ用户"
        user_cardname: str = ""
        member_info: dict | None = await get_member_info(
            int(group_id) if group_id else 0, int(user_id) if user_id else 0
        )
        if member_info:
            user_nickname = member_info.get("nickname", "QQ用户")
            user_cardname = sanitize_text(member_info.get("card", "")) or ""
        else:
            logger.debug("无法获取被操作者的群成员信息")

        user_info: UserInfoPayload = {
            "platform": "qq",
            "user_id": str(user_id),
            "user_nickname": user_nickname,
            "user_cardname": user_cardname,
            "role": "",  # type: ignore[typeddict-item]
        }

        action_text = "被任命为管理员" if sub_type == "set" else "被取消了管理员"
        # 附带 QQ 号便于识别，格式与其他群通知一致：昵称(QQ号)动作
        user_display = f"{user_nickname}({user_id})" if user_id else user_nickname
        seg_data: SegPayload = {
            "type": "text",
            "data": f"{user_display}{action_text}",
        }
        return seg_data, user_info

    async def _handle_essence_notify(
        self, raw: dict[str, Any], group_id: Any, user_id: Any
    ) -> tuple[SegPayload | None, UserInfoPayload | None]:
        """处理精华消息变动通知。

        OneBot v11 ``essence`` 事件字段：
        - ``sub_type``: ``add``（设置精华）/ ``delete``（移除精华）
        - ``message_id``: 被操作的 message_id
        - ``operator_id``: 操作者
        - ``user_id``: 被操作消息的发送者

        Args:
            raw: 原始通知数据
            group_id: 群 ID
            user_id: 被操作消息的发送者 user_id

        Returns:
            text 消息段与操作者用户信息；处理失败返回 None。
        """
        if not group_id:
            logger.warning("群ID为空，无法处理精华消息通知")
            return None, None

        sub_type = raw.get("sub_type", "add")
        message_id = str(raw.get("message_id", ""))
        operator_id = raw.get("operator_id") or user_id

        # 获取操作者信息
        operator_nickname: str = "QQ用户"
        operator_cardname: str = ""
        op_info: dict | None = await get_member_info(
            int(group_id) if group_id else 0, int(operator_id) if operator_id else 0
        )
        if op_info:
            operator_nickname = op_info.get("nickname", "QQ用户")
            operator_cardname = sanitize_text(op_info.get("card", "")) or ""
        else:
            logger.debug("无法获取精华消息操作者的群成员信息")

        # 获取被操作消息发送者信息
        sender_nickname: str = "QQ用户"
        member_info: dict | None = await get_member_info(
            int(group_id) if group_id else 0, int(user_id) if user_id else 0
        )
        if member_info:
            sender_nickname = member_info.get("card") or member_info.get("nickname", "QQ用户")

        user_info: UserInfoPayload = {
            "platform": "qq",
            "user_id": str(operator_id),
            "user_nickname": operator_nickname,
            "user_cardname": operator_cardname,
            "role": "",  # type: ignore[typeddict-item]
        }

        # 尝试获取被操作消息的内容预览
        msg_preview = ""
        if message_id:
            try:
                preview = await self._get_message_preview(message_id)
                if preview:
                    msg_preview = preview
            except Exception as e:
                logger.debug(f"获取精华消息内容失败: {e!s}")

        action_text = "设置了精华消息" if sub_type == "add" else "移除了精华消息"
        if msg_preview:
            content = f"{operator_nickname}{action_text}（{sender_nickname}的消息：{msg_preview}）"
        else:
            content = f"{operator_nickname}{action_text}（消息发送者：{sender_nickname}）"
        seg_data: SegPayload = {
            "type": "text",
            "data": content,
        }
        return seg_data, user_info
