# Hyself V2.1 第一批 Issue / 任务清单

本清单对应 [v2_1_plan.md](v2_1_plan.md) 的首批落地项，优先覆盖 P0，兼顾少量 P1 预备工作。

## 批次目标

1. 完成 V2 文档与当前代码现状同步
2. 清理已无实际依赖的 chat 顶层兼容壳
3. 让资源中心读取链路继续从 `views.py` 下沉到 query/service
4. 为下一批 realtime、搜索、审核增强建立更清晰入口

## Issue 01: 同步 V2 核心文档现状

范围：

1. 更新 `chat_v2_refactor_plan.md` 的状态描述
2. 更新 `v2_architecture.md` 的产品名、落地状态与后续边界
3. 保证 V2、V2.1、发布说明之间术语一致

完成定义：

1. 文档不再把已完成事项写成“目标态”
2. 文档明确 V2 已完成、V2.1 正在推进的边界

状态：已完成

## Issue 02: 移除 chat 顶层兼容壳

范围：

1. 删除 `chat/views.py`
2. 删除 `chat/serializers.py`
3. 确认代码库内无顶层兼容壳引用

完成定义：

1. `chat/interfaces/api/` 成为唯一 REST 入口聚合层
2. 不再保留无人维护的兼容文件

状态：已完成

## Issue 03: 资源中心列表查询下沉

范围：

1. 抽离系统根目录 listing
2. 抽离系统目录 listing
3. 抽离用户目录 listing
4. 抽离虚拟视频目录 listing

完成定义：

1. `FileEntriesAPIView` 只保留权限、参数解析与响应协调
2. 列表响应结构保持兼容

状态：已完成第一轮

## Issue 04: 资源中心搜索查询下沉

范围：

1. 抽离用户资源搜索路径构建
2. 抽离系统资源搜索路径
3. 保持回收站树判断和 payload 输出兼容

完成定义：

1. `SearchFileEntriesAPIView` 不再承载目录路径拼装细节
2. 现有搜索相关回归继续通过

状态：已完成第一轮

## Issue 05: 资源中心剩余写接口继续收口

范围：

1. 评估 `SaveChatAttachmentToResourceAPIView`
2. 评估 `DeleteFileEntryAPIView`、`RenameFileEntryAPIView`
3. 评估回收站恢复与彻底删除链路是否继续下沉到 command/service

完成定义：

1. `hyself/views.py` 继续缩小到 API 协调层
2. 写接口边界与 query/payload/service 划分更清晰

当前进展：

1. `SaveChatAttachmentToResourceAPIView`
2. `DeleteFileEntryAPIView`
3. `RenameFileEntryAPIView`
4. `RestoreRecycleBinEntryAPIView`
5. `CreateFolderAPIView`
6. `UploadSmallFileAPIView`
7. `UploadPrecheckAPIView`
8. `UploadChunkAPIView`
9. `UploadMergeAPIView`

其中前四条写接口已在第一轮完成 command 下沉；第二轮已继续把建目录与上传链路写路径迁入 `application/commands/resource_uploads.py`，视图当前主要保留权限、参数校验、错误到 HTTP 状态码映射和响应组装。

状态：已完成第二轮

## Issue 06: 建立资源中心 query 模块边界

范围：

1. 评估是否从 `application/services/` 继续分出 `application/queries/`
2. 给列表、搜索、回收站读取建立统一命名规则
3. 明确 payload builder 和 query builder 的职责分界

完成定义：

1. 资源中心读取逻辑的命名与目录边界稳定
2. 后续写接口收口不会再次回流到视图层

当前进展：

1. 已新增 `hyself/application/queries/`
2. 列表、搜索、系统目录、虚拟目录相关读取逻辑已迁入 `queries/resource_center.py`
3. 旧 `services/resource_queries.py` 已移除
4. payload builder 已从 `application/services/resource_payloads.py` 收口到 `application/payloads/resource_center.py`
5. 读取与响应组装命名已统一为 `build_*_payload` 风格

状态：已完成第二轮

## Issue 07: 前端 realtime 统一消费层预备拆解

范围：

1. 梳理当前 envelope 解包路径
2. 列出仍在页面/组件内直接处理 WS 事件的入口
3. 输出下一批改造清单

完成定义：

1. 后续 P1 改造有明确入口文件和迁移顺序
2. 不直接在未知边界上推进大改

当前进展：

1. 已将 envelope 能力提升到 `src/realtime/envelope.ts`
2. 已新增 `src/realtime/dispatcher.ts`，提供按 `type`、`event_type`、`domain` 订阅的统一入口
3. chat 订阅已改走 domain dispatcher，auth 已改走 event dispatcher，upload 进度已改走 type dispatcher
4. 原 `src/stores/chat/realtimeEvents.ts` 当前仅保留兼容导出
5. `src/stores/chat/realtimeHandlers.ts` 已继续细分为 message / friendship / notice 子域 handler 文件，`src/stores/chat/realtime.ts` 保持聚合入口
6. `src/stores/chat/searchAuditRealtimeRuntime.ts` 已把 search / audit 条件刷新接入 dispatcher，并补上延迟合并策略
7. auth / upload 已进一步抽到 `src/stores/authRealtimeRuntime.ts` 与 `src/utils/uploadRealtimeRuntime.ts`
8. 已产出并同步拆解清单文档 [../../hyself/docs/v2_1-realtime-refactor-checklist.md](../../hyself/docs/v2_1-realtime-refactor-checklist.md)

状态：已完成下一步第二轮落地

## 建议执行顺序

1. Issue 07 后续：继续为更多非 chat 域补 dispatcher runtime
2. search / audit 条件刷新链路补充人工联调与防抖验证
3. 补充更完整的跨域 realtime 回归

## 验证基线

本批次完成后，至少应保持以下验证结果：

1. 后端 `manage.py test hyself.tests chat.tests user.tests game.tests` 通过
2. 资源中心列表、搜索、回收站主链路无回归
3. chat REST 路由正常加载，不依赖已删除的顶层兼容壳
