# SnowLuma API 参考手册

本文档列出了 SnowLuma 提供的所有 171 个 API 及其说明。这些 API 已被定义在 `src.api_constants.SnowLumaAction` 枚举中。

## 开发者调用方式

### 方式一：插件内直接调用 (通过 Adapter)
如果你可以获取到 `SnowLumaAdapter` 实例，可以直接调用 `send_snowluma_api` 方法：

```python
from plugins.snowluma_adapter.src.api_constants import SnowLumaAction

# 发送空间说说
await adapter.send_snowluma_api(
    SnowLumaAction.SEND_QZONE_MSG.value, 
    {"content": "今天天气真好！"}
)
```

### 方式二：通过 `adapter_command` 消息类型 (推荐，无需获取 Adapter 实例)
通过 MoFox 核心下发 `adapter_command` 类型的消息片段，适配器会自动拦截并执行。

```python
from mofox_wire import MessageEnvelope
from plugins.snowluma_adapter.src.api_constants import SnowLumaAction

envelope: MessageEnvelope = {
    "message_segment": {
        "type": "adapter_command",
        "data": {
            "action": SnowLumaAction.SET_GROUP_NAME.value,
            "params": {
                "group_id": 123456789,
                "group_name": "新群名"
            }
        }
    }
}
# 将 envelope 发送回核心 / sink
```

## API 列表

### 扩展

