# Assets 域目录与命名约定

## 1. 文档目标

本文件定义当前阶段 assets 域在后端代码中的落点和命名约定。

它解决两个现实问题：

1. 资源中心、聊天附件、头像引用已经共享 Asset / AssetReference，但物理目录还没有完全拆成独立 `assets/` app
2. 新代码如果继续随手堆进 `views.py`、`utils/` 或宽泛的 `services.py`，后续再拆域会再次返工

因此，这份文档不是未来理想图，而是约束“现在继续写代码时应该怎么落”。

## 2. 当前边界

现阶段 assets 域仍主要挂在 `hyself` 应用下。

当前已经确认的主落点如下：

1. `hyself/application/queries/resource_center.py` 负责资源中心读侧编排
2. `hyself/application/commands/resource_center.py` 负责资源中心写侧动作
3. `hyself/application/commands/resource_uploads.py` 负责上传、合并、头像上传、目录创建等写侧动作
4. `hyself/application/payloads/resource_center.py` 负责资源中心响应 payload 组装
5. `hyself/application/services/asset_references.py` 负责跨入口复用的 asset reference 生命周期逻辑
6. `hyself/application/services/resource_center.py` 负责资源中心共享业务辅助逻辑

在真正拆成独立 `assets/` app 之前，新增资产域代码优先继续收敛到这组目录，不再先落进散点工具模块。

## 3. 名词约定

### 3.1 Asset

`Asset` 表示物理文件事实。

涉及内容包括：

1. 存储键
2. 文件哈希
3. MIME 类型
4. 媒体类型
5. 文件尺寸、时长等元信息

命名里凡是明确指向物理文件层的概念，统一使用 `asset`。

### 3.2 AssetReference

`AssetReference` 表示业务对象对 Asset 的引用。

命名里凡是明确指向“谁在引用该文件”，统一使用 `asset_reference` 或 `reference`，不要再混写成泛化的 `file_record`、`file_link`、`asset_item`。

### 3.3 Resource Entry

资源中心目录视图中的一项，当前兼容层仍然主要由 `UploadedFile` 承担。

命名里遇到资源中心目录树、父子目录、回收站目录等语义时，使用 `resource entry`、`uploaded entry` 或 `resource_center`，不要误叫成 `asset`。

原因很简单：目录不是 Asset，目录视图项也不等于 AssetReference 本体。

### 3.4 Compat

凡是仍然服务于 `UploadedFile -> Asset / AssetReference` 兼容桥接的代码，命名里必须出现 `compat`。

例如：

1. `asset_compat.py`
2. `ensure_asset_compat_for_uploaded_file()`

这样可以避免兼容层和目标域模型继续混在一起。

## 4. 目录约定

### 4.1 queries

`hyself/application/queries/` 只放读侧编排。

适合放这里的逻辑：

1. 目录列表
2. 搜索结果组装
3. breadcrumb 生成
4. virtual path 解析
5. owner scope / system scope 下的读侧分支

不应该放这里的逻辑：

1. 创建目录
2. 删除、恢复、重命名
3. 上传写入
4. 发消息时创建聊天附件引用

当前主文件是 `hyself/application/queries/resource_center.py`。

新增 query 文件命名优先按业务面命名，例如：

1. `resource_center.py`
2. `asset_access.py`
3. `asset_search.py`

不要使用含糊名字，例如：

1. `common.py`
2. `helpers.py`
3. `asset_misc.py`

### 4.2 commands

`hyself/application/commands/` 只放写侧用例入口。

适合放这里的逻辑：

1. 创建目录
2. 上传小文件
3. 分片上传合并
4. 保存聊天附件到资源中心
5. 删除、恢复、重命名资源条目

当前已落地的文件命名已经是后续标准：

1. `resource_center.py` 表示资源中心条目写侧操作
2. `resource_uploads.py` 表示上传链路相关写侧操作

新的 command 函数命名统一用动作动词起头，例如：

1. `create_folder_entry`
2. `save_chat_attachment_to_resource`
3. `delete_resource_entry`
4. `submit_large_file_merge`

避免在 command 模块里直接拼 REST response payload。command 返回领域对象或最小结果，再交给 payload 层处理。

### 4.3 payloads

`hyself/application/payloads/` 只负责响应结构组装。

允许的命名模式：

1. `build_*_payload`
2. `build_*_result_payload`
3. `build_*_response_payload`

