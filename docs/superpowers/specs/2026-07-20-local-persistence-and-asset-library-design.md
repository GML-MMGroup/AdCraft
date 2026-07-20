# AdCraft 本地持久化与资产库设计

日期：2026-07-20

## 1. 决策摘要

AdCraft 第一版采用单用户、本地部署架构：

- 后端 SQLite 是项目、工作流、执行记录、资产元数据和模型配置的事实来源。
- 图片、视频、音频等大文件保存在后端管理的本地文件系统中。
- 前端只通过后端 API 读写业务数据，不直接访问 SQLite 或拼接磁盘路径。
- 前端 IndexedDB 仅保留未提交草稿、界面缓存和迁移期间的兼容数据。
- 一个项目对应一个工作流，工作流可以有多个不可变修订版本。
- 所有媒体统一登记为资产，但模型生成结果和画布上传内容默认不进入资产库。
- 资产库由用户主动整理；从资产库专用入口上传的内容直接入库。
- 本地文件访问通过 `StorageAdapter` 隔离，为后续 MinIO、S3 等对象存储预留迁移能力。
- 第一版不引入用户、组织、角色和权限表。

## 2. 目标与非目标

### 2.1 目标

1. 将当前浏览器 IndexedDB、后端 JSON/NDJSON 与媒体目录中的业务关系收敛到统一数据模型。
2. 保持本地部署简单，默认不要求用户安装 PostgreSQL、Redis 或对象存储。
3. 让项目、工作流、执行记录、生成资产和资产库之间的关系可以查询、恢复和校验。
4. 消除在工作流 JSON、执行状态或 provider payload 中持久化 Base64 媒体内容的情况。
5. 支持可靠备份、恢复、软删除和孤儿文件回收。
6. 保留未来迁移 PostgreSQL 与 S3/MinIO 的路径。

### 2.2 非目标

- 第一版不实现多用户协作、租户隔离、复杂权限或云端同步。
- 第一版不把媒体二进制写入 SQLite BLOB。
- 第一版不将工作流节点的每一个嵌套字段拆成独立关系表。
- 第一版不引入 Redis、Celery 或分布式 worker。
- 第一版不自动将所有上传内容和生成结果收入资产库。

## 3. 总体架构

```text
Web frontend
    |
    | REST + SSE
    v
FastAPI backend
    |-- Project / Workflow services
    |-- Execution services
    |-- Asset library services
    |-- Model configuration services
    |
    |-- SQLAlchemy repositories --> SQLite: data/adcraft.sqlite3
    |
    `-- StorageAdapter
          |-- LocalFileStorage: data/storage/objects/...
          `-- Future: S3Storage / MinIOStorage
```

数据库属于后端持久化层。前后端通过 OpenAPI 契约协作，但数据库表、迁移脚本、事务和文件一致性由后端负责。前端负责界面状态、请求状态和可丢弃缓存。

## 4. 数据模型

### 4.1 项目与工作流

#### `projects`

保存用户看到的项目。

关键字段：

- `id`: UUID 字符串主键。
- `name`, `description`。
- `cover_asset_id`: 可空，关联项目封面资产。
- `is_favorite`。
- `status`: `active | trashed | archived`。
- `created_at`, `updated_at`, `deleted_at`。

#### `workflows`

一个项目唯一对应一个工作流。

关键字段：

- `id`。
- `project_id`: 唯一外键。
- `current_revision_no`: 当前修订号。
- `created_at`, `updated_at`。

#### `workflow_revisions`

工作流修订不可变，保存一次完整画布快照。

关键字段：

- `id`。
- `workflow_id`。
- `revision_no`: 在工作流内递增。
- `schema_version`: 工作流文档版本。
- `document_json`: 完整 WorkflowV2 JSON。
- `change_source`: `create | autosave | manual | execution | migration`。
- `created_at`。

唯一约束为 `(workflow_id, revision_no)`。前端保存时携带已知修订号，后端使用乐观并发控制，避免旧页面覆盖新内容。

`document_json` 可以保留节点和边的嵌套结构，但只能引用 `asset_id`、`entity_id` 等稳定标识，不允许包含 Data URL、Base64 文件内容或服务器绝对路径。

### 4.2 执行记录

#### `workflow_executions`

关键字段：

- `id`, `workflow_id`, `workflow_revision_id`。
- `status`: `queued | running | succeeded | failed | cancelled | interrupted`。
- `started_at`, `finished_at`。
- `error_code`, `error_message`。
- `created_at`, `updated_at`。