| API 动作 (Enum Name) | Action Name | 说明 |
|---|---|---|
| `SnowLumaAction._DEL_GROUP_NOTICE` | `_del_group_notice` | 删除群公告（fid 或 notice_id 二选一） |
| `SnowLumaAction._GET_GROUP_NOTICE` | `_get_group_notice` | 获取群公告 |
| `SnowLumaAction._GET_MODEL_SHOW` | `_get_model_show` | 获取机型展示（兼容 mock） |
| `SnowLumaAction._MARK_ALL_AS_READ` | `_mark_all_as_read` | 标记全部已读（no-op，待 RE 全读 cmd） |
| `SnowLumaAction._SEND_GROUP_NOTICE` | `_send_group_notice` | 发送群公告 |
| `SnowLumaAction._SET_MODEL_SHOW` | `_set_model_show` | 设置机型展示（占位） |
| `SnowLumaAction.GET_WORD_SLICES` | `.get_word_slices` | 分词（未实现） |
| `SnowLumaAction.ADD_CUSTOM_FACE` | `add_custom_face` | 添加收藏表情 |
| `SnowLumaAction.BOT_EXIT` | `bot_exit` | 退出机器人 |
| `SnowLumaAction.CANCEL_GROUP_TODO` | `cancel_group_todo` | 取消群待办 |
| `SnowLumaAction.CHECK_URL_SAFELY` | `check_url_safely` | 检查链接安全性 |
| `SnowLumaAction.CLEAN_CACHE` | `clean_cache` | 清理缓存 |
| `SnowLumaAction.CLICK_INLINE_KEYBOARD_BUTTON` | `click_inline_keyboard_button` | 点击内联键盘按钮 |
| `SnowLumaAction.COMPLETE_GROUP_TODO` | `complete_group_todo` | 完成群待办 |
| `SnowLumaAction.CREATE_COLLECTION` | `create_collection` | 创建收藏（未实现） |
| `SnowLumaAction.CREATE_FLASH_TASK` | `create_flash_task` | 创建闪传任务 |
| `SnowLumaAction.DELETE_CUSTOM_FACE` | `delete_custom_face` | 删除收藏表情 |
| `SnowLumaAction.DELETE_ESSENCE_MSG` | `delete_essence_msg` | 移除精华消息 |
| `SnowLumaAction.DELETE_FLASH_FILE` | `delete_flash_file` | 删除闪传文件 |
| `SnowLumaAction.DELETE_GROUP_FOLDER` | `delete_group_folder` | 删除群文件夹 |
| `SnowLumaAction.DOWNLOAD_FILE` | `download_file` | 下载文件（url 或 base64）到 data/downloads |
| `SnowLumaAction.DOWNLOAD_FILESET` | `download_fileset` | 解析闪传文件下载直链（不下载，由调用方实现下载） |
| `SnowLumaAction.FETCH_CUSTOM_FACE` | `fetch_custom_face` | 获取自定义表情 |
| `SnowLumaAction.FETCH_EMOJI_LIKE` | `fetch_emoji_like` | 获取表情回应用户（NapCat 分页） |
| `SnowLumaAction.FETCH_PTT_TEXT` | `fetch_ptt_text` | 获取语音转文字结果 |
| `SnowLumaAction.FORWARD_FRIEND_SINGLE_MSG` | `forward_friend_single_msg` | 转发单条消息给好友 |
| `SnowLumaAction.FORWARD_GROUP_SINGLE_MSG` | `forward_group_single_msg` | 转发单条消息到群 |
| `SnowLumaAction.FRIEND_POKE` | `friend_poke` | 好友拍一拍 |
| `SnowLumaAction.GET_AI_CHARACTERS` | `get_ai_characters` | 获取 AI 语音角色 |
| `SnowLumaAction.GET_AI_RECORD` | `get_ai_record` | 生成 AI 语音 |
| `SnowLumaAction.GET_CLIENTKEY` | `get_clientkey` | 获取 clientkey |
| `SnowLumaAction.GET_COLLECTION_LIST` | `get_collection_list` | 获取收藏列表（占位） |
| `SnowLumaAction.GET_COOKIES` | `get_cookies` | 获取 Cookies |
| `SnowLumaAction.GET_CREDENTIALS` | `get_credentials` | 获取凭证 |
| `SnowLumaAction.GET_CSRF_TOKEN` | `get_csrf_token` | 获取 CSRF 令牌 |
| `SnowLumaAction.GET_DOUBT_FRIENDS_ADD_REQUEST` | `get_doubt_friends_add_request` | 获取可疑好友申请 |
| `SnowLumaAction.GET_EMOJI_LIKES` | `get_emoji_likes` | 获取表情回应用户 |
| `SnowLumaAction.GET_ESSENCE_MSG_LIST` | `get_essence_msg_list` | 获取精华消息列表 |
| `SnowLumaAction.GET_FILE` | `get_file` | 获取文件信息（仅图片/语音缓存；群文件请用 get_group_file_url） |
| `SnowLumaAction.GET_FILESET_ID` | `get_fileset_id` | 从分享码/链接获取 fileset_id |
| `SnowLumaAction.GET_FILESET_INFO` | `get_fileset_info` | 获取文件集信息 |
| `SnowLumaAction.GET_FLASH_FILE_LIST` | `get_flash_file_list` | 获取闪传文件列表 |
| `SnowLumaAction.GET_FLASH_FILE_URL` | `get_flash_file_url` | 获取闪传文件链接 |
| `SnowLumaAction.GET_FORWARD_MSG` | `get_forward_msg` | 获取合并转发消息（id 或 message_id） |
| `SnowLumaAction.GET_FRIEND_MSG_HISTORY` | `get_friend_msg_history` | 获取好友消息历史 |
| `SnowLumaAction.GET_FRIENDS_WITH_CATEGORY` | `get_friends_with_category` | 获取分组好友列表 |
| `SnowLumaAction.GET_GROUP_AT_ALL_REMAIN` | `get_group_at_all_remain` | 获取群 @全体成员 剩余次数 |
| `SnowLumaAction.GET_GROUP_DETAIL_INFO` | `get_group_detail_info` | 获取群详细信息 |
| `SnowLumaAction.GET_GROUP_FILE_SYSTEM_INFO` | `get_group_file_system_info` | 获取群文件系统信息 |
| `SnowLumaAction.GET_GROUP_IGNORE_ADD_REQUEST` | `get_group_ignore_add_request` | 获取被忽略的入群请求（NapCat） |
| `SnowLumaAction.GET_GROUP_IGNORED_NOTIFIES` | `get_group_ignored_notifies` | 获取被过滤的入群请求 |
| `SnowLumaAction.GET_GROUP_INFO_EX` | `get_group_info_ex` | 获取群信息（扩展） |
| `SnowLumaAction.GET_GROUP_MSG_HISTORY` | `get_group_msg_history` | 获取群消息历史 |
| `SnowLumaAction.GET_GROUP_SHUT_LIST` | `get_group_shut_list` | 获取群禁言列表 |
| `SnowLumaAction.GET_GROUP_SIGNED_LIST` | `get_group_signed_list` | 获取群今日打卡列表 |
| `SnowLumaAction.GET_IMAGE` | `get_image` | 获取图片信息 |
| `SnowLumaAction.GET_MINI_APP_ARK` | `get_mini_app_ark` | 获取小程序卡片 ark |
| `SnowLumaAction.GET_ONLINE_CLIENTS` | `get_online_clients` | 获取在线客户端（占位，OneBot v11 形状） |
| `SnowLumaAction.GET_PROFILE_LIKE` | `get_profile_like` | 获取资料点赞 |
| `SnowLumaAction.GET_RECENT_CONTACT` | `get_recent_contact` | 获取最近会话（占位） |
| `SnowLumaAction.GET_RECORD` | `get_record` | 获取语音信息 |
| `SnowLumaAction.GET_RKEY` | `get_rkey` | 获取下载 rkey |
| `SnowLumaAction.GET_RKEY_SERVER` | `get_rkey_server` | 获取 rkey 服务器信息 |
| `SnowLumaAction.GET_SHARE_LINK` | `get_share_link` | 获取文件分享链接 |
| `SnowLumaAction.GET_UNIDIRECTIONAL_FRIEND_LIST` | `get_unidirectional_friend_list` | 获取单向好友列表 |
| `SnowLumaAction.GROUP_POKE` | `group_poke` | 群拍一拍 |
| `SnowLumaAction.LIST_FILESETS` | `list_filesets` | 列出当前账号的所有闪传文件集 |
| `SnowLumaAction.MARK_GROUP_MSG_AS_READ` | `mark_group_msg_as_read` | 标记群消息已读 |
| `SnowLumaAction.MARK_MSG_AS_READ` | `mark_msg_as_read` | 标记消息已读（群聊/私聊自动路由） |
| `SnowLumaAction.MARK_PRIVATE_MSG_AS_READ` | `mark_private_msg_as_read` | 标记私聊消息已读 |
| `SnowLumaAction.MODIFY_CUSTOM_FACE` | `modify_custom_face` | 修改收藏表情备注 |
| `SnowLumaAction.MOVE_CUSTOM_FACE_TO_FRONT` | `move_custom_face_to_front` | 收藏表情移到最前 |
| `SnowLumaAction.NC_GET_PACKET_STATUS` | `nc_get_packet_status` | 获取 packet 状态（占位） |
| `SnowLumaAction.NC_GET_USER_STATUS` | `nc_get_user_status` | 获取用户在线/扩展状态 |
| `SnowLumaAction.OCR_IMAGE` | `ocr_image` | OCR 图片（服务端，需图片 URL 或已缓存的图片 file_id） |
| `SnowLumaAction.RENAME_FLASH_FILE` | `rename_flash_file` | 重命名闪传文件 |
| `SnowLumaAction.REQUEST_DECRYPT_KEY` | `request_decrypt_key` | 请求数据库解密密钥 |
| `SnowLumaAction.SEND_ARK_SHARE` | `send_ark_share` | 分享用户/群 Ark 卡片（NapCat 标准名） |
| `SnowLumaAction.SEND_FLASH_MSG` | `send_flash_msg` | 发送闪传消息（私聊或群聊，引用 fileset_id 让对端下载） |
| `SnowLumaAction.SEND_FORWARD_MSG` | `send_forward_msg` | 发送合并转发（按 message_type/群号自动路由） |
| `SnowLumaAction.SEND_GROUP_AI_RECORD` | `send_group_ai_record` | 发送 AI 语音到群 |
| `SnowLumaAction.SEND_GROUP_ARK_SHARE` | `send_group_ark_share` | 分享群 Ark 卡片（NapCat 标准名） |
| `SnowLumaAction.SEND_GROUP_FORWARD_MSG` | `send_group_forward_msg` | 发送群合并转发 |
| `SnowLumaAction.SEND_LIKE` | `send_like` | 点赞 |
| `SnowLumaAction.SEND_PACKET` | `send_packet` | 发送原始 SSO 包（cmd + hex data） |
| `SnowLumaAction.SEND_POKE` | `send_poke` | 拍一拍（群聊/私聊自动路由） |
| `SnowLumaAction.SEND_PRIVATE_FORWARD_MSG` | `send_private_forward_msg` | 发送私聊合并转发 |
| `SnowLumaAction.SET_DIY_ONLINE_STATUS` | `set_diy_online_status` | 设置自定义在线状态 |
| `SnowLumaAction.SET_DOUBT_FRIENDS_ADD_REQUEST` | `set_doubt_friends_add_request` | 处理可疑好友申请 |
| `SnowLumaAction.SET_ESSENCE_MSG` | `set_essence_msg` | 设置精华消息 |
| `SnowLumaAction.SET_FRIEND_REMARK` | `set_friend_remark` | 设置好友备注 |
| `SnowLumaAction.SET_GROUP_REACTION` | `set_group_reaction` | 群聊表情回应 |
| `SnowLumaAction.SET_GROUP_REMARK` | `set_group_remark` | 设置群备注 |
| `SnowLumaAction.SET_GROUP_ROBOT_ADD_OPTION` | `set_group_robot_add_option` | 设置群机器人加群选项 |
| `SnowLumaAction.SET_GROUP_SIGN` | `set_group_sign` | 群签到 |
| `SnowLumaAction.SET_GROUP_TODO` | `set_group_todo` | 设置群待办 |
| `SnowLumaAction.SET_INPUT_STATUS` | `set_input_status` | 设置输入状态 |
| `SnowLumaAction.SET_MSG_EMOJI_LIKE` | `set_msg_emoji_like` | 设置消息表情回应 |
| `SnowLumaAction.SET_ONLINE_STATUS` | `set_online_status` | 设置在线状态 |
| `SnowLumaAction.SET_QQ_AVATAR` | `set_qq_avatar` | 设置 QQ 头像 |
| `SnowLumaAction.SET_QQ_PROFILE` | `set_qq_profile` | 设置 QQ 资料 |
| `SnowLumaAction.SET_RESTART` | `set_restart` | 重启（不支持） |
| `SnowLumaAction.SET_SELF_LONGNICK` | `set_self_longnick` | 设置个性签名（longNick/long_nick，严格 string） |
| `SnowLumaAction.SHARE_GROUP_EX` | `share_group_ex` | 分享群 Ark 卡片 |
| `SnowLumaAction.SHARE_PEER` | `share_peer` | 分享用户/群 Ark 卡片 |
| `SnowLumaAction.TRANS_GROUP_FILE` | `trans_group_file` | 转存群文件（未实现） |
| `SnowLumaAction.TRANSLATE_EN2ZH` | `translate_en2zh` | 英译中 |
| `SnowLumaAction.UPLOAD_FORWARD_MSG` | `upload_forward_msg` | 上传转发消息 |
| `SnowLumaAction.UPLOAD_FOWARD_MSG` | `upload_foward_msg` | 上传转发消息（别名拼写） |