不应该放这里的逻辑：

1. ORM 查询
2. 权限判断
3. 状态迁移
4. 上传路径处理

当前主文件是 `hyself/application/payloads/resource_center.py`，后续如新增 assets 专属 payload 文件，也应继续按业务面命名，而不是叫 `serializers.py` 或 `utils.py`。

### 4.4 services

`hyself/application/services/` 放跨多个 command / query 复用的共享业务逻辑，但它不是兜底杂物箱。

当前建议分两类：

1. `asset_references.py` 这类明确围绕 AssetReference 生命周期的共享服务
2. `resource_center.py` 这类资源中心共享业务辅助逻辑

适合放这里的函数前缀：

1. `ensure_`
2. `resolve_`
3. `upsert_`
4. `create_*_reference`

不建议新增泛化文件名，例如：

1. `file_service.py`
2. `asset_utils.py`
3. `resource_helpers.py`

如果一个函数已经只服务单个写操作或单个查询，不要为了“抽一层”硬塞到 services，直接留在 command / query 文件里更清楚。

## 5. interface 与基础设施边界

### 5.1 views.py

`hyself/views.py` 只保留：

1. 请求参数解析
2. 权限入口校验
3. command / query 调用
4. HTTP Response 返回

以下逻辑不应继续新增到 `views.py`：

1. 目录树遍历
2. 资源列表 payload 循环拼装
3. AssetReference upsert 规则
4. 上传目标路径决策

### 5.2 asset_compat.py

`asset_compat.py` 只保留兼容桥语义。

它的职责是把旧 `UploadedFile` 记录接到 Asset / AssetReference 上，而不是承担新的产品规则。

如果新增逻辑的主语已经是 `AssetReference` 本身，就不应再放进 compat 模块。

### 5.3 utils/upload.py

`hyself/utils/upload.py` 只放存储、路径、MD5、文件系统层面的基础能力。

例如：

1. 文件名归一化
2. 上传根目录解析
3. chunk MD5 校验
4. 相对路径处理

不要把 `AssetReference` 可见性、聊天附件复用、资源中心回收站规则放进这里。

## 6. 命名规则

### 6.1 模块名

模块名优先体现业务面，而不是技术动作堆砌。

推荐：

1. `resource_center.py`
2. `resource_uploads.py`
3. `asset_references.py`

不推荐：

1. `file_ops.py`
2. `asset_helpers.py`
3. `common_service.py`

### 6.2 函数名前缀

建议统一如下：

1. query 读侧：`build_`、`get_`、`list_`、`search_`、`resolve_`
2. command 写侧：`create_`、`process_`、`submit_`、`save_`、`delete_`、`restore_`、`rename_`
3. shared service：`ensure_`、`resolve_`、`upsert_`
4. compat bridge：名称里显式带 `compat`

### 6.3 结果对象命名

1. 面向 API 输出的字典统一叫 `payload`
2. 面向查询结果的聚合字典可叫 `listing_payload`、`search_payload`、`result_payload`
3. 不要把返回给前端的 dict 再叫成 `dto` 和 `serializer_data` 混用

## 7. 新增代码落点决策

写新逻辑前先问四个问题：

1. 这是读侧还是写侧
2. 主语是 Asset、AssetReference，还是资源中心目录视图项
3. 这是复用规则，还是单个用例内部细节
4. 这是业务语义，还是文件系统 / 存储基础能力

按答案落点：

1. 读侧编排 -> `queries/`
2. 写侧动作 -> `commands/`
3. 跨入口共享的引用规则 -> `services/asset_references.py`
4. API 输出结构 -> `payloads/`
5. 旧模型桥接 -> `asset_compat.py`
6. 路径/文件系统细节 -> `utils/upload.py`

如果上述四个问题回答不清，优先不要新增文件，先把函数留在最接近的 command / query 模块中，等出现第二个调用方再抽共享层。

## 8. 后续拆成独立 assets app 时保持不变的规则

未来即使物理目录迁到独立 `assets/` app，这份文档里的命名和边界也不变：

1. query 仍然是读侧编排
2. command 仍然是写侧动作
3. payload 仍然只管输出组装
4. service 仍然只承载明确的共享业务规则
5. compat 仍然必须显式标出过渡属性

也就是说，当前这份约定不是临时命名习惯，而是未来物理拆域前的先行约束。
