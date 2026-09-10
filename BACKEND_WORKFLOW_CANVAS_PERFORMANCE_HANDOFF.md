# AdCraft Workflow Canvas 性能优化：后端配合事项

## 目的

本文件用于后端联调。前端已经完成以下方向的优化：

- React Flow viewport 只负责平移和缩放变换；
- 节点与 SVG 连线保持分层渲染；
- Agent Chat 历史消息按可视区域附近分段挂载；
- 画布图片优先加载 preview，视频优先加载 poster，原始媒体只在查看、播放或编辑时加载。

后端配合的核心目标是提供可信、轻量、版本固定的媒体预览信息。该工作不需要改变工作流执行、节点生成、SSE 或提交交互协议。

## 一、必须保证的媒体契约

前端会直接使用后端返回的精确 AssetVersion 信息：

```json
{
  "asset_id": "asset_123",
  "version_id": "version_456",
  "media_type": "image",
  "preview_url": "/api/v2/assets/asset_123/preview?v=version_456",
  "poster_url": null
}
```

视频示例：

```json
{
  "asset_id": "asset_video_123",
  "version_id": "version_video_456",
  "media_type": "video",
  "preview_url": null,
  "poster_url": "/api/v2/assets/asset_video_123/poster?v=version_video_456"
}
```

要求：

1. `asset_id` 和 `version_id` 必须来自同一个 AssetVersion。
2. 前端不取“最新版本”替代后端返回的 `version_id`。
3. `preview_url` 必须指向图片预览 rendition，而不是原始 `/content`。
4. 视频 `poster_url` 必须指向静态图片，不要要求前端加载视频后 seek 获取首帧。
5. 没有可用 rendition 时返回 `null`，不要返回原始媒体地址作为伪 preview/poster。
6. 预览地址和原始内容地址必须使用相同的项目访问权限。

如果当前生成的 V2 contract 已经包含这些字段，则只需确认语义和响应内容，不需要新增接口。

## 二、图片 preview 要求

图片节点首屏只会请求 `preview_url`。建议后端提供：

- WebP 或 AVIF 格式；
- 最大边约 640～960px；
- 保持原始宽高比；
- 保留透明通道（如果原图需要）；
- 生成失败时返回 `null`，不要让前端猜测地址。

原始 `/content` 接口保持现有行为，供详情查看、下载和编辑使用，不需要改成缩略图。

## 三、视频 poster 要求

视频节点首屏只会请求 `poster_url`，不会自动创建 `<video>` 或 seek：

- poster 使用 JPEG、WebP 或 AVIF；
- 建议最大边约 640～960px；
- 使用稳定的视频代表帧；
- poster 生成可以是上传/视频生成完成后的异步任务；
- poster 尚未准备好时明确返回 `null`；
- 原始视频 `/content` 继续支持 Range 请求，供播放和编辑器使用。

前端的播放对话框仍会使用原始视频地址，因此 poster 不需要承担播放功能。

## 四、版本化缓存响应头

由于 URL 已经包含 `version_id`，同一个 AssetVersion 的 preview/poster 可以使用长期缓存：

```http
Cache-Control: public, max-age=31536000, immutable
Content-Type: image/webp
ETag: "asset-123-version-456-preview"
```

要求：

- `version_id` 变化时，响应内容和缓存身份必须变化；
- 不要在服务端重写或删除 `?v=<version_id>`；
- 如果 preview/poster 生成结果发生变化，应创建新的 AssetVersion 或新的明确 rendition 版本标识；
- 访问控制不能因为设置长期缓存而失效，CDN/代理需要遵循项目权限策略。

如果开发环境继续使用 `no-store`，功能仍然正确，但无法验证真实的跨刷新缓存收益。生产和验收环境建议开启上述缓存头。

## 五、存储与生成时机建议

后端可以复用现有媒体存储和处理管线，不要求修改工作流业务流程：

1. AssetVersion 创建或媒体生成完成后，异步生成 preview/poster。
2. rendition 完成后写入 AssetVersion 的预览元数据。
3. API 返回 rendition URL 和对应的 `version_id`。
4. rendition 失败时保留原始 AssetVersion，但将对应字段置为 `null`，并记录可观测错误。

不要在每次 `GET /workflows/{id}` 时同步转码或生成缩略图，否则会把媒体处理延迟重新带回工作流首屏。

## 六、时间线接口（可选的后续优化）

本轮前端已经可以减少聊天历史的 DOM 和 React 挂载数量，后端不需要立即改时间线接口。

如果真实项目的历史消息达到数百或数千条，建议后续增加分页/游标能力，例如：

```text
before_seq
after_seq
limit
```

要求保持现有消息顺序、事件序号和去重语义。该项属于后续数据规模优化，不是本轮 preview/poster 接入的阻塞项。

## 七、后端验收清单

后端完成后，请使用至少一个图片 AssetVersion 和一个视频 AssetVersion 验证：

- 项目/工作流响应包含准确的 `asset_id` 和 `version_id`；
- 图片 `preview_url` 返回轻量图片，而非原图内容；
- 视频 `poster_url` 返回静态图片，而非视频文件；
- preview/poster 版本参数保留且与 AssetVersion 一致；
- 无 rendition 时字段为 `null`；
- 未授权用户不能读取 preview/poster；
- 原始 content、下载和 Range 播放行为不受影响；
- 同一个版本重复请求可以命中缓存；
- 新版本不会复用旧版本的 preview/poster。

前端浏览器验收预期：打开包含多个图片和视频节点的工作流时，首屏只请求 preview/poster，不请求原始视频；点击播放或打开编辑器后才请求原始媒体。

## 八、本轮明确不需要后端修改的内容

- viewport transform；
- React Flow 节点与 SVG 连线分层；
- Agent Chat 历史消息的前端虚拟化；
- 节点拖动、缩放和平移交互；
- 当前方案卡、Decision Dock 和聊天提交协议；
- 工作流运行状态、节点生成和 Presentation SSE。

如果现有 V2 响应已经满足第二至第四节的媒体字段和缓存语义，则后端本轮只需完成契约确认、部署和验收，不需要新增业务逻辑。
