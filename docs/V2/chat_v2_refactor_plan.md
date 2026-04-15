# Chat V2 重构实施计划

## 0.1 当前落地快照

截至当前代码，Chat V2 已完成第一轮边界收口，V2 主目标已经达成，当前进入 V2.1 的收口和增强阶段。

已完成：

1. 前端已抽出 `useChatShellScene`、转发流程 composable、聊天记录弹窗组件，`src/modules/chat-center/` 已开始承接 chat 页面场景逻辑
2. 后端 chat HTTP 接口已迁入 `chat/interfaces/api/`，并继续拆成 `endpoints/` 与场景化 serializer 模块
3. 后端应用命令已通过 `chat/infrastructure/event_bus.py` 发布核心聊天事件，底层广播统一落到 `ws/event_bus.py`
4. 聊天附件消息已接入资产域 service，不再在命令里散落创建 `AssetReference`
5. V2 发布所需的前端类型检查、单测、后端关键回归、浏览器回归和人工验收已完成

转入 V2.1 的收口项：

1. 前端 store 还没有按 conversation / message / friendship / group 等维度完成拆分
2. 后端 application / domain / infrastructure 虽已收口，但 repository、query、规则边界还有继续细化空间
3. 前端实时消费层还没有完全抽成独立 realtime store / scene
4. 搜索、审核、媒体增强仍处于“可继续扩展”而不是“完全收口”的状态

## 1. 文档目标

本文件基于 [v2_architecture.md](v2_architecture.md)，进一步记录 chat 模块在 V2 的实际落地过程，并为 V2.1 收口提供背景。

目标不是一次性推倒重写，而是在保证 V1 可用性的前提下，逐步把 chat 从“能用”升级到“可持续演进”。

## 2. 重构目标

Chat V2 需要解决四类问题：

1. 前端单一大 store 过重
2. 后端 chat 规则虽然完整，但应用层与领域层边界仍混杂
3. 实时事件协议不统一
4. 文件消息、图片消息和审核增强没有稳定扩展点

## 3. 重构范围

### 3.1 本次 V2 必做

1. 拆分前端 chat store
2. 拆分前端 chat 页面场景层
3. 后端 chat 按应用层 / 领域层 / 基础设施层重组
4. 标准化 WebSocket 事件 envelope
5. 统一消息类型扩展接口
6. 为图片消息、文件消息接入资产域预留接口

### 3.2 本次 V2 不立即做

1. 音视频通话
2. 真正的全文检索引擎接入
3. 单条消息级已读回执完整闭环
4. 多端同步冲突解决算法
5. 消息撤回的完整产品规则

## 4. 前端重构计划

### 4.1 现状问题

当前 useChatStore 同时承担：

1. 会话列表
2. 消息列表
3. 好友关系
4. 群成员与群审批
5. 搜索
6. 巡检
7. 失败消息重试
8. WebSocket 事件分发

这会带来以下问题：

1. 修改任一功能都容易影响其它状态
2. 单元测试难做
3. 页面重用困难
4. 后续接入文件消息时 store 会继续膨胀

### 4.2 目标拆分

建议拆为以下模块：

1. useConversationStore
2. useMessageStore
3. useFriendshipStore
4. useGroupStore
5. useChatModerationStore
6. useChatPreferenceStore
7. useChatSearchStore
8. useChatRealtimeStore

### 4.3 场景层拆分

页面层不要直接消费多个底层 store，而是通过场景层聚合：

1. useChatShellScene
2. useConversationListScene
3. useConversationWorkspaceScene
4. useContactScene
5. useAuditScene
6. useChatSettingsScene

目标：

1. 页面组件只处理展示与交互
2. 场景层处理跨 store 协调
3. store 只处理单一领域状态

当前进度补充：

1. `useChatShellScene` 已落地，并替代原先一部分页面层直接编排
2. 会话工作区里的转发选择、合并转发、聊天记录查看逻辑已拆到独立 composable / 组件
3. 其余 conversation list、contact、audit、settings 场景仍待继续收口

### 4.4 前端目录目标

