# SnowLuma 适配器命令使用文档

本文档说明如何使用 SnowLuma 适配器封装的框架级命令。

## 命令概览

SnowLuma 适配器提供了 **27 个框架级封装命令**，这些命令可以通过 MoFox 的 `command` 消息段直接使用，并提供了参数验证和错误处理。

## 使用方式

### 方式一：通过 Command 消息段
```python
from mofox_wire import MessageEnvelope

envelope: MessageEnvelope = {
    "message_segment": {
        "type": "command",
        "data": {
            "name": "SET_GROUP_NAME",  # 命令名称（使用 CommandType 的枚举名）
            "args": {
                "group_name": "新群名"
            }
        }
    },
    "message_info": {
        "group_info": {
            "group_id": "123456789"
        }
    }
}
```

## 命令分类说明

### 1. 群管理核心命令（11个）

#### GROUP_BAN - 禁言用户
```python
args = {
    "user_id": 123456789,  # 必填：要禁言的用户QQ号
    "duration": 3600       # 必填：禁言时长（秒），0表示解除禁言
}
```

#### GROUP_WHOLE_BAN - 群全体禁言
```python
args = {
    "enable": True  # 必填：True开启全员禁言，False解除
}
```

#### GROUP_KICK - 踢出群聊
```python
args = {
    "user_id": 123456789,      # 必填：要踢出的用户QQ号
    "reject_add_request": False # 可选：是否拒绝再次加群请求
}
```

#### SET_GROUP_NAME - 设置群名
```python
args = {
    "group_name": "新群名"  # 必填：新的群名称
}
```

#### SET_GROUP_CARD - 设置群名片
```python
args = {
    "user_id": 123456789,  # 必填：目标用户QQ号
    "card": "新名片"       # 必填：新的群名片（空字符串清除）
}
```

#### SET_GROUP_ADMIN - 设置/取消管理员
```python
args = {
    "user_id": 123456789,  # 必填：目标用户QQ号
    "enable": True         # 必填：True设置管理员，False取消管理员
}
```

#### SET_GROUP_SPECIAL_TITLE - 设置群头衔
```python
args = {
    "user_id": 123456789,         # 必填：目标用户QQ号
    "special_title": "头衔文本",  # 必填：头衔内容（空字符串清除）
    "duration": -1                # 可选：头衔有效期（秒），-1为永久
}
```

#### SET_GROUP_LEAVE - 退群
```python
args = {}  # 无需参数，自动退出当前群
```

#### SET_GROUP_PORTRAIT - 设置群头像
```python
args = {
    "file": "图片文件路径或URL"  # 必填：头像图片
}
```

#### SET_GROUP_ADD_OPTION - 设置加群选项
```python
args = {
    "option": 1  # 必填：1=无需验证，2=需要验证，3=禁止加群
}
```

#### SET_GROUP_KICK_MEMBERS - 批量踢人
```python
args = {
    "user_ids": [123456, 789012],  # 必填：要踢出的用户QQ号列表
    "reject_add_request": False     # 可选：是否拒绝再次加群请求
}
```

### 2. 消息操作命令（6个）

#### DELETE_MSG - 撤回消息
```python
args = {
    "message_id": "消息ID"  # 必填：要撤回的消息ID
}
```

#### SEND_POKE - 戳一戳
```python
args = {
    "user_id": 123456789  # 必填：目标用户QQ号
}
```

#### SET_EMOJI_LIKE - 设置表情回应
```python
args = {
    "message_id": "消息ID",  # 必填：消息ID
    "emoji_id": "123",       # 必填：表情ID
    "set": True              # 可选：True添加，False取消（默认True）
}
```

#### SEND_AT_MESSAGE - 发送@消息
```python
args = {
    "user_id": 123456789,  # 必填：要@的用户QQ号
    "text": "消息内容"      # 必填：消息文本
}
```

#### SEND_GROUP_FORWARD_MSG - 发送群合并转发
```python
args = {
    "messages": [...]  # 必填：消息列表（具体格式见SnowLuma文档）
}
```

#### SEND_PRIVATE_FORWARD_MSG - 发送私聊合并转发
```python
args = {
    "user_id": 123456789,  # 必填：目标用户QQ号
    "messages": [...]       # 必填：消息列表
}
```

### 3. 好友管理命令（3个）

#### SEND_LIKE - 发送点赞
```python
args = {
    "user_id": 123456789,  # 必填：目标用户QQ号
    "times": 10            # 可选：点赞次数（默认1）
}
```

