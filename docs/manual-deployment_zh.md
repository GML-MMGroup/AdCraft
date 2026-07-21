[English](manual-deployment.md)

# 手动分步部署教程

仅当 `deploy-windows.cmd` 或 `deploy-linux.sh` 无法完成时使用本教程。它启动的是同一个仅限本机访问的 AdCraft 部署，但每一步都由您手动执行，因此可以明确看到问题出现在哪一步。

不要同时运行一键启动器和本教程中的命令。请保持完整的项目文件夹。本教程不要求安装 Python、Node.js 或独立数据库服务。

## 本部署会创建什么

Docker 会运行两个服务：

- `api`：后端，仅在 Docker 内部网络中提供服务。
- `web`：浏览器界面，只发布到 `127.0.0.1`。

## 1. 准备项目文件夹

将完整的 AdCraft 文件夹放到可写的本地位置，不要只复制 `scripts` 文件夹。

- Windows 示例：`D:\AdCraft\AdCraft-main`
- Linux 示例：`~/AdCraft`

继续前，请在该文件夹中打开终端：

```text
Windows 命令提示符：cd /d D:\AdCraft\AdCraft-main
Linux 终端：        cd ~/AdCraft
```

在 `8080` 到 `8179` 中选择一个未被占用的本地端口。本教程使用 `8080`。完成后的地址为 `http://127.0.0.1:8080`，只能在同一台计算机上访问。

## 2. 安装并启动 Docker

### Windows 10 或 Windows 11

1. 以管理员身份打开 **PowerShell**。
2. 运行以下命令；若 Windows 要求重启，请先重启。

   ```powershell
   wsl --install
   ```

