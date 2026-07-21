[English](deployment-with-docker.md)

# 部署 AdCraft

本指南在您自己的计算机上启动 AdCraft，面向首次使用者。随项目提供的启动器会在需要时安装运行所需组件、构建并启动 AdCraft，然后打印应在浏览器中打开的本地地址。

若一键启动器无法在您的计算机上完成部署，请使用本教程中的“手动分步部署”部分。该部分使用相同的 Docker 配置，但会将每一步单独列出，便于查看和处理具体报错。若完全不希望使用 Docker，请使用[不使用 Docker 的部署教程](deployment-without-docker_zh.md)。

## 您需要准备的内容

- 一份完整的 AdCraft 项目文件夹。请保持文件夹完整，不要只复制 `scripts` 文件夹后运行脚本。
- 首次部署时可用的互联网连接；启动器可能需要下载组件并构建镜像。
- 下列任一受支持的操作系统：
  - **Windows：** 64 位 Windows 10 22H2（build 19045）或更高版本，或 64 位 Windows 11 23H2（build 22631）或更高版本。计算机必须支持硬件虚拟化。不支持 Windows Server 和 Windows containers。
  - **Linux：** Ubuntu 或 Debian。首发启动器不支持其他 Linux 发行版。
- Windows 上能够以管理员身份运行文件的权限；Linux 上在启动器询问时能够输入 `sudo` 密码的账户。
- 您计划使用的服务商提供的 API 密钥。AdCraft 启动后再添加密钥；不要将密钥发到聊天、公开文档或工单中。

您**不需要**手动安装 Python、Node.js、Docker 或 Docker Compose。Windows 启动器可以设置 WSL 2 和 Docker Desktop；Linux 启动器可以安装 Docker Engine 及其 Compose 插件。这些操作需要网络连接，并可能请求管理员或 `sudo` 权限。

## 开始前

1. 将完整项目放在可写的本地文件夹中。Windows 上建议使用本地 NTFS 文件夹。
2. 保存文件夹中的工作，并确保有足够的磁盘空间用于下载组件和首次构建。
3. 请在可信的个人或工作计算机上使用。AdCraft 会在此主机保存 API 凭据和生成的媒体。
4. 初次使用时不要为了部署而手动修改文件。启动器会创建所需环境文件，并在 8080 到 8179 之间选择可用的本地端口。

最后打印的地址格式为 `http://127.0.0.1:<port>`。其中 `127.0.0.1` 表示仅限本机，不是公开网站地址。

## 在 Windows 上部署

1. 在文件资源管理器中打开项目文件夹，再打开其中的 `scripts` 文件夹。
2. 右键单击 `scripts\\deploy-windows.cmd`，选择 **Run as administrator**，然后确认 Windows 提示。
3. 在新计算机上，启动器可能会启用或安装 WSL 2 和 Docker Desktop，Windows 也可能要求重启。若要求重启，请重启 Windows，然后再次右键以管理员身份运行**同一个** `scripts\\deploy-windows.cmd` 文件。
4. 等待启动器检查系统、准备运行环境、构建 AdCraft 并启动 Web 与 API 服务。首次运行通常比之后运行更久。
5. 成功后，打开打印出的 `http://127.0.0.1:<port>` URL。启动器通常会自动打开浏览器；若没有，请在同一台计算机的浏览器中粘贴显示的 URL。

预期结果：两个服务均变为健康状态，AdCraft 在本机打开。Docker Desktop 必须处于 **Linux containers** 模式。部署者负责确认并遵守适用的 Docker Desktop 许可条款。

## 在 Linux 上部署

1. 在**项目文件夹中**打开终端。
2. 运行以下精确命令：

   ```bash
   bash scripts/deploy-linux.sh
   ```

3. **仅当启动器询问时**输入 `sudo` 密码。它可能需要该权限来安装或启动 Docker 和支持它的系统软件包。不要在 `sudo` 提示处输入 API 密钥。
4. 等待启动器检查 Ubuntu/Debian、准备运行环境、构建 AdCraft，并等待 Web 与 API 服务变为健康状态。首次运行通常比之后运行更久。
5. 打开打印出的 `http://127.0.0.1:<port>` URL。在带图形界面的 Linux 桌面上，启动器可能自动打开它；否则请在同一台计算机的浏览器中粘贴该地址。