每次执行绑定一个不可变工作流修订，保证后续可以知道当时实际执行的图结构。

#### `node_runs`

保存每个节点、每次尝试的状态。

关键字段：

- `id`, `execution_id`, `node_id`, `node_type`。
- `attempt_no`。
- `status`。
- `provider_job_id`: 可空。
- `input_summary_json`, `output_summary_json`: 只保存文本摘要和资产 ID。
- `error_code`, `error_message`。
- `started_at`, `finished_at`。

唯一约束为 `(execution_id, node_id, attempt_no)`。

#### `execution_events`

保存用于 SSE 恢复和审计的轻量事件。

关键字段：

- `id`: 递增整数主键。
- `execution_id`, `node_run_id`。
- `sequence_no`, `event_type`, `payload_json`, `created_at`。

`payload_json` 不保存模型原始二进制响应。大型 provider 原始响应、调试包或渲染清单作为文件型执行产物保存，并由资产或专用 artifact 记录引用。

#### `provider_jobs`

保存外部模型任务的可恢复状态。

关键字段：

- `id`, `node_run_id`。
- `provider`, `model_id`, `external_job_id`。
- `status`, `submitted_at`, `last_polled_at`, `finished_at`。
- `request_summary_json`, `response_summary_json`。

请求摘要只保留 prompt、参数和资产 ID。真正发给 provider 的临时 Base64 或签名 URL 不落库。

### 4.3 统一资产

#### `assets`

所有上传、生成、导入和渲染得到的媒体都登记为资产。资产记录与“是否进入资产库”是两个概念。`assets` 表示一次可追溯的逻辑媒体记录；内容完全相同的多条资产记录可以共享同一个不可变 `storage_key`，从而在保留各自文件名和来源信息的同时避免重复存储。

关键字段：

- `id`。
- `media_type`: `image | video | audio | document | other`。
- `filename`, `mime_type`, `size_bytes`。
- `width`, `height`, `duration_seconds`。
- `sha256`。
- `storage_driver`: 第一版为 `local`。
- `storage_key`: 存储适配器内部键，不是绝对路径。
- `status`: `pending | ready | failed | pending_delete | deleted`。
- `source_type`: `upload | generated | imported | rendered | derivative`。
- `source_project_id`, `source_workflow_id`, `source_execution_id`, `source_node_id`。
- `parent_asset_id`, `derivative_type`: 用于缩略图、代理视频和转码版本。
- `metadata_json`, `created_at`, `updated_at`, `deleted_at`。

资产文件不可原地修改。替换、裁剪、转码或重新生成均创建新资产，并通过 `parent_asset_id` 保留来源关系。

当多个资产记录共享 `storage_key` 时，物理文件只有在没有任何 `ready` 资产记录引用该键后才允许删除。第一版不额外增加 `storage_objects` 表，引用计数通过 `assets.storage_key` 查询得到；如果未来需要跨实例对象级去重，再独立拆分物理对象表。

#### `project_assets`

项目与资产的多对多关系。

关键字段：

- `project_id`, `asset_id`。
- `origin`: `upload | generated | library | render`。
- `created_at`。

同一个资产可被多个项目引用，不复制物理文件。

### 4.4 资产库

#### `asset_entities`

表示用户认知中的可复用对象，而不是某一个文件。

类型沿用当前后端概念：

- `character`
- `scene`
- `storyboard_shot`
- `video_clip`
- `bgm`
- `product`
- `style_reference`
- `uploaded_reference`

关键字段：

- `id`, `entity_type`, `display_name`, `description`。
- `tags_json`, `reuse_policy_json`, `metadata_json`。
- `is_archived`, `created_at`, `updated_at`。

#### `asset_entity_members`

关联资产库实体与媒体文件。

关键字段：

- `entity_id`, `asset_id`。
- `semantic_type`: 例如 `character_face_id`、`product_reference`、`storyboard_video`。
- `is_primary`, `sort_order`, `created_at`。

唯一约束为 `(entity_id, asset_id, semantic_type)`。

#### `asset_bindings`

表示资产或资产库实体如何参与当前工作流。

关键字段：

- `id`, `project_id`, `workflow_id`。
- `entity_id` 或 `asset_id`: 至少一个存在。
- `scope_type`: `global | node | item | shot | final_composition`。
- `scope_id`。
- `role`: 例如 `character_reference`、`product_reference`、`style_reference`。
- `use_as_prompt`, `reference_mode`, `lock_identity`, `priority`。
- `metadata_json`, `created_at`, `updated_at`。

