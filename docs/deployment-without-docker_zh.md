[English](deployment-without-docker.md)

# 不使用 Docker 的原生部署

本教程让 AdCraft 直接在本机运行，不使用 Docker、WSL 或容器。它只监听本机地址，适合在自己的 Windows 或 Linux 电脑上使用。

不要同时运行 Docker 启动器和原生启动器；它们会共用 apps/api/.env、apps/web/.env 和 runtime-data/。

## 先认识两个目录和两个终端

- AdCraft 根目录：同时包含 apps 和 scripts 两个文件夹的目录。
- Linux：下文命令在系统的终端中执行。
- Windows：安装工具时使用“以管理员身份运行”的 PowerShell；启动 AdCraft 时使用普通 PowerShell。
- 所有安装命令会下载软件，请保持网络连接。Linux 出现 sudo 密码提示时输入本机登录密码；任何时候都不要把 API 密钥输入终端。

## 第 1 步：安装一次系统工具

只执行与自己系统对应的一节。安装完成后，按该节最后的“检查”命令确认全部工具可用。

### Windows 10 / Windows 11（64 位）

1. 在开始菜单搜索 PowerShell，右键选择“以管理员身份运行”。
2. 将下面整块命令复制进去并按 Enter。安装过程中会显示下载进度，请保持窗口打开。

    winget install --exact --id astral-sh.uv --accept-package-agreements --accept-source-agreements
    $nodeVersion = '22.23.1'
    $nodeArchitecture = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'x64' }
    $nodeInstaller = Join-Path $env:windir "Temp\node-v$nodeVersion-$nodeArchitecture.msi"
    Invoke-WebRequest -Uri "https://nodejs.org/dist/v$nodeVersion/node-v$nodeVersion-$nodeArchitecture.msi" -OutFile $nodeInstaller
    Start-Process msiexec.exe -Wait -ArgumentList "/i $nodeInstaller /passive /norestart"
    winget install --exact --id Gyan.FFmpeg --version 7.1 --accept-package-agreements --accept-source-agreements

3. 完成后关闭所有 PowerShell 窗口，再打开一个普通 PowerShell。复制下面整块命令检查：

    uv --version
    node --version
    npm --version
    ffmpeg -version
    ffprobe -version
    ffmpeg -hide_banner -encoders | Select-String -Pattern 'libx264|libopenh264'
    ffmpeg -hide_banner -encoders | Select-String -Pattern 'aac'

如果任意命令提示找不到命令，重新打开一次 PowerShell 后再检查。Node 版本必须以 v22 开头；FFmpeg 和 ffprobe 必须是 6.1–7.x，且最后两条命令都要显示结果。

### Ubuntu 22.04

Ubuntu 22.04 自带的 FFmpeg 版本过低，因此本节会编译固定的 FFmpeg 7.1.1。这一步可能需要数分钟，终端持续有输出即表示仍在工作。

1. 打开终端。
2. 将下面整块命令复制进去并按 Enter：

    sudo apt update
    sudo apt install -y ca-certificates curl gnupg build-essential pkg-config nasm yasm libx264-dev xz-utils
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt install -y nodejs
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    cd /tmp
    rm -rf ffmpeg-7.1.1 ffmpeg-7.1.1.tar.xz
    curl -fLO https://ffmpeg.org/releases/ffmpeg-7.1.1.tar.xz
    tar -xJf ffmpeg-7.1.1.tar.xz
    cd ffmpeg-7.1.1
    ./configure --prefix=/usr/local --enable-gpl --enable-libx264
    make -j"$(nproc)"
    sudo make install
    sudo ldconfig
    hash -r

3. 在同一个终端复制下面整块命令检查：

    uv --version
    node --version
    npm --version
    ffmpeg -version
    ffprobe -version
    ffmpeg -hide_banner -encoders | grep -E 'libx264|libopenh264'
    ffmpeg -hide_banner -encoders | grep -E '^[[:space:]]*[.A-Z]{2,7}[[:space:]]+aac([[:space:]]|$)'

### Ubuntu 24.04 及更高版本，或 Debian 13 及更高版本

1. 打开终端。
2. 将下面整块命令复制进去并按 Enter：

    sudo apt update
    sudo apt install -y ca-certificates curl gnupg ffmpeg
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt install -y nodejs
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"