预期结果：命令以部署成功消息和本地 URL 结束。您无需自行安装 Python、Node.js、Docker 或 Docker Compose。

## AdCraft 已运行后更换端口

Docker 部署只发布一个本机网页端口，后端 API 保留在 Docker 内部网络中。容器启动时，所选网页端口也会同步给后端的凭据来源限制。不要只修改端口后重启 Web 容器。需要换端口时，如有需要先停止 AdCraft，然后在项目文件夹重新运行部署启动器；它会重新创建端口互相匹配的 Web 与 API 配置，同时保留 .env、runtime-data 和已保存的 API 密钥。

## 一键部署失败时：手动分步部署

仅当 deploy-windows.cmd 或 deploy-linux.sh 无法完成时使用本部分。不要在一键启动器已成功运行时再执行这些命令。

仅当 `deploy-windows.cmd` 或 `deploy-linux.sh` 无法完成时使用本教程。它启动的是同一个仅限本机访问的 AdCraft 部署，但每一步都由您手动执行，因此可以明确看到问题出现在哪一步。

不要同时运行一键启动器和本教程中的命令。请保持完整的项目文件夹。本教程不要求安装 Python、Node.js 或独立数据库服务。

### 本部署会创建什么

Docker 会运行两个服务：

- `api`：后端，仅在 Docker 内部网络中提供服务。
- `web`：浏览器界面，只发布到 `127.0.0.1`。

### 1. 准备项目文件夹

将完整的 AdCraft 文件夹放到可写的本地位置，不要只复制 `scripts` 文件夹。

- Windows 示例：`D:\AdCraft\AdCraft-main`
- Linux 示例：`~/AdCraft`

继续前，请在该文件夹中打开终端：

```text
Windows 命令提示符：cd /d D:\AdCraft\AdCraft-main
Linux 终端：        cd ~/AdCraft
```

在 `8080` 到 `8179` 中选择一个未被占用的本地端口。本教程使用 `8080`。完成后的地址为 `http://127.0.0.1:8080`，只能在同一台计算机上访问。

### 2. 安装并启动 Docker

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

### 3. 创建本地配置，但不覆盖已有密钥

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

### 4. 验证 Compose 配置

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

### 5. 构建镜像

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

### 6. 启动 AdCraft

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

### 7. 打开 AdCraft 并添加 API 密钥

在同一台计算机的浏览器中打开：

```text
http://127.0.0.1:8080
```

若选择了其他端口，请替换为所选端口。打开 **API Space**，填写计划使用的服务商凭据，然后选择 **Save credentials**。应用会将其保存在本机的 `apps/api/.env` 中；不要将该文件或其中的值粘贴到聊天、Issue 或公开文档。

### 日常手动命令

所有命令都在项目文件夹中运行。Linux 请使用表中的 `sudo docker` 形式。

| 操作 | Windows 命令提示符 | Linux 终端 |
| --- | --- | --- |
| 查看状态 | `docker compose --env-file runtime-data\deployment.env -f compose.yaml ps` | `sudo docker compose --env-file runtime-data/deployment.env -f compose.yaml ps` |
| 查看近期日志 | `docker compose --env-file runtime-data\deployment.env -f compose.yaml logs --tail=100 api web` | `sudo docker compose --env-file runtime-data/deployment.env -f compose.yaml logs --tail=100 api web` |
| 替换项目代码后重新构建 | `docker compose --env-file runtime-data\deployment.env -f compose.yaml up -d --build --remove-orphans` | `sudo docker compose --env-file runtime-data/deployment.env -f compose.yaml up -d --build --remove-orphans` |
| 停止容器但保留数据 | `docker compose --env-file runtime-data\deployment.env -f compose.yaml down` | `sudo docker compose --env-file runtime-data/deployment.env -f compose.yaml down` |

除非明确要删除本地部署状态、生成媒体和 SQLite 事件数据库，否则不要使用 `down -v`，也不要删除 `runtime-data/`。

### 故障处理

