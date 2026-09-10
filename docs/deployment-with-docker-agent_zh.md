# Agent 运行手册：使用 Docker 部署 AdCraft

本手册面向能够访问完整 AdCraft 项目和终端的桌面编码 Agent。必须达成的结果是：在本机启动 AdCraft 的 Agent Runtime、API 和 Web 三个服务，确认它们健康，并向用户返回可访问的网页地址。

需要了解面向用户的说明或手动排错命令时，读取[使用 Docker 部署 AdCraft](deployment-with-docker_zh.md)。

## 执行约束

- 使用用户现有的项目副本。只有同时存在 `compose.yaml`、`apps/api/pyproject.toml`、`apps/api/agent/package.json` 和 `apps/web/package.json` 时，才认定当前目录为项目根目录。
- 按当前文件部署。保留已有 `.env`、`runtime-data/`、数据库、媒体文件和 Docker volumes。
- 部署命令运行期间持续观察并转述有效进度。只要输出、下载字节数或网络活动仍在变化，耗时较长的镜像下载和构建就仍在运行。
- 保持仅限本机访问。现有 Compose 配置把网页绑定到 `127.0.0.1`，不得改成公网监听地址。
- 将 `.env` 和 `runtime-data/deployment.env` 视为密钥文件，不输出其中的值，也不把它们加入 Git。
- 启动 AdCraft 不需要供应商 API Key。部署完成后由用户在网页中输入凭据。
- 以仓库自带启动器为唯一事实来源，不使用临时命令重新实现 Compose、端口、内部令牌或环境变量逻辑。
- 只有 UAC 确认、输入 sudo 密码、重启 Windows、修改桌面代理等 Agent 无法代办的操作才请求用户介入。

## 1. 检查环境

1. 进入项目根目录。
2. 记录 `git status --short` 作为上下文，但不得 reset、clean、stash 或覆盖用户改动。
3. 判断操作系统：
   - Windows：64 位 Windows 10 22H2（build 19045+）或 Windows 11 23H2（build 22631+）。
   - Linux：带有 `bash` 的 Ubuntu 或 Debian。读取 `/etc/os-release`，不要根据终端提示符猜测系统。
4. 判断当前 Shell 是否位于容器内部。如果位于容器中，并且 `docker info` 无法连接外部 Docker Engine，则明确报告当前环境不是受支持的部署主机。不得尝试 Docker-in-Docker，也不得修改外层容器。
5. 检查 Dockerfile 所需镜像仓库的网络连通性：Docker Hub 和 `ghcr.io`。预检失败只用于诊断，真正部署仍以启动器的结果为准。

确认项目根目录，并确定一个受支持的宿主机执行分支后，本阶段完成。

## 2. 运行权威启动器

### Windows

Windows 启动器必须在 Windows PowerShell 中运行，不要放到 WSL 中运行。如果当前进程已有管理员权限，执行：

```powershell
Set-Location C:\path\to\AdCraft
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy-windows.ps1
```

如果当前进程没有管理员权限，通过 UAC 启动同一个脚本并等待它结束：