#### SET_FRIEND_REMARK - 设置好友备注
```python
args = {
    "user_id": 123456789,  # 必填：好友QQ号
    "remark": "新备注"      # 必填：新的备注名
}
```

#### DELETE_FRIEND - 删除好友
```python
args = {
    "user_id": 123456789  # 必填：要删除的好友QQ号
}
```

### 4. 群扩展功能（4个）

#### SET_ESSENCE_MSG - 设置精华消息
```python
args = {
    "message_id": "消息ID"  # 必填：要设为精华的消息ID
}
```

#### DELETE_ESSENCE_MSG - 移除精华消息
```python
args = {
    "message_id": "消息ID"  # 必填：要移除的精华消息ID
}
```

#### SET_GROUP_REMARK - 设置群备注
```python
args = {
    "remark": "群备注"  # 必填：群备注内容
}
```

#### SET_GROUP_SIGN - 群签到
```python
args = {}  # 无需参数，自动签到当前群
```

### 5. 媒体命令（1个）

#### AI_VOICE_SEND - AI语音发送
```python
args = {
    "character": "角色ID",  # 必填：AI语音角色ID
    "text": "要转换的文本"   # 必填：语音内容
}
```

### 6. QQ空间命令（5个）✨ 全部已实现

#### SEND_QZONE_MSG - 发布空间说说
```python
args = {
    "content": "说说内容"  # 必填：说说文本
}
```

#### DELETE_QZONE_MSG - 删除空间说说
```python
args = {
    "tid": "说说ID"  # 必填：要删除的说说ID（tid）
}
```

#### LIKE_QZONE - 点赞空间说说
```python
args = {
    "tid": "说说ID"  # 必填：要点赞的说说ID（tid）
}
```

#### UNLIKE_QZONE - 取消点赞空间说说
```python
args = {
    "tid": "说说ID"  # 必填：要取消点赞的说说ID（tid）
}
```

#### COMMENT_QZONE - 评论空间说说
```python
args = {
    "tid": "说说ID",      # 必填：要评论的说说ID（tid）
    "content": "评论内容" # 必填：评论文本
}
```

### 7. 请求处理（2个）

#### SET_FRIEND_ADD_REQUEST - 处理好友申请
```python
args = {
    "flag": "请求标识",  # 必填：好友申请的flag
    "approve": True,    # 必填：True同意，False拒绝
    "remark": "备注"    # 可选：好友备注
}
```

#### SET_GROUP_ADD_REQUEST - 处理加群申请
```python
args = {
    "flag": "请求标识",  # 必填：加群申请的flag
    "sub_type": "add",  # 必填："add"加群申请，"invite"邀请
    "approve": True,    # 必填：True同意，False拒绝
    "reason": "拒绝理由" # 可选：拒绝时的理由
}
```

## 错误处理

所有命令都包含参数验证，如果参数不完整或不正确，会抛出 `ValueError` 异常并在日志中记录错误信息。

## 完整示例

```python
from mofox_wire import MessageEnvelope
from src.app.plugin_system.api.send_api import send_message

# 示例1：设置群名
envelope: MessageEnvelope = {
    "direction": "outgoing",
    "message_segment": {
        "type": "command",
        "data": {
            "name": "SET_GROUP_NAME",
            "args": {"group_name": "MoFox 开发群"}
        }
    },
    "message_info": {
        "group_info": {"group_id": "123456789"}
    }
}
await send_message(envelope)

# 示例2：发布QQ空间说说
envelope: MessageEnvelope = {
    "direction": "outgoing",
    "message_segment": {
        "type": "command",
        "data": {
            "name": "SEND_QZONE_MSG",
            "args": {"content": "今天天气真好！"}
        }
    },
    "message_info": {}
}
await send_message(envelope)

# 示例3：点赞QQ空间说说
envelope: MessageEnvelope = {
    "direction": "outgoing",
    "message_segment": {
        "type": "command",
        "data": {
            "name": "LIKE_QZONE",
            "args": {"tid": "abc123xyz"}
        }
    },
    "message_info": {}
}
await send_message(envelope)
```

## 注意事项

1. 群管理相关命令需要机器人具有相应的权限（群主或管理员）
2. QQ空间命令需要目标说说的 `tid`（说说ID），可以通过 `get_qzone_msg_list` API 获取
3. 部分命令需要在群聊上下文中使用，需要提供 `group_info`
4. 所有命令都会返回执行结果，可以通过日志查看

## 更多API

除了这 27 个框架级命令，SnowLuma 还提供了 **171 个原生 API**，可以通过 `adapter_command` 消息类型直接调用。

详见：[`API_REFERENCE.md`](./API_REFERENCE.md)