该结构直接承接后端现有 `AssetBinding` 行为，不需要在工作流 JSON 内复制完整资产元数据。

### 4.5 对话与模型配置

#### `conversations` 和 `conversation_messages`

对话归属项目和工作流，可以可选聚焦某个节点。消息正文以 JSON 保存，附件只保存资产 ID。

#### `model_configs`

保存 API Space 中用户配置的可用模型：

- `id`, `media_type`, `provider`, `model_id`, `display_name`。
- `is_enabled`, `is_default`, `settings_json`。
- `created_at`, `updated_at`。

同一媒体类型允许配置多个模型，但最多一个默认模型。

#### `provider_credentials`

保存 provider 凭据引用：

- `id`, `provider`, `label`。
- `encrypted_payload`, `key_hint`。
- `created_at`, `updated_at`。

API Key 不写入工作流、日志或前端持久缓存，也不建议由运行中的 API 修改 `.env`。本地部署可使用独立 master key 文件加密数据库中的凭据；master key 文件使用仅当前用户可读的文件权限，并且不进入 Git。

## 5. 资产进入资产库的规则

| 来源 | 是否创建资产 | 是否自动进入资产库 |
|---|---:|---:|
| 资产库页面上传 | 是 | 是 |
| 工作流画布上传 | 是 | 否 |
| 对话附件上传 | 是 | 否 |
| 模型中间生成结果 | 是 | 否 |
| 最终成片 | 是 | 否 |
| 用户点击“保存到资产库” | 已存在 | 是 |
| 从资产库选择到项目 | 复用现有资产 | 已在资产库 |

“保存到资产库”支持两种操作：

1. 创建新实体，并将一个或多个已有资产加入实体。
2. 将已有资产追加到一个已有实体。

保存过程只新增数据库关联，不复制文件。

## 6. 本地文件存储

建议目录结构：

```text
data/
|-- adcraft.sqlite3
|-- storage/
|   `-- objects/
|       `-- sha256/
|           `-- ab/
|               `-- cd/
|                   `-- <hash>.<ext>
|-- tmp/
|-- backups/
`-- legacy/                 # 迁移后保留的旧 JSON，可选
```

文件名使用内容哈希或随机不可变标识，用户上传的原始文件名只保存在数据库中。HTTP 下载名称通过响应头设置。

`StorageAdapter` 最小接口：

```text
put(stream, metadata) -> StoredObject
open(storage_key, byte_range) -> stream
stat(storage_key) -> StoredObjectInfo
exists(storage_key) -> bool
delete(storage_key) -> None
```

前端媒体地址为 `/api/v1/assets/{asset_id}/content`。后端根据 `asset_id` 查询 `storage_key` 并提供图片、音频和视频 Range 响应。前端和工作流 JSON 不感知真实目录。

## 7. 文件与数据库一致性

SQLite 事务不能与文件系统移动组成同一个原子事务，因此上传和生成结果使用状态机：

1. 将内容流式写入 `tmp/`，同时计算哈希和大小。
2. 校验 MIME、大小及必要的媒体属性。
3. 在数据库创建 `assets(status=pending)`。
4. 将临时文件原子移动到最终 `storage_key`。
5. 更新资产为 `ready` 并创建项目、实体或执行关系。
6. 任一步失败时标记 `failed`，并由清理任务删除临时文件。

后台一致性任务定期处理：

- 长时间处于 `pending` 的资产。
- 数据库记录存在但文件缺失的资产。
- 磁盘存在但数据库无引用的孤儿文件。
- 已经 `pending_delete` 且没有任何引用的资产。

删除实体或项目优先使用软删除。物理文件只有在项目、资产库实体、工作流绑定和执行产物都不再引用时才允许回收。

## 8. API 边界

### 项目和工作流

- `GET /api/v1/projects`
- `POST /api/v1/projects`
- `GET /api/v1/projects/{project_id}`
- `PATCH /api/v1/projects/{project_id}`
- `DELETE /api/v1/projects/{project_id}`
- `GET /api/v1/projects/{project_id}/workflow`
- `PUT /api/v1/projects/{project_id}/workflow`
- `GET /api/v1/workflows/{workflow_id}/revisions`

工作流保存请求携带基础修订号。冲突返回 `409 revision_conflict`，前端保留本地草稿并重新拉取最新版本。

### 执行