```text
src/modules/chat-center/
  api/
  stores/
    conversation.ts
    message.ts
    friendship.ts
    group.ts
    moderation.ts
    preference.ts
    realtime.ts
    search.ts
  composables/
    useChatShellScene.ts
    useConversationListScene.ts
    useConversationWorkspaceScene.ts
    useContactScene.ts
    useAuditScene.ts
  components/
  views/
```

## 5. 后端重构计划

### 5.1 现状问题

当前后端 chat 已有 views、serializers、services、events、models，但仍存在这些问题：

1. APIView 中还残留一部分业务编排
2. services 里既有规则又有序列化与通知协作
3. 领域规则与持久化访问没有彻底解耦
4. 广播逻辑还是函数式散落，不利于事件标准化

### 5.2 目标分层

建议拆成：

1. interfaces
2. application
3. domain
4. infrastructure

#### interfaces

负责：

1. REST API
2. WebSocket 输入协议
3. serializer / DTO 转换
4. permission gateway

#### application

负责：

1. 用例编排
2. 事务边界
3. 调用 repository
4. 发布领域事件

#### domain

负责：

1. 好友申请规则
2. 陌生人私聊规则
3. 群邀请与审批规则
4. 成员角色与禁言规则
5. 消息类型可发送性规则

#### infrastructure

负责：

1. ORM repository
2. Channels 事件广播
3. Redis 缓存
4. 搜索适配器

当前进度补充：

1. `interfaces/api` 已物理落地，顶层 `chat/views.py`、`chat/serializers.py` 兼容壳已进入移除阶段
2. REST 接口已按 friends / conversations / groups / search / settings / admin 场景拆到独立 endpoint 文件
3. serializer 也已按 friends / conversations / groups / settings 场景拆分，后续不再建议依赖顶层聚合导出
4. 事件广播已收口到通用 event bus 与 chat 基础设施包装层，但 repository 与搜索适配器还未完全独立成基础设施目录

### 5.3 子域拆分

chat/domain 下拆五个子域：

1. conversation
2. messaging
3. social_graph
4. moderation
5. preference

## 6. 实时事件改造

### 6.1 当前问题

当前 ws.events 已经可用，但事件模型仍然偏扁平，问题如下：

1. 事件命名不统一
2. 事件上下文不足
3. 前端消费侧只能靠大量 if 分支判断

### 6.2 V2 目标

统一事件 envelope：

```json
{
  "event_id": "uuid",
  "event_type": "chat.message.created",
  "domain": "chat",
  "occurred_at": "2026-04-08T20:00:00+08:00",
  "payload": {}
}
```

当前实现补充：

1. 服务端广播给前端的聊天域事件已经统一输出为 `type: "event"`
2. 事件名当前落地值为：
   - `chat.message.created`
   - `chat.message.ack`
   - `chat.conversation.updated`
   - `chat.unread.updated`
3. `chat.message.acknowledged` 这一命名保留为概念目标，当前代码与测试已统一收口到 `chat.message.ack`
4. WebSocket 输入动作如 `chat_send_message`、`chat_send_asset_message` 的校验失败或权限失败，当前仍返回兼容结构：

```json
{
  "type": "error",
  "event": "chat_send_asset_message",
  "message": "你们还不是好友，当前私聊暂不支持发送附件"
}
```

这类 `error` 响应不属于领域广播事件，不进入标准 envelope，而是作为连接级命令回执保留。

当前落地边界补充：

1. 事件构造与发布已不再主要从 `ws.events` 直接散落调用，而是通过 `ws/event_bus.py` 和 `chat/infrastructure/event_bus.py` 收口
2. 这意味着 chat 域已经具备面向其它域复用的事件广播边界，但前端消费统一层仍有继续抽象空间

### 6.3 首批事件清单

1. chat.conversation.updated
2. chat.message.created
3. chat.message.ack
4. chat.unread.updated
5. chat.friend_request.updated
6. chat.friendship.updated
7. chat.group_join_request.updated
8. chat.moderation.notice

## 7. 消息模型升级

### 7.1 当前状态

当前 V1 主要使用：

1. text
2. system

V2 需要开始支持：

1. image
2. file

### 7.2 目标方案

ChatMessage 保留主表，但 payload 只保存轻量描述字段。