### 信息

| API 动作 (Enum Name) | Action Name | 说明 |
|---|---|---|
| `SnowLumaAction.CAN_SEND_IMAGE` | `can_send_image` | 无详细说明 |
| `SnowLumaAction.CAN_SEND_RECORD` | `can_send_record` | 无详细说明 |
| `SnowLumaAction.GET_LOGIN_INFO` | `get_login_info` | 无详细说明 |
| `SnowLumaAction.GET_STATUS` | `get_status` | 无详细说明 |
| `SnowLumaAction.GET_VERSION_INFO` | `get_version_info` | 无详细说明 |

### 群相册

| API 动作 (Enum Name) | Action Name | 说明 |
|---|---|---|
| `SnowLumaAction.CANCEL_GROUP_ALBUM_MEDIA_LIKE` | `cancel_group_album_media_like` | 无详细说明 |
| `SnowLumaAction.DEL_GROUP_ALBUM_MEDIA` | `del_group_album_media` | 无详细说明 |
| `SnowLumaAction.DO_GROUP_ALBUM_COMMENT` | `do_group_album_comment` | 无详细说明 |
| `SnowLumaAction.GET_GROUP_ALBUM_LIST` | `get_group_album_list` | 无详细说明 |
| `SnowLumaAction.GET_GROUP_ALBUM_MEDIA_LIST` | `get_group_album_media_list` | 无详细说明 |
| `SnowLumaAction.GET_QUN_ALBUM_LIST` | `get_qun_album_list` | 无详细说明 |
| `SnowLumaAction.SET_GROUP_ALBUM_MEDIA_LIKE` | `set_group_album_media_like` | 无详细说明 |
| `SnowLumaAction.UPLOAD_IMAGE_TO_QUN_ALBUM` | `upload_image_to_qun_album` | 无详细说明 |