```powershell
Set-Location C:\path\to\AdCraft
$script = (Resolve-Path .\scripts\deploy-windows.ps1).Path
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$script`""
$process = Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "AdCraft deployment exited with code $($process.ExitCode)." }
```

用户可能需要确认 UAC。启动器会检查 Windows 版本，启用 WSL 2，安装或启动 Docker Desktop，初始化缺失的本地配置，选择空闲 Web 端口，构建镜像，启动三个服务，等待健康检查并打开浏览器。

如果启用 WSL 2 后 Windows 要求重启，把它记录为“等待重启后继续”，而不是部署完成。请用户重启 Windows；重启后在同一项目副本中再次运行同一个启动器。

### Linux

在可见的终端中执行：

```bash
cd /path/to/AdCraft
bash scripts/deploy-linux.sh
```

等待命令结束。启动器会复用能够正常工作的 Docker Engine；如果受支持的 Ubuntu/Debian 主机尚未安装 Docker，则通过 root 权限安装 Docker Engine 和 Compose v2。之后它会初始化缺失的本地配置，在 `8080`–`8179` 中选择空闲 Web 端口，构建镜像，启动三个服务，等待健康检查，并在存在桌面会话时打开浏览器。启动恢复可能继续执行中断的视频导出，因此应持续观察最长 30 分钟的状态显示，不要把短暂无输出直接判断为卡死。

如果 sudo 要求密码，请用户在同一个终端中输入，然后继续观察执行过程。

只有启动器成功退出，并打印带有本机 URL 的 `部署成功` 后，本阶段才完成。

### 代码更新后重新部署

当用户现有项目副本已经包含更新后的代码时，再次运行当前操作系统对应的同一个权威启动器。保留 `.env`、`runtime-data/`、数据库、媒体文件和 Docker volumes。启动器会重新构建发生变化的镜像、复用可用的 Docker 缓存、重建整组服务，并等待三个健康检查。已有容器处于健康状态并不能证明其中运行的是新代码；每次重新部署后都要继续完成下一节验证。

## 3. 验证完整系统

即使启动器已经报告成功，也要运行对应平台的状态命令。

Windows PowerShell：

```powershell
Set-Location C:\path\to\AdCraft
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\status-windows.ps1
```

Linux：

```bash
cd /path/to/AdCraft
bash scripts/status-linux.sh
```

然后从宿主机使用较短超时时间请求状态命令给出的 Web URL。只有同时满足以下条件才算验证通过：

1. `agent`、`api` 和 `web` 三个容器都在运行且健康；
2. 宿主机能够访问 Web URL；
3. URL 使用 `127.0.0.1` 或 `localhost`。

如果启动器没有打开浏览器，则打开该 URL。告知用户现在可以在 API Space 中输入供应商 API Key。只报告网页地址，不暴露环境变量值或 Agent 内部令牌。

## 4. 处理部署失败

保留第一个失败命令及其完整错误。匹配对应分支，只进行一个与原因直接相关的状态调整，然后重新运行权威启动器。

- **Windows 要求重启：**重启后继续运行同一个启动器。
- **Docker Desktop 已安装但不可用：**启动 Docker Desktop，等待 `docker info` 成功，确认使用 Linux containers 模式，然后重试。
- **Docker Hub 或 `ghcr.io` 出现 EOF、超时、DNS 或令牌错误：**分别检查宿主机和 Docker Engine 到失败地址的连接。按照[使用 Docker 部署 AdCraft](deployment-with-docker_zh.md#常见问题)中的代理说明处理。如果必须操作 Docker Desktop 界面，请用户协助。不得关闭 TLS 校验或安装不可信证书。
- **Linux 软件源失败：**找出具体失败的软件源。不相关的损坏 APT 源需要由用户或管理员修正或禁用后再重试，不要静默改写第三方软件源。
- **端口冲突：**重新运行启动器。端口选择由启动器负责，它会保持 Web 来源、API 路由和保存状态一致。
- **容器不健康：**修改任何内容之前，先读取仓库自带的日志。

Windows PowerShell：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\logs-windows.ps1
```

Linux：

```bash
bash scripts/logs-linux.sh
```

如果重复失败，并且没有新的环境状态可改变，则停止重试。向用户报告操作系统、失败阶段、原始错误、相关状态或日志片段，以及下一步只需用户完成的操作。仅仅镜像构建成功不等于部署成功。

## 完成报告

最终向用户简洁报告：

- 操作系统和采用的 Docker 执行路径；
- 成功运行的启动器命令；
- Agent Runtime、API、Web 的健康状态；
- 本机 Web URL；
- 是否已打开浏览器；
- 是否仍有需要用户完成的操作。

只有三个服务全部通过健康检查，并且 Web URL 可以访问，部署才算完成。