- `POST /api/v1/workflows/{workflow_id}/executions`
- `GET /api/v1/executions/{execution_id}`
- `GET /api/v1/executions/{execution_id}/events`
- `POST /api/v1/executions/{execution_id}/cancel`

### 项目资产

- `POST /api/v1/projects/{project_id}/assets`
- `GET /api/v1/projects/{project_id}/assets`
- `GET /api/v1/assets/{asset_id}`
- `GET /api/v1/assets/{asset_id}/content`
- `DELETE /api/v1/assets/{asset_id}`

### 资产库

- `GET /api/v1/asset-library/entities`
- `POST /api/v1/asset-library/entities`
- `GET /api/v1/asset-library/entities/{entity_id}`
- `PATCH /api/v1/asset-library/entities/{entity_id}`
- `POST /api/v1/asset-library/entities/{entity_id}/assets`
- `POST /api/v1/assets/{asset_id}/save-to-library`
- `POST /api/v1/workflows/{workflow_id}/asset-bindings`
- `DELETE /api/v1/workflows/{workflow_id}/asset-bindings/{binding_id}`

### 模型配置

- `GET /api/v1/model-catalog`
- `GET /api/v1/model-configs`
- `POST /api/v1/model-configs`
- `PATCH /api/v1/model-configs/{config_id}`
- `POST /api/v1/model-configs/{config_id}/test`
- `DELETE /api/v1/model-configs/{config_id}`

错误响应统一返回稳定 `code` 和轻量 `message`，详细 provider 响应只进入后端日志或受控诊断产物。

## 9. 前后端职责

### 后端主导

- 数据库 schema、迁移与事务。
- 文件写入、读取、Range 请求和垃圾回收。
- 项目、工作流、执行和资产关联的合法性。
- 资产去重、软删除、备份与恢复。
- API Key 加密和 provider 调用。
- OpenAPI 契约和错误码。

### 前端主导

- 工作台、资产库和 API Space 的交互体验。
- 临时画布状态、节点选中状态、视口和未提交编辑。
- 请求缓存、乐观更新和失败后的轻量提示。
- 首次升级时将浏览器旧项目提交给后端迁移接口。

IndexedDB 中的项目记录在迁移后不能继续作为事实来源。服务端保存成功后才更新本地缓存标记。

## 10. 技术选型

后端当前为同步 FastAPI/Pydantic 服务，第一版推荐：

- SQLAlchemy 2.x，同步 Session。
- Python 内置 `sqlite3` 驱动。
- Alembic 管理数据库版本。
- Pydantic 继续作为 API 与领域数据校验层。
- 不增加通用 Repository 基类；按项目、工作流、执行、资产划分明确仓储接口。

SQLite 连接至少启用：

- `PRAGMA foreign_keys=ON`
- 合理的 `busy_timeout`
- 短事务；模型网络请求、视频下载和转码期间不持有数据库事务。

当前开发环境的 SQLite 为 3.41.2。SQLite 官方在 2026 年披露并修复了一个涉及 WAL、多连接并发写入和 checkpoint 的低概率问题。第一版在没有打包修复版 SQLite 前使用默认 rollback journal；若启用 WAL，运行时必须检查 SQLite 为已修复版本：3.51.3 及以上，或官方提供修复的 3.50.7、3.44.6 分支版本，并保持单机本地文件系统。

SQLite 部署约束：

- Uvicorn 默认单 worker。
- 数据库放在本机磁盘，不放 NFS 或共享网络盘。
- 并行生成任务可以存在，但所有数据库写事务必须短小。
- 当产品需要多用户、多 API worker 或分布式任务时，迁移 PostgreSQL。

## 11. 备份与恢复

备份包包含：

