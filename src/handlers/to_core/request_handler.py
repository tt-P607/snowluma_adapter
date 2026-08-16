"""请求事件处理器。

处理来自 SnowLuma 的 request 事件（加群申请、群邀请、好友申请等），
将其转换为包含可读通知文本与元数据的 MessageEnvelope，交由核心分发与消费。
"""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING, Any

from mofox_wire import MessageBuilder, MessageEnvelope

from src.app.plugin_system.api.log_api import get_logger

from ...event_models import ACCEPT_FORMAT, RequestType
from ..utils import get_group_info, get_stranger_info, sanitize_text

if TYPE_CHECKING:
    from ....plugin import SnowLumaAdapter

logger = get_logger("snowluma_adapter")


class RequestHandler:
    """处理 SnowLuma 请求事件（加群申请、群邀请、好友申请等）。"""

    def __init__(self, adapter: "SnowLumaAdapter") -> None:
        """初始化请求事件处理器。

        Args:
            adapter: 所属 SnowLumaAdapter 实例
        """
        self.adapter = adapter

    async def handle_request(self, raw: dict[str, Any]) -> MessageEnvelope | None:
        """处理原始请求事件并转换为 MessageEnvelope。

        Args:
            raw: SnowLuma 原始请求事件数据

        Returns:
            MessageEnvelope | None: 转换后的消息信封；处理失败或无效时返回 None
        """
        request_type = raw.get("request_type")
        sub_type = raw.get("sub_type", "add")
        group_id = raw.get("group_id")
        user_id = raw.get("user_id")
        comment = raw.get("comment", "")
        flag = raw.get("flag", "")
        message_time = float(raw.get("time") or time.time())

        user_id_str = str(user_id) if user_id and str(user_id) != "0" else ""
        user_nickname = ""
        qq_level: int | None = None

        # 尝试通过 get_stranger_info 补齐申请人昵称与 QQ 等级
        if user_id_str:
            try:
                stranger_info = await get_stranger_info(int(user_id_str))
                if stranger_info:
                    user_nickname = sanitize_text(stranger_info.get("nickname", ""))
                    qq_level = stranger_info.get("qq_level") or stranger_info.get("level")
            except Exception as exc:
                logger.debug(f"获取申请人 {user_id_str} 资料失败: {exc}")

        # 针对群请求获取群名称
        group_name = ""
        if group_id:
            try:
                group_info = await get_group_info(group_id)
                if group_info:
                    group_name = sanitize_text(group_info.get("group_name", ""))
            except Exception as exc:
                logger.debug(f"获取群 {group_id} 信息失败: {exc}")

        # 构造可读展示文本
        user_display = (
            f"{user_nickname}({user_id_str})"
            if user_nickname and user_id_str
            else (f"QQ用户({user_id_str})" if user_id_str else (user_nickname or "未知用户"))
        )
        group_display = f"{group_name}({group_id})" if group_name and group_id else str(group_id or "")
        level_str = f"，QQ等级 {qq_level}" if qq_level is not None else ""
        comment_str = f"，验证留言：{comment}" if comment else "，验证留言：（无留言）"

        if request_type == RequestType.group:
            if sub_type == RequestType.Group.add:
                content = (
                    f"[notice] 加群申请 {user_display} 申请加入 {group_display}{level_str}{comment_str}。"
                    "请根据群规与意愿审核是否同意该用户入群，可使用相应工具进行审批处理。"
                )
            elif sub_type == RequestType.Group.invite:
                content = (
                    f"[notice] 邀请入群 用户 {user_display} 邀请加入 {group_display}{comment_str}。"
                )
            else:
                content = (
                    f"[notice] 群请求 {user_display} 针对 {group_display} 发起请求{comment_str}。"
                )
        elif request_type == RequestType.friend:
            content = f"[notice] 好友申请 用户 {user_display} 请求添加好友{comment_str}，可使用相应工具进行处理。"
        else:
            logger.warning(f"不支持的 request 类型: {request_type}, raw={raw}")
            content = f"[notice] 收到系统请求 ({request_type}) 来自 {user_display}{comment_str}。"

        # 生成唯一 message_id
        _req_id_raw = f"req_{request_type}_{sub_type}_{user_id}_{group_id}_{flag}_{message_time}"
        unique_msg_id = "req_" + hashlib.md5(_req_id_raw.encode()).hexdigest()[:16]

        msg_builder = MessageBuilder()
        (
            msg_builder.direction("incoming")
            .message_id(unique_msg_id)
            .timestamp_ms(int(message_time * 1000))
            .from_user(
                user_id=user_id_str or "0",
                platform="qq",
                nickname=user_nickname or "QQ用户",
            )
        )

        if group_id:
            msg_builder.from_group(
                group_id=str(group_id),
                platform="qq",
                name=group_name or "",
            )

        msg_builder.format_info(
            content_format=["text"],
            accept_format=ACCEPT_FORMAT,
        )
        msg_builder.seg_list([{"type": "text", "data": content}])

        extra_meta: dict[str, Any] = {
            "is_notice": True,
            "is_request": True,
            "request_type": str(request_type),
            "sub_type": str(sub_type),
            "group_id": str(group_id) if group_id else "",
            "group_name": group_name,
            "user_id": user_id_str,
            "user_nickname": user_nickname,
            "qq_level": qq_level,
            "comment": comment,
            "flag": flag,
            "raw": raw,
        }
        msg_builder.metadata(extra_meta)

        envelope = msg_builder.build()
        logger.info(f"已构建 request 消息信封: [#FAB387]{content}[/#FAB387]")
        return envelope


__all__ = ["RequestHandler"]