### 空间

| API 动作 (Enum Name) | Action Name | 说明 |
|---|---|---|
| `SnowLumaAction.COMMENT_QZONE` | `comment_qzone` | 评论一条说说（QQ 空间） |
| `SnowLumaAction.DELETE_QZONE_MSG` | `delete_qzone_msg` | 删除一条说说（QQ 空间，按 tid） |
| `SnowLumaAction.GET_QZONE_FEEDS` | `get_qzone_feeds` | 获取 QQ 空间好友动态（feed）；page_num 仅首页可靠，深翻页需时间游标（暂未实现） |
| `SnowLumaAction.GET_QZONE_MSG_LIST` | `get_qzone_msg_list` | 获取 QQ 空间说说列表（默认机器人自己的空间） |
| `SnowLumaAction.LIKE_QZONE` | `like_qzone` | 给一条说说点赞（QQ 空间） |
| `SnowLumaAction.SEND_QZONE_MSG` | `send_qzone_msg` | 发表一条纯文字说说（QQ 空间） |
| `SnowLumaAction.UNLIKE_QZONE` | `unlike_qzone` | 取消对一条说说的点赞（QQ 空间；取消赞端点待真机核实） |

### 群文件

| API 动作 (Enum Name) | Action Name | 说明 |
|---|---|---|
| `SnowLumaAction.CREATE_GROUP_FILE_FOLDER` | `create_group_file_folder` | 创建群文件夹 |
| `SnowLumaAction.DELETE_GROUP_FILE` | `delete_group_file` | 删除群文件 |
| `SnowLumaAction.DELETE_GROUP_FILE_FOLDER` | `delete_group_file_folder` | 删除群文件夹 |
| `SnowLumaAction.GET_GROUP_FILE_URL` | `get_group_file_url` | 获取群文件下载链接 |
| `SnowLumaAction.GET_GROUP_FILES_BY_FOLDER` | `get_group_files_by_folder` | 获取群子目录文件列表 |
| `SnowLumaAction.GET_GROUP_ROOT_FILES` | `get_group_root_files` | 获取群根目录文件列表 |
| `SnowLumaAction.GET_PRIVATE_FILE_URL` | `get_private_file_url` | 获取私聊文件下载链接 |
| `SnowLumaAction.MOVE_GROUP_FILE` | `move_group_file` | 移动群文件 |
| `SnowLumaAction.RENAME_GROUP_FILE` | `rename_group_file` | 重命名群文件 |
| `SnowLumaAction.RENAME_GROUP_FILE_FOLDER` | `rename_group_file_folder` | 重命名群文件夹 |
| `SnowLumaAction.UPLOAD_GROUP_FILE` | `upload_group_file` | 上传群文件 |
| `SnowLumaAction.UPLOAD_PRIVATE_FILE` | `upload_private_file` | 上传私聊文件 |