```text
adcraft-backup-<timestamp>/
|-- manifest.json
|-- adcraft.sqlite3
`-- storage/objects/...
```

备份流程：

1. 使用 SQLite Backup API 生成一致数据库快照，不直接复制正在写入的数据库文件。
2. 从快照读取所有 `ready` 资产的 `storage_key`。
3. 复制对应不可变文件并计算校验和。
4. 写入包含 schema 版本、应用版本、文件数量和哈希的 manifest。
5. 将目录打包为单个归档文件。

恢复前校验 manifest、数据库 schema 和文件哈希。恢复到临时目录成功后再原子替换正式数据目录。

## 12. 迁移方案

### 阶段 0：控制数据膨胀

- 停止在执行 JSON 中持久化 provider Base64 输入和输出。
- provider 调用时临时加载媒体，持久化时只保存资产 ID、哈希和摘要。
- 为当前 `data/` 创建完整备份。

### 阶段 1：引入持久化基础设施

- 增加 SQLAlchemy、Alembic、数据库 Session 和初始 schema。
- 实现 `LocalFileStorage`，先兼容现有媒体相对路径。
- 增加启动时 schema 版本检查和迁移命令。

### 阶段 2：迁移项目与工作流

- 新建项目 API 和一个项目一个工作流的修订模型。
- 前端将 IndexedDB 项目通过一次性迁移流程提交给后端。
- 迁移成功前保留浏览器原数据；收到后端确认后记录迁移标记。

### 阶段 3：迁移资产与资产库

- 扫描现有 `data/assets`、`data/videos` 和资产库 JSON。
- 计算哈希并建立 `assets`、`asset_entities`、成员和绑定记录。
- 第一轮迁移保留原相对路径，不复制现有大文件。
- 新写入内容使用新的 StorageAdapter 路径。

### 阶段 4：迁移执行数据

- 优先迁移当前和最近执行记录。
- 将活动执行、节点尝试和 provider job 状态导入数据库。
- 历史 NDJSON 可以只读保留，并按需提供离线导入工具。

### 阶段 5：切换事实来源

- 后端停止写旧 JSON 索引。
- 前端项目列表、画布保存、资产库和执行状态全部切换 API。
- IndexedDB 只保留可丢弃缓存和未提交草稿。
- 一段兼容期后清理旧读取路径。

迁移采用“一次性、可重复运行的导入器 + 切换”模式，不长期双写。双写会让文件 JSON 与 SQLite 在异常情况下产生两个事实来源。

## 13. 测试与验收

### 单元测试

- 数据库模型约束、修订号和软删除行为。
- StorageAdapter 写入、Range 读取、失败清理。
- 资产实体、成员和绑定解析。
- API Key 不出现在日志、工作流和错误响应中。

### 集成测试

- 创建项目、保存多个工作流修订并检测冲突。
- 上传项目资产，不自动进入资产库。
- 将项目资产保存到新实体和已有实体。
- 从资产库引用资产执行节点，不复制文件。
- 删除项目后资产库内容仍存在。
- 模拟文件移动失败、数据库提交失败和进程中断并执行修复。
- 视频 `Range` 请求与浏览器播放。

### 迁移测试

- 使用当前真实工作流和资产库目录的脱敏副本测试导入。
- 重复执行迁移不生成重复项目、资产或绑定。
- 校验迁移前后项目数、工作流数、执行数、资产数和文件哈希。
- 明确断言数据库和持久 JSON 中不存在 Base64 媒体内容。

### 验收标准

1. 重启浏览器和后端后，项目、工作流、执行记录和资产库保持一致。
2. 任一资产可以追溯到上传或生成来源，并能查询其项目、实体和工作流使用位置。
3. 生成结果和画布上传默认不会出现在资产库。
4. 用户主动保存到资产库时不复制文件。
5. 备份包可以在空数据目录完整恢复。
6. 旧 JSON 与 IndexedDB 数据可以通过迁移流程导入，失败不会破坏原数据。

## 14. 演进路径

当出现以下任一需求时，将关系数据迁移到 PostgreSQL：

- 多用户并发编辑或权限控制。
- 多个后端 API 实例或分布式 worker。
- 大量并发执行状态写入。
- 远程部署需要高可用数据库。

当本地磁盘不再适合媒体容量或多实例共享时，将 `LocalFileStorage` 替换为 S3/MinIO 适配器。由于数据库始终只保存 `storage_driver + storage_key`，前端 API 和业务关系不需要改变。

## 15. 参考方案

- SQLite 官方关于内部与外部 BLOB 的比较：https://www.sqlite.org/intern-v-extern-blob.html
- SQLite WAL 官方说明：https://sqlite.org/wal.html
- SQLite Backup API：https://sqlite.org/backup.html
- SQLAlchemy SQLite 方言：https://docs.sqlalchemy.org/en/20/dialects/sqlite.html
- Alembic SQLite batch migrations：https://alembic.sqlalchemy.org/en/latest/batch.html
- Supabase Storage 元数据与对象分离：https://supabase.com/docs/guides/storage/schema/design
- Directus 文件元数据与存储适配器：https://directus.io/docs/api/files
- n8n 支持的自托管数据库：https://docs.n8n.io/hosting/configuration/supported-databases-settings/
