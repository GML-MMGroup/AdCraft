# Agent 运行手册：不使用 Docker 部署 AdCraft

本手册面向能够访问完整 AdCraft 项目和终端的桌面编码 Agent。必须达成的结果是：以本机原生方式启动 Agent Runtime、API 和 Web 三个进程，确认它们健康，并向用户返回可访问的网页地址。

需要安装前置工具或查看面向用户的手动排错步骤时，读取[不使用 Docker 部署 AdCraft](deployment-without-docker_zh.md)。

## 执行约束

- 只有同时存在 `apps/api/pyproject.toml`、`apps/api/uv.lock`、`apps/api/agent/package.json`、`apps/api/agent/package-lock.json`、`apps/web/package.json` 和 `apps/web/package-lock.json` 时，才认定当前目录为项目根目录。
- 部署用户现有项目副本。保留 `.env`、`runtime-data/`、数据库、媒体、PID 文件和日志；只有仓库脚本可以替换自己判定为过期的运行状态。
- 命令运行期间持续观察并转述下载、安装、启动和健康检查进度。
- 所有服务都必须监听回环地址，不得把 `127.0.0.1` 改成局域网或公网地址。
- 将 `.env` 和 `runtime-data/native/native.env` 视为密钥文件，不输出其中的值，也不把它们加入 Git。
- 启动时不需要供应商 API Key。网页可用后，由用户在 API Space 中输入凭据。
- 以仓库自带启动器作为依赖同步、进程顺序、内部令牌、端口、可信来源、日志和 PID 状态的唯一事实来源。
- 只有 UAC 确认、输入管理员密码、安装系统工具后重启等 Agent 无法代办的操作才请求用户介入。

## 1. 检查环境

