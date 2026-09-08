# CLIProxyAPI Compose 集成设计

## 目标

将 CLIProxyAPI（CPA）作为 AdCraft 的独立 Docker Compose sidecar，使 AdCraft 的文本/LLM 请求可以通过 CPA 的 OpenAI-compatible 接口访问已授权的 Codex、Claude、Gemini 等账户，同时保持 OAuth 凭据与 AdCraft 代码、配置隔离。

## 架构

```text
浏览器 → AdCraft Web → AdCraft API ──Compose 内网──→ CPA:8317
                                      │
                                      ├─ CPA config.yaml
                                      └─ CPA auths/（OAuth 凭据）
```

- `cpa` 使用 CLIProxyAPI 官方发布镜像，镜像通过 `CLI_PROXY_IMAGE` 可替换或固定版本。
- CPA 只将需要的端口绑定到 `127.0.0.1`；AdCraft API 通过服务名 `cpa` 访问，不绕出容器网络。
- CPA 的 `config.yaml`、OAuth `auths/`、日志目录位于项目根目录的 `cpa/` 下，并由 Git 忽略。
- AdCraft 的 `LLM_BASE_URL` 指向 `http://cpa:8317/v1`，`LLM_API_KEY` 使用 CPA 配置的下游访问 key。

## 配置与凭据边界

- 提供 `cpa/config.example.yaml`，只包含占位值，不包含任何账户令牌或真实 key。
- 首次启动时如果 `cpa/config.yaml` 不存在，文档指导用户从示例复制，不自动生成 OAuth 凭据。
- `cpa/auths/` 永不提交到 Git；`.gitignore` 同时覆盖 CPA 配置、凭据和日志。
- CPA API key 仅用于 AdCraft → CPA 的本地认证；它不等于上游 OpenAI/Anthropic API key。
- 默认不开放 CPA 管理 API 到局域网或公网。

## Compose 行为

- 新增 `cpa` 服务，具备 restart policy 和 HTTP 健康检查。
- `api.depends_on.cpa` 使用 `service_healthy`，避免 API 在 CPA 未就绪时启动。
- `api` 的 `LLM_BASE_URL` 和 `LLM_API_KEY` 通过根 `.env` / `apps/api/.env` 注入，不把密钥写入版本控制文件。
- 保留 AdCraft 原有 Agent、API、Web 服务和网络；CPA 只加入同一 Compose 网络。
- CPA 的宿主机端口使用回环绑定，并允许通过根环境变量调整，避免与现有服务冲突。

## 失败处理

- CPA 未配置 `api-keys` 或 OAuth 凭据时，CPA 健康检查可通过，但 AdCraft 的真实 LLM 请求返回可识别的上游认证/模型错误；文档提供日志和连通性检查命令。
- CPA 容器启动失败时，API 不启动并保留 Compose 日志，避免产生“服务已成功但请求失败”的假状态。
- 代理不可用时不自动切换到未经用户配置的其他 provider；AdCraft 的 `MEDIA_MODE=mock` 只影响媒体生成，不改变 LLM 凭据。

## 验证

1. `docker compose config --quiet` 通过，且不打印任何真实凭据。
2. CPA、Agent、API、Web 四个服务均为 healthy。
3. 从 API 容器访问 `http://cpa:8317/v1/models`，确认代理网络连通和认证行为。
4. AdCraft API health endpoint 返回 200。
5. 使用 Mock 或已授权的测试模型完成一次最小 LLM 请求；不执行真实图片/视频付费生成。
6. 检查 `git status`，确保 `cpa/config.yaml`、`cpa/auths/`、日志和 `.env` 不会被跟踪。

## 不在本次范围

- 将 CPA 管理面板嵌入 AdCraft 前端。
- 在 AdCraft 内开发 OAuth 登录和账号池管理 UI。
- 自动把 CPA 模型目录同步到 AdCraft 的模型目录。
- 代理图片、视频、音频供应商。
- 修改 CLIProxyAPI 上游源码。