| 现象 | 处理方式 |
| --- | --- |
| `docker version` 没有显示 Server 部分。 | Windows 请启动 Docker Desktop；Linux 请运行 `sudo systemctl start docker`，再重新检查。 |
| 找不到 `docker compose`。 | 按 Docker 官方教程安装或更新 Docker Compose 插件，然后重新打开终端。 |
| 出现 `failed to fetch anonymous token`、`EOF`、DNS 或镜像仓库超时。 | 这是 Docker 网络/代理问题，不是 AdCraft API 密钥问题。修复 Docker Desktop 或 Linux Docker 的代理/DNS 路径，重启 Docker 后再重新构建。 |
| 出现 `port is already allocated`。 | 停止占用所选端口的程序，或将 `runtime-data/deployment.env` 中的 `ADCRAFT_PORT` 改为 `8080` 到 `8179` 内另一个空闲端口，然后再次执行启动命令。 |
| `api` 或 `web` 为 `exited` 或 `unhealthy`。 | 运行上表中的日志命令。分享日志时务必去除 API 密钥。修复最先报告的错误后，重新执行重新构建/启动命令。 |
| 构建成功但浏览器仍显示旧页面。 | 强制刷新浏览器缓存，然后通过 `docker compose ... ps` 和日志确认新容器正在运行。 |

该手动部署路径仍然只允许本机访问：Web 端口绑定到 `127.0.0.1`。除非已经单独设计认证、TLS、防火墙规则和数据保护方案，否则不要通过修改 Compose 配置将其暴露到网络。

## 打开 AdCraft 并添加 API 密钥

1. 打开打印出的本地 URL，然后进入 **API Space**。
2. 选择当前可用的服务商 **Volcengine Ark**。API Space 为 **LLM**、**Image** 和 **Video** 分别提供密钥输入框。请为计划使用的工作类型输入对应密钥。若服务商发放的一把密钥对三种类型都具有正确权限，可使用页面上的 **Use for all**；否则请分别填写适用的密钥。
3. 选择 **Save credentials**。保存成功时会提示凭据已保存并已应用，因此不需要为此重启 AdCraft。
4. 若 API Space 为已配置的密钥提供连接测试，可用它确认服务商连接。测试成功会显示连接成功，有时还会显示模型名称。

密钥会保存在此主机的 `apps/api/.env` 中，状态页仅以掩码显示它们。请将该文件视为密码文件：不要分享、提交、附在支持请求中，也不要把其内容粘贴到终端记录里。API 使用可能产生服务商费用；生成媒体前请确认密钥、账户、模型访问权限与计费权限正确。

## 日常命令

以下命令应在已经部署过 AdCraft 的项目文件夹中运行。

| 要执行的操作 | Windows PowerShell | Linux 终端 | 预期结果 |
| --- | --- | --- | --- |
| 检查状态 | `.\\scripts\\status-windows.ps1` | `bash scripts/status-linux.sh` | 显示本地 URL、API 健康状态和 Web 健康状态。 |
| 查看近期日志 | `.\\scripts\\logs-windows.ps1` | `bash scripts/logs-linux.sh` | 显示最多 100 行近期 API 与 Web 日志。不要发布含敏感信息的日志。 |
| 停止 AdCraft | `.\\scripts\\stop-windows.ps1` | `bash scripts/stop-linux.sh` | 停止容器，同时保留配置、运行数据、镜像和卷。 |
| 再次启动，或替换项目文件后更新 | 右键 `scripts\\deploy-windows.cmd` 并选择 **Run as administrator** | `bash scripts/deploy-linux.sh` | 重用已保存的本地配置，并再次打印本地 URL。 |

您不需要自行运行 Docker 命令。若 Windows PowerShell 阻止某个维护脚本，请从项目文件夹以管理员身份打开 PowerShell，再运行表中显示的命令。

## 保留这些文件

- `apps/api/.env` 保存后端配置及在 API Space 中保存的 API 密钥。请保持私密，更新 AdCraft 时不要删除它。
- `apps/web/.env` 保存 Web 应用的本地配置。请与项目一起保留。
- `runtime-data/` 保存生成的媒体和部署状态，包括所选本地端口。若希望保留生成结果和已保存的部署状态，更新时不要删除它。

停止 AdCraft 不会删除这些文件、镜像或卷。移动或删除项目文件夹前，请使用组织认可的加密备份方式备份私密凭据和重要生成媒体。

## 常见问题

