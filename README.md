# SnowLuma Adapter

基于 mofox-wire 架构的 SnowLuma 适配器，为 Neo-MoFox 提供 QQ 平台的消息收发能力。

## 功能特性

- **消息收发**：支持文本、图片、表情、@、回复、语音、视频、合并转发等消息类型
- **通知处理**：戳一戳、表情回应、撤回、禁言、文件上传等通知事件，静默注入到聊天上下文
- **语音转文字**：支持通过 SnowLuma 原生 `fetch_ptt_text` 进行语音识别（可选）
- **黑白名单**：群聊/私聊级别的黑白名单过滤
- **视频处理**：可配置的视频消息下载和解析
- **回复@**：可配置概率的回复自动@发送者

## 项目结构

```
snowluma_adapter/
├── plugin.py                          # 主插件入口（BaseAdapter 实现）
├── config.py                          # 配置定义
├── manifest.json                      # 插件清单
├── src/
│   ├── api_constants.py               # SnowLuma API 枚举
│   ├── event_models.py                # 事件类型常量、QQ 表情映射表
│   ├── event_types.py                 # 事件类型定义
│   └── handlers/
│       ├── utils.py                   # API 调用、缓存、信息查询等工具函数
│       ├── video_handler.py           # 视频下载处理
│       ├── to_core/                   # SnowLuma → 核心方向
│       │   ├── message_handler.py     # 消息处理
│       │   ├── notice_handler.py      # 通知处理（注入到 unread_messages）
│       │   ├── meta_event_handler.py  # 元事件（心跳等）
│       │   └── request_handler.py     # 请求事件（加群/加好友）
│       └── to_snowluma/               # 核心 → SnowLuma 方向
│           └── send_handler.py        # 消息发送、命令处理
```

## 配置说明

配置文件位于 `config/plugins/snowluma_adapter/config.toml`。

### 核心配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `plugin.enabled` | `true` | 插件开关 |
| `bot.qq_id` | - | Bot 的 QQ 号 |
| `bot.qq_nickname` | - | Bot 昵称 |
| `snowluma_server.mode` | `"reverse"` | 连接模式（reverse/direct） |
| `snowluma_server.host` | `"localhost"` | SnowLuma 服务地址 |
| `snowluma_server.port` | `8095` | SnowLuma 服务端口 |
| `snowluma_server.access_token` | `""` | 访问令牌（可选） |

### 功能配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `features.group_list_type` | `"blacklist"` | 群聊名单模式 |
| `features.enable_poke` | `true` | 戳一戳通知 |
| `features.enable_emoji_like` | `true` | 表情回应通知 |
| `features.enable_recall` | `true` | 撤回通知 |
| `features.enable_sl_voice_to_text` | `false` | SnowLuma 原生语音转文字 |
| `features.enable_video_processing` | `true` | 视频消息处理 |
| `features.enable_reply_at` | `true` | 回复时@用户 |

## 快速开始

1. 在 `config/plugins/snowluma_adapter/config.toml` 中配置 SnowLuma 服务地址和 Bot 信息
2. 启动 Neo-MoFox，插件自动加载并连接 SnowLuma
3. 配置黑白名单以控制消息处理范围

## 依赖

- Neo-MoFox >= 1.0.0
- pillow >= 12.1.0