3. 在同一个终端复制下面整块命令检查：

    uv --version
    node --version
    npm --version
    ffmpeg -version
    ffprobe -version
    ffmpeg -hide_banner -encoders | grep -E 'libx264|libopenh264'
    ffmpeg -hide_banner -encoders | grep -E '^[[:space:]]*[.A-Z]{2,7}[[:space:]]+aac([[:space:]]|$)'

Linux 检查规则与 Windows 相同：Node 必须是 v22；FFmpeg 和 ffprobe 必须是 6.1–7.x；两条编码器检查都必须显示结果。若 Ubuntu 24.04 或 Debian 13 的系统仓库实际给出范围外的 FFmpeg，请改用上面的 Ubuntu 22.04 编译步骤。

## 第 2 步：一键启动 AdCraft

首次启动会自动创建缺失的 .env、安装后端和前端依赖、启动两个服务，并在终端打印本地网页地址。不要关闭终端，直到看到“原生部署成功”。

启动过程会显示 [1/6] 到 [6/6] 的阶段。第 3/6、4/6 阶段会显示依赖下载和安装输出；第 5/6、6/6 阶段会持续显示转圈和已等待秒数。看到这些内容表示程序仍在工作。

### Linux

在终端中先进入 AdCraft 根目录。若项目位于自己的主目录，直接复制：

    cd "$HOME/AdCraft"
    bash scripts/deploy-native-linux.sh

如果项目不在 $HOME/AdCraft，先把第一行改成实际位置；第二行不需要改。例如项目在 /home/alice/Downloads/AdCraft-main 时：

    cd /home/alice/Downloads/AdCraft-main
    bash scripts/deploy-native-linux.sh

### Windows 10 / Windows 11

打开普通 PowerShell，将第一行的路径改成 AdCraft 根目录的实际位置后，再一起执行：

    Set-Location 'D:\AdCraft\AdCraft-main'
    .\scripts\deploy-native-windows.cmd

也可以双击 scripts 文件夹中的 deploy-native-windows.cmd。使用 PowerShell 启动时，窗口会在成功或失败后保留，便于查看进度与报错。

默认地址：

    API:  http://127.0.0.1:8000
    网页: http://127.0.0.1:5189

成功后浏览器通常会自动打开网页；若没有自动打开，请复制“网页”地址到同一台计算机的浏览器。进入网页后，在 API Space 中填写服务商 API 密钥。

## 端口被占用时

先停止旧的 AdCraft 原生服务；如果端口仍被其他程序占用，再使用下面的命令。必须在 AdCraft 根目录执行。

Linux：

    ADCRAFT_NATIVE_API_PORT=8001 ADCRAFT_NATIVE_WEB_PORT=5190 bash scripts/deploy-native-linux.sh

Windows PowerShell：

    $env:ADCRAFT_NATIVE_API_PORT = '8001'
    $env:ADCRAFT_NATIVE_WEB_PORT = '5190'
    .\scripts\deploy-native-windows.cmd

启动器会记住本次端口，后面的状态、日志和停止命令会自动使用它们。它也会把凭据管理接口限制在这次选择的本机网页端口，因此换端口后仍可在 API Space 中保存和测试 API 密钥。

### AdCraft 已运行后更换端口

前端启动时会读取后端 API 端口；后端启动时会读取可信网页来源。因此不要只修改一个正在运行的服务的端口。请设置两个所需端口变量后重新运行原生启动器；它只会停止自己启动的原生 API 和网页进程，再启动端口互相匹配的一对服务。它会保留 .env、runtime-data、.venv、node_modules 和已保存的 API 密钥。

## 一键启动失败时：手动分步启动

以下步骤只在一键启动报错且需要定位问题时使用。不要在已经成功运行一键启动器的同时再执行这些命令。以下手动命令使用默认端口 8000 和 5189；需要更换端口时，请优先使用上面的一键启动命令，它会同时同步前端代理和凭据接口的本机来源限制。

### 1. 在 AdCraft 根目录创建本地配置

Linux：

    if [ ! -f apps/api/.env ]; then cp apps/api/.env.example apps/api/.env; chmod 600 apps/api/.env; fi
    if [ ! -f apps/web/.env ]; then cp apps/web/.env.example apps/web/.env; chmod 600 apps/web/.env; fi
    mkdir -p runtime-data/api
    chmod 700 runtime-data runtime-data/api