| 问题 | 处理方式 | 预期结果 |
| --- | --- | --- |
| Windows 提示需要管理员权限。 | 右键 `scripts\\deploy-windows.cmd`，选择 **Run as administrator**。 | 启动器可以检查前置条件并继续。 |
| Windows 启用 WSL 2 或要求重启。 | 重启 Windows，然后再次以管理员身份运行同一个 `scripts\\deploy-windows.cmd` 文件。 | 第二次运行时 WSL 2 已可用。 |
| Docker Desktop 缺失、未就绪，或正在使用 Windows containers。 | 保持网络连接，让启动器完成设置；若提示则启动 Docker Desktop，并切换到 Linux containers 模式。之后重新运行启动器。 | 启动器可以使用 Docker 和 Docker Compose。 |
| 拉取 Docker 镜像时出现 `EOF`、匿名令牌错误，或无法连接 `auth.docker.io`。 | 保持代理客户端运行。在 Docker Desktop 中打开 **Settings → Resources → Proxies**，选择手动配置，只在 HTTP/HTTPS Proxy 输入框中填写代理 URL（例如 FlClash 正在该地址监听时填写 `http://127.0.0.1:7890`；不要填写 `HTTP Proxy:` 之类的前缀）。如有需要，在 FlClash 中启用 TUN/全局模式，并让 `docker.io`、`docker.com`、`dockerusercontent.com` 走代理。应用设置或重启 Docker Desktop 后，在命令提示符运行 `docker pull docker/dockerfile:1.7`；仅在该命令成功后重新运行启动器。 | Docker 可以拉取构建所需的 Dockerfile 前端和镜像层。 |
| Windows 版本被拒绝。 | 使用 64 位 Windows 10 22H2 build 19045+，或 Windows 11 23H2 build 22631+。 | 通过受支持平台检查。 |
| Linux 启动器拒绝当前操作系统。 | 此部署路径请使用 Ubuntu 或 Debian。 | 启动器可以识别受支持的系统版本。 |
| 出现 Linux `sudo` 提示。 | 仅在该提示处输入本地账户密码；不要输入 API 密钥。 | 启动器可安装或启动所需系统服务。 |
| 成功后没有打开浏览器。 | 在同一台计算机的浏览器中粘贴打印出的 `http://127.0.0.1:<port>` URL。 | 本地 AdCraft 页面打开。 |
| 8080 到 8179 的所有端口都被占用。 | 停止或重新配置占用这些端口的其他本地程序，然后重新运行部署启动器。 | AdCraft 可以选择空闲端口并打印 URL。 |
| 部署报告健康检查超时或服务失败。 | 使用上表命令检查状态并读取近期日志；分享内容时务必排除 API 密钥。处理报告的本地问题后，重新运行部署启动器。 | API 与 Web 服务报告健康。 |
| API Space 无法保存或测试密钥。 | 检查服务商密钥、权限、计费/额度、模型访问权限和网络连接；修正后再次保存。 | API Space 显示凭据已配置，且任何可用的连接测试成功。 |
| 脚本提示缺少项目文件或部署状态。 | 返回完整项目文件夹；在使用状态、日志或停止命令前，先运行部署启动器。 | 启动器会创建所需本地状态。 |

## 范围与安全

- 此部署路径仅面向上文列出的受支持 Windows 和 Linux 桌面系统；它不配置公共服务器、远程访问、TLS、用户账户或共享网络访问。
- Web 端口绑定到 `127.0.0.1`，因此只能在部署该实例的计算机上打开打印出的 URL。除非已另行设计并保护该变更，否则不要通过修改部署配置把它暴露到网络上。
- 请保持 `apps/api/.env`、`apps/web/.env` 和 `runtime-data/` 私密。它们可能包含凭据、配置、部署状态及生成媒体。
- 启动器不会修改代理设置，也不会保存代理凭据。请只在 Docker Desktop 或组织认可的网络客户端中配置代理。
- 只能使用您有权使用的 API 密钥和媒体。保护服务商账户、关注服务商费用，并遵守组织的数据处理要求。
- 除非已有认可的备份并了解可能丢失本地凭据、生成媒体或部署状态，否则不要为了排查更新问题而删除环境文件或 `runtime-data/`。