3. 按照 [Docker Desktop Windows 官方安装教程](https://docs.docker.com/desktop/setup/install/windows-install/) 下载并安装 Docker Desktop。安装时出现选项，请选择 **WSL 2** 后端。
4. 启动 Docker Desktop，等待它提示 Docker Engine 已运行。它必须使用 **Linux containers**，不能使用 Windows containers。
5. 在 AdCraft 文件夹中重新打开命令提示符，检查 Docker：

   ```bat
   docker version
   docker compose version
   ```

   两条命令均成功、且 `docker version` 显示 Server 部分后再继续。

Docker Desktop 的许可与 AdCraft 分开，请确认预期用途符合 Docker 的适用条款。

### Ubuntu 或 Debian Linux

1. 按 Docker 官方的 [Ubuntu](https://docs.docker.com/engine/install/ubuntu/) 或 [Debian](https://docs.docker.com/engine/install/debian/) 教程安装 Docker Engine 和 Docker Compose 插件。请使用官方 `apt` 软件源方式，不要使用未经验证的第三方安装器。
2. 启动 Docker，并设置开机自动启动：

   ```bash
   sudo systemctl enable --now docker
   ```

3. 检查 Docker：

   ```bash
   sudo docker version
   sudo docker compose version
   ```

   两条命令均成功后再继续。本教程中的 Linux Docker 命令保留 `sudo`，因此不要求修改 Docker 用户组权限。

若因企业网络、DNS 规则或代理阻止 Docker 镜像仓库拉取，请先解决网络路径。请为 Docker 配置组织认可的代理或镜像源，重启 Docker 后再重试失败的拉取操作。不要为了 API 密钥或生产数据而使用未知的公共代理。

## 3. 创建本地配置，但不覆盖已有密钥

以下命令只会在文件不存在时创建文件。若 `apps/api/.env` 已存在，它可能包含在 AdCraft 中保存的 API 密钥，必须保留。

### Windows 命令提示符

在项目文件夹中运行：

```bat
if not exist apps\api\.env copy apps\api\.env.example apps\api\.env
if not exist apps\web\.env copy apps\web\.env.example apps\web\.env
if not exist runtime-data mkdir runtime-data
if not exist runtime-data\api mkdir runtime-data\api
if not exist runtime-data\deployment.env (
  >runtime-data\deployment.env echo ADCRAFT_PORT=8080
  >>runtime-data\deployment.env echo ADCRAFT_UID=0
  >>runtime-data\deployment.env echo ADCRAFT_GID=0
)
```

最后三条命令会创建 `runtime-data/deployment.env`，其中保存端口和 Windows 容器用户设置。若选择的不是 `8080`，请在运行前将三条命令中第一条的 `8080` 改为所选端口。

### Linux 终端

在项目文件夹中运行：

```bash
if [ ! -f apps/api/.env ]; then cp apps/api/.env.example apps/api/.env; chmod 600 apps/api/.env; fi
if [ ! -f apps/web/.env ]; then cp apps/web/.env.example apps/web/.env; chmod 600 apps/web/.env; fi
mkdir -p runtime-data/api
chmod 700 runtime-data runtime-data/api
if [ ! -f runtime-data/deployment.env ]; then
  printf 'ADCRAFT_PORT=8080\nADCRAFT_UID=%s\nADCRAFT_GID=%s\n' "$(id -u)" "$(id -g)" > runtime-data/deployment.env
  chmod 600 runtime-data/deployment.env
fi
```

若选择其他端口，请在运行前将 `ADCRAFT_PORT=8080` 改为所选端口。不要用任一 `.env.example` 覆盖已存在的 `.env` 文件。

## 4. 验证 Compose 配置

此步骤会在下载或构建镜像前检查路径和配置。

Windows 命令提示符：

```bat
docker compose --env-file runtime-data\deployment.env -f compose.yaml config
```

Linux 终端：

```bash
sudo docker compose --env-file runtime-data/deployment.env -f compose.yaml config
```

预期结果：Docker 打印解析后的配置并正常结束。若提示缺少文件，请返回步骤 3，确认当前位于完整项目文件夹中。

## 5. 构建镜像

首次构建会下载基础镜像、后端依赖和前端依赖；网络较慢时需要较长时间。请保持终端打开，Docker 会显示当前构建阶段和下载进度。

Windows 命令提示符：

```bat
docker compose --env-file runtime-data\deployment.env -f compose.yaml build
```

Linux 终端：

```bash
sudo docker compose --env-file runtime-data/deployment.env -f compose.yaml build
```

若 Docker 报告镜像仓库连接、DNS 或代理错误，说明应用尚未启动。请修复 Docker 网络/代理配置后重新运行这条构建命令。不要为了网络错误删除 `.env` 或 `runtime-data/`。

## 6. 启动 AdCraft

Windows 命令提示符：

```bat
docker compose --env-file runtime-data\deployment.env -f compose.yaml up -d --remove-orphans
```

Linux 终端：

```bash
sudo docker compose --env-file runtime-data/deployment.env -f compose.yaml up -d --remove-orphans
```

随后检查服务健康状态。

Windows 命令提示符：

```bat
docker compose --env-file runtime-data\deployment.env -f compose.yaml ps
```

Linux 终端：

```bash
sudo docker compose --env-file runtime-data/deployment.env -f compose.yaml ps
```

请等待 `api` 和 `web` 都显示为 `healthy`。首次启动时，API 会先变为健康状态，之后 Web 才启动。

## 7. 打开 AdCraft 并添加 API 密钥

在同一台计算机的浏览器中打开：

```text
http://127.0.0.1:8080
```

若选择了其他端口，请替换为所选端口。打开 **API Space**，填写计划使用的服务商凭据，然后选择 **Save credentials**。应用会将其保存在本机的 `apps/api/.env` 中；不要将该文件或其中的值粘贴到聊天、Issue 或公开文档。

## 日常手动命令

所有命令都在项目文件夹中运行。Linux 请使用表中的 `sudo docker` 形式。

| 操作 | Windows 命令提示符 | Linux 终端 |
| --- | --- | --- |
| 查看状态 | `docker compose --env-file runtime-data\deployment.env -f compose.yaml ps` | `sudo docker compose --env-file runtime-data/deployment.env -f compose.yaml ps` |
| 查看近期日志 | `docker compose --env-file runtime-data\deployment.env -f compose.yaml logs --tail=100 api web` | `sudo docker compose --env-file runtime-data/deployment.env -f compose.yaml logs --tail=100 api web` |
| 替换项目代码后重新构建 | `docker compose --env-file runtime-data\deployment.env -f compose.yaml up -d --build --remove-orphans` | `sudo docker compose --env-file runtime-data/deployment.env -f compose.yaml up -d --build --remove-orphans` |
| 停止容器但保留数据 | `docker compose --env-file runtime-data\deployment.env -f compose.yaml down` | `sudo docker compose --env-file runtime-data/deployment.env -f compose.yaml down` |

除非明确要删除本地部署状态、生成媒体和 SQLite 事件数据库，否则不要使用 `down -v`，也不要删除 `runtime-data/`。

## 故障处理

| 现象 | 处理方式 |
| --- | --- |
| `docker version` 没有显示 Server 部分。 | Windows 请启动 Docker Desktop；Linux 请运行 `sudo systemctl start docker`，再重新检查。 |
| 找不到 `docker compose`。 | 按 Docker 官方教程安装或更新 Docker Compose 插件，然后重新打开终端。 |
| 出现 `failed to fetch anonymous token`、`EOF`、DNS 或镜像仓库超时。 | 这是 Docker 网络/代理问题，不是 AdCraft API 密钥问题。修复 Docker Desktop 或 Linux Docker 的代理/DNS 路径，重启 Docker 后再重新构建。 |
| 出现 `port is already allocated`。 | 停止占用所选端口的程序，或将 `runtime-data/deployment.env` 中的 `ADCRAFT_PORT` 改为 `8080` 到 `8179` 内另一个空闲端口，然后再次执行启动命令。 |
| `api` 或 `web` 为 `exited` 或 `unhealthy`。 | 运行上表中的日志命令。分享日志时务必去除 API 密钥。修复最先报告的错误后，重新执行重新构建/启动命令。 |
| 构建成功但浏览器仍显示旧页面。 | 强制刷新浏览器缓存，然后通过 `docker compose ... ps` 和日志确认新容器正在运行。 |

该手动部署路径仍然只允许本机访问：Web 端口绑定到 `127.0.0.1`。除非已经单独设计认证、TLS、防火墙规则和数据保护方案，否则不要通过修改 Compose 配置将其暴露到网络。