Windows PowerShell：

    if (-not (Test-Path apps/api/.env)) { Copy-Item apps/api/.env.example apps/api/.env }
    if (-not (Test-Path apps/web/.env)) { Copy-Item apps/web/.env.example apps/web/.env }
    New-Item -ItemType Directory -Force runtime-data/api | Out-Null

已有 .env 可能保存了 API 密钥，不要覆盖它。

### 2. 在第一个终端启动后端

Linux：在 AdCraft 根目录执行：

    cd apps/api
    uv sync
    MEDIA_DATA_DIR="$(cd ../.. && pwd)/runtime-data/api" FFMPEG_PATH="$(command -v ffmpeg)" FFPROBE_PATH="$(command -v ffprobe)" uv run uvicorn main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app

Windows PowerShell：在 AdCraft 根目录执行：

    Set-Location apps/api
    uv sync
    $env:MEDIA_DATA_DIR = Join-Path (Resolve-Path ../..) 'runtime-data\api'
    $env:FFMPEG_PATH = (Get-Command ffmpeg).Source
    $env:FFPROBE_PATH = (Get-Command ffprobe).Source
    uv run uvicorn main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app

保持第一个终端运行。浏览器打开 http://127.0.0.1:8000/api/v1/health；能看到正常响应后再继续。

### 3. 在第二个终端启动网页

重新打开一个终端，并先回到 AdCraft 根目录。

Linux：

    cd "$HOME/AdCraft/apps/web"
    npm ci --progress=true
    BACKEND_ORIGIN=http://127.0.0.1:8000 npm run dev -- --host 127.0.0.1 --port 5189

如果项目不在 $HOME/AdCraft，把第一行改成实际目录。

Windows PowerShell：

    Set-Location 'D:\AdCraft\AdCraft-main\apps\web'
    npm ci --progress=true
    $env:BACKEND_ORIGIN = 'http://127.0.0.1:8000'
    npm run dev -- --host 127.0.0.1 --port 5189

Windows 的第一行同样需要改成实际目录。看到本地地址后，用浏览器打开 http://127.0.0.1:5189。

## 日常命令

必须在 AdCraft 根目录执行。

| 操作 | Linux | Windows PowerShell |
| --- | --- | --- |
| 查看状态 | bash scripts/status-native-linux.sh | .\scripts\status-native-windows.ps1 |
| 查看近期日志 | bash scripts/logs-native-linux.sh | .\scripts\logs-native-windows.ps1 |
| 停止 | bash scripts/stop-native-linux.sh | .\scripts\stop-native-windows.ps1 |
| 更新代码后重新安装依赖并启动 | bash scripts/deploy-native-linux.sh | .\scripts\deploy-native-windows.cmd |

启动器只会停止自己启动的原生进程；会保留 .env、runtime-data、.venv、node_modules 和日志。除非明确要删除生成的媒体与本地数据库，否则不要删除 runtime-data。

## 常见问题

| 现象 | 处理方式 |
| --- | --- |
| 找不到 uv、node、npm、ffmpeg 或 ffprobe。 | 关闭并重新打开终端，然后再执行检查命令。仍找不到时，重新执行对应系统的安装步骤。 |
| 安装阶段没有新的输出。 | 先等待；软件包下载取决于网络。若长时间无网络活动，检查网络、软件源或代理，然后重新运行启动器。 |
| FFmpeg 版本或编码器被拒绝。 | 不要使用 4.x、5.x 或 8.x。Ubuntu 22.04 请执行本教程的 FFmpeg 7.1.1 编译步骤；其他系统请确认检查命令的输出。 |
| uv sync 或 npm ci 失败。 | 检查网络是否能访问 Python 包索引或 npm registry；不要删除 uv.lock 或 package-lock.json。 |
| 端口被占用。 | 使用上面的两个 ADCRAFT_NATIVE 端口变量，或先停止占用端口的程序。 |
| API 或网页启动后退出。 | 执行对应系统的“查看近期日志”命令。分享日志前必须删除 API 密钥和 .env 内容。 |

原生部署会把前后端绑定到 127.0.0.1。除非另行设计认证、TLS、防火墙与数据保护，否则不要把开发服务器暴露到局域网或互联网。