1. 进入项目根目录。
2. 记录 `git status --short`，但不得 reset、clean、stash 或覆盖用户改动。
3. 通过操作系统信息判断宿主机：
   - 64 位 Windows 10 或 Windows 11；或
   - [原生部署教程](deployment-without-docker_zh.md#第-1-步一次性安装系统工具)明确支持的 Linux 发行版。
4. 检查所需工具及版本：
   - `uv`；
   - Node.js 22 和配套的 `npm`；
   - 来自同一发行版、版本为 `>=6.1,<8` 的 FFmpeg 和 ffprobe；
   - 仅 Linux：`curl`、`setsid` 以及启动器使用的套接字检查工具。
5. 如果工具缺失或版本不兼容，只读取并执行用户教程“第 1 步”中与当前系统匹配的小节。安装后重新检查真实版本；安装器返回成功本身不算验证完成。

只有全部可执行文件都能在即将运行启动器的同一个环境中找到，本阶段才完成。

## 2. 运行权威启动器

启动器依次执行八个阶段：校验、初始化本地状态、同步后端依赖、安装 Agent Runtime 依赖、安装 Web 依赖、启动 Agent Runtime、启动 API、启动 Web。不得只启动其中两个进程。

### Windows

从项目根目录使用 Windows PowerShell：

```powershell
Set-Location C:\path\to\AdCraft
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy-native-windows.ps1
```

直接运行 PowerShell 脚本，使 Agent 能够保留并检查完整输出。只有安装前置工具时才根据需要使用 UAC；原生启动器本身应由最终拥有进程和 `runtime-data/` 的用户运行。

### Linux

在可见的 Bash 终端中运行：

```bash
cd /path/to/AdCraft
bash scripts/deploy-native-linux.sh
```

启动器会输出每个阶段，以及 `uv sync` 和 `npm ci` 产生的进度。持续观察，直到它打印最终 URL 或明确错误。API 启动恢复可能继续执行中断的视频导出，因此就绪状态最长可能持续显示 30 分钟。

只有八个阶段全部完成，并且启动器打印本机 Web URL 后，本阶段才完成。

## 3. 将端口冲突作为一个整体处理

原生部署默认使用 API `8000`、内部 Agent Runtime `8765`、Web `5189`。三个端口必须互不相同且未被占用。

如果启动器报告冲突，检查正在监听的套接字，并在 `1024`–`65535` 中选择三个空闲端口。通过同一次启动器调用重新启动全部三个受管进程，使 Web 代理、API 到 Agent 的连接和 Web 可信来源一起更新。

Windows PowerShell：

```powershell
Set-Location C:\path\to\AdCraft
$env:ADCRAFT_NATIVE_API_PORT = '8001'
$env:ADCRAFT_NATIVE_AGENT_PORT = '8766'
$env:ADCRAFT_NATIVE_WEB_PORT = '5190'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy-native-windows.ps1
```

Linux：

```bash
cd /path/to/AdCraft
ADCRAFT_NATIVE_API_PORT=8001 \
ADCRAFT_NATIVE_AGENT_PORT=8766 \
ADCRAFT_NATIVE_WEB_PORT=5190 \
bash scripts/deploy-native-linux.sh
```

以上端口只是示例，重试前必须确认所选端口空闲。启动后不得只修改 Web 或 API 单个进程的端口；应带上全部端口值重新运行完整启动器。

## 4. 验证完整系统

每次启动器看似成功后，都运行对应平台的状态命令。

Windows PowerShell：

```powershell
Set-Location C:\path\to\AdCraft
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\status-native-windows.ps1
```

Linux：

```bash
cd /path/to/AdCraft
bash scripts/status-native-linux.sh
```

然后使用较短超时时间请求状态命令给出的 Web URL。只有同时满足以下条件才算验证通过：

1. Agent Runtime、API 和 Web 各自都有仍在运行的受管进程；
2. Agent Runtime 和 API 显示 healthy，Web 显示 reachable；
3. 宿主机能够访问报告的 Web URL；
4. URL 使用 `127.0.0.1` 或 `localhost`。

如果启动器没有打开浏览器，则打开该 URL。告知用户现在可以在 API Space 中输入供应商 API Key。不得暴露 Agent 内部令牌。

## 5. 处理部署失败

保留第一个失败阶段和原始错误。修改配置前，先查看仓库管理的日志。

Windows PowerShell：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\logs-native-windows.ps1
```

Linux：

```bash
bash scripts/logs-native-linux.sh
```

只执行与错误匹配的最小恢复操作：

- **缺少可执行文件或版本不正确：**安装用户教程指定的准确前置工具；如果 PATH 已变化则打开新 Shell；重新检查版本后再运行启动器。
- **依赖下载失败：**确认失败来自 `uv`、npm 还是操作系统包管理器。修复对应工具的网络、registry 或代理路径后重试；不得混用包管理器或删除锁文件。
- **端口冲突：**按上一节选择三个空闲端口，然后重新运行完整启动器。
- **进程状态过期：**先使用仓库提供的停止脚本，再重新运行启动器。
- **Agent Runtime、API 或 Web 启动失败：**读取对应的受管日志，并保留其它日志和 `runtime-data/` 作为诊断依据。

Windows PowerShell 停止命令：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-native-windows.ps1
```

Linux 停止命令：

```bash
bash scripts/stop-native-linux.sh
```

只有环境状态发生了相关变化才重试。如果阻塞条件不变，则向用户报告操作系统、失败阶段、工具版本、原始错误、相关日志片段，以及下一步只需用户完成的操作。仅依赖安装成功或仅两个进程健康，都不代表部署完成。

## 完成报告

最终向用户简洁报告：

- 操作系统和已安装前置工具的版本；
- 启动器命令及使用的端口覆盖值；
- Agent Runtime、API 和 Web 的健康状态；
- 本机 Web URL；
- 是否已打开浏览器；
- 是否仍有需要用户完成的操作。

只有三个进程全部通过检查，并且 Web URL 可以访问，部署才算完成。
