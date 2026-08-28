# CLIProxyAPI（CPA）Compose 集成

AdCraft 通过 Compose 内网访问 CLIProxyAPI（CPA）的 OpenAI-compatible 接口。CPA 负责自己的 OAuth 登录、账号池和下游 API key；AdCraft 只保存访问 CPA 的本地 key。

## 首次配置

在项目根目录执行：

```powershell
Copy-Item cpa/config.example.yaml cpa/config.yaml
```

编辑 `cpa/config.yaml`，把 `api-keys` 中的占位值改为随机生成的本地 key。不要把 OAuth 文件、真实 key 或 `cpa/config.yaml` 提交到 Git。

将 CLIProxyAPI 支持的 Codex、Claude、Gemini 等 OAuth 登录产物保存到 `cpa/auths/`。登录方式以 CPA 官方文档为准。

在 `apps/api/.env` 中配置 AdCraft 到 CPA 的连接：

```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=http://cpa:8317/v1
LLM_API_KEY=与cpa/config.yaml相同的本地key
```

`LLM_*_MODEL` 必须填写 CPA 实际暴露的模型名或 alias。CPA 只代理 LLM；图片、视频、音频仍需分别配置 AdCraft 的供应商。

## 启动与检查

```powershell
docker compose up -d
docker compose ps
docker compose logs --tail=100 cpa
```

CPA 在容器内监听 `0.0.0.0:8317`，但宿主机只绑定 `127.0.0.1:8317`；AdCraft API 在 Compose 内部使用 `http://cpa:8317/v1`。停止服务：

```powershell
docker compose down
```

重启 CPA：

```powershell
docker compose restart cpa
```

## 安全边界

- `cpa/auths/`、`cpa/config.yaml`、`cpa/logs/` 和 `.env` 均为本地运行时数据。
- 不要把 OAuth 文件、API key、管理密钥或带凭据的日志上传到 GitHub、Issue 或聊天中。
- 订阅 OAuth 通过第三方代理使用时，仍需遵守对应服务条款；CPA 的本地 key 不等于上游官方 API key。
- 不要把 CPA 管理端口绑定到公网或不受信任的局域网。

## 常见问题

`cpa` healthy 但 AdCraft 请求返回 401：检查 `apps/api/.env` 的 `LLM_API_KEY` 是否与 `cpa/config.yaml` 的 `api-keys` 完全一致。

模型不存在：使用 CPA 暴露的模型 alias 更新对应的 `LLM_*_MODEL`。

OAuth 回调失败：确认 CPA 官方要求的回调端口已在本机可用；如端口冲突，通过根 `.env` 的 `CLI_PROXY_PORT` 修改 API 端口，并按 CPA 文档处理额外回调端口。