### 好友

| API 动作 (Enum Name) | Action Name | 说明 |
|---|---|---|
| `SnowLumaAction.DELETE_FRIEND` | `delete_friend` | 删除好友 |
| `SnowLumaAction.GET_FRIEND_LIST` | `get_friend_list` | 获取好友列表 |
| `SnowLumaAction.GET_STRANGER_INFO` | `get_stranger_info` | 获取陌生人信息 |

### 消息

| API 动作 (Enum Name) | Action Name | 说明 |
|---|---|---|
| `SnowLumaAction.DELETE_MSG` | `delete_msg` | 撤回消息 |
| `SnowLumaAction.GET_MSG` | `get_msg` | 获取消息 |
| `SnowLumaAction.SEND_GROUP_MSG` | `send_group_msg` | 发送群消息 |
| `SnowLumaAction.SEND_MSG` | `send_msg` | 发送消息（按 message_type/群号 自动路由群聊或私聊） |
| `SnowLumaAction.SEND_PRIVATE_MSG` | `send_private_msg` | 发送私聊消息 |

### 群信息

| API 动作 (Enum Name) | Action Name | 说明 |
|---|---|---|
| `SnowLumaAction.GET_GROUP_HONOR_INFO` | `get_group_honor_info` | 获取群荣誉信息 |
| `SnowLumaAction.GET_GROUP_INFO` | `get_group_info` | 获取群信息 |
| `SnowLumaAction.GET_GROUP_LIST` | `get_group_list` | 获取群列表 |
| `SnowLumaAction.GET_GROUP_MEMBER_INFO` | `get_group_member_info` | 获取群成员信息 |
| `SnowLumaAction.GET_GROUP_MEMBER_LIST` | `get_group_member_list` | 获取群成员列表 |
| `SnowLumaAction.GET_GROUP_SYSTEM_MSG` | `get_group_system_msg` | 获取群系统消息 |