对于图片和文件消息：

1. 不直接把复杂文件信息堆到 payload
2. 使用 asset_id 或 asset_reference_id 关联资产域

推荐结构：

```json
{
  "message_type": "file",
  "content": "",
  "payload": {
    "asset_reference_id": 123,
    "display_name": "需求文档.pdf"
  }
}
```

## 8. 接口演进策略

### 8.1 保持兼容

V2 第一阶段不主动破坏现有 V1 REST 路径。

### 8.2 内部实现替换

优先做：

1. 原路径不变
2. 内部改调 application command/query
3. serializer 输出保持兼容

### 8.3 允许新增的接口

后续为图片/文件消息可新增：

1. chat asset picker 接口
2. 消息附件预签名 / 上传初始化接口
3. 消息媒体预览接口

## 9. 数据迁移建议

### 9.1 不做破坏式迁移

V2 第一阶段尽量不改动会引发全量迁移风险的核心表结构。

### 9.2 可接受的增量迁移

1. 新增资产引用表
2. 新增用户偏好扩展字段
3. 新增事件日志表
4. 新增消息附件映射表

## 10. 实施顺序

### Step 1

先拆前端 chat store 与 composable。

### Step 2

后端引入 application / domain 目录，并让现有 views 改调 command/query。

### Step 3

建立标准事件 envelope，并替换现有散落通知函数的输出结构。

### Step 4

接资产域，为图片/文件消息做第一批接入。

### Step 5

再做聊天搜索增强、审核增强、消息能力增强。

当前说明：

1. Step 1 到 Step 4 已在 V2 阶段完成主路径落地
2. Step 5 已成为 V2.1 的主要能力增强范围

## 11. 里程碑验收

### M1：结构拆分完成

验收标准：

1. 前端 chat store 已拆分
2. 后端 chat 具备 command/query 入口
3. 原有 V1 功能回归通过

当前状态：V2 主目标已完成，剩余项转入 V2.1。

1. 第 2、3 条已满足，且 chat 回归测试已持续通过
2. 第 1 条在 V2.1 当前边界下视为完成：前端保留 assembly store 作为聚合入口，但 scene/state/runtime/orchestration 已拆分稳定，不再把“彻底无 store 聚合文件”作为发布阻断

### M2：事件统一完成

验收标准：

1. 前端统一消费 event envelope
2. 后端广播统一输出 event_type
3. 输入命令失败场景继续返回显式 `error` 回执，前端可按 `event` 字段回滚发送态
4. 实时消息、好友申请、群通知链路无回归

当前状态：V2.1 已完成当前范围内的事件统一收口。

1. 前端 realtime 已统一到共享 `envelope + dispatcher + domain handler/runtime` 结构，chat/auth/upload/search-audit 都通过统一消费层接入
2. 后端广播骨架、错误回执和 chat 事件链路均已稳定，聊天相关自动化回归与浏览器回归通过
3. 更进一步的跨域 runtime 抽象与 CI 级实时工件留存属于 V2.2 工程化增强，而非当前阻断

### M3：文件消息接入完成

验收标准：

1. 文件消息可发送
2. 资源中心与聊天复用资产能力
3. 同一文件不重复造轮子

当前状态：V2.1 在消息/媒体增强上的当前边界已收口。

1. 聊天附件消息已可通过 asset reference 发送，图片/文件/聊天记录链路稳定可用
2. 资源中心、头像、聊天附件已共享同一批 asset reference application service，并补齐了资源中心 realtime 与保存附件链路
3. 统一上传入口、统一 asset picker、更多媒体编辑能力不再继续纳入当前 V2.1，统一延后到 V2.2

## 12. 风险与注意事项

1. 不要先做图片/文件消息，再回头补重构
2. 不要在现有大 store 上继续加功能
3. 不要让 application 层重新长成新的大 service
4. 不要把事件 envelope 设计成只服务 chat，应该兼容系统通知和后续模块

## 13. 当前文档边界

本文件用于保留 Chat V2 的实施背景。

如果要查看当前阶段的正式推进范围，请转到 [v2_1_plan.md](v2_1_plan.md)。