### 请求

| API 动作 (Enum Name) | Action Name | 说明 |
|---|---|---|
| `SnowLumaAction.SET_FRIEND_ADD_REQUEST` | `set_friend_add_request` | 处理好友添加请求 |
| `SnowLumaAction.SET_GROUP_ADD_REQUEST` | `set_group_add_request` | 处理加群请求 |

### 群管理

| API 动作 (Enum Name) | Action Name | 说明 |
|---|---|---|
| `SnowLumaAction.SET_GROUP_ADD_OPTION` | `set_group_add_option` | 设置加群选项 |
| `SnowLumaAction.SET_GROUP_ADMIN` | `set_group_admin` | 设置/取消管理员 |
| `SnowLumaAction.SET_GROUP_ANONYMOUS` | `set_group_anonymous` | 匿名开关（未实现，返回 ok） |
| `SnowLumaAction.SET_GROUP_ANONYMOUS_BAN` | `set_group_anonymous_ban` | 匿名禁言（未实现，返回 ok） |
| `SnowLumaAction.SET_GROUP_BAN` | `set_group_ban` | 禁言群成员（duration=0 解除） |
| `SnowLumaAction.SET_GROUP_CARD` | `set_group_card` | 设置群名片（空字符串清除） |
| `SnowLumaAction.SET_GROUP_KICK` | `set_group_kick` | 踢出群成员 |
| `SnowLumaAction.SET_GROUP_KICK_MEMBERS` | `set_group_kick_members` | 批量踢出群成员 |
| `SnowLumaAction.SET_GROUP_LEAVE` | `set_group_leave` | 退群 |
| `SnowLumaAction.SET_GROUP_NAME` | `set_group_name` | 设置群名 |
| `SnowLumaAction.SET_GROUP_PORTRAIT` | `set_group_portrait` | 设置群头像 |
| `SnowLumaAction.SET_GROUP_SEARCH` | `set_group_search` | 允许群被搜索 |
| `SnowLumaAction.SET_GROUP_SPECIAL_TITLE` | `set_group_special_title` | 设置群头衔 |
| `SnowLumaAction.SET_GROUP_WHOLE_BAN` | `set_group_whole_ban` | 全员禁言开关 |

