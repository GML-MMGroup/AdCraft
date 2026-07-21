[简体中文](deployment-without-docker_zh.md)

# Native Deployment Without Docker

This guide runs AdCraft directly on one computer without Docker, WSL, or containers. Both services listen only on that computer, so this path is for local Windows or Linux use.

Do not run the Docker launcher and the native launcher at the same time. They share apps/api/.env, apps/web/.env, and runtime-data/.

## Two folders and two terminals

- The AdCraft project root is the folder that contains both apps and scripts.
- On Linux, run the commands below in the system terminal.
- On Windows, use PowerShell opened as Administrator to install tools, then use normal PowerShell to start AdCraft.
- Every installation command downloads software, so keep an internet connection. Enter only your local Linux password at a sudo prompt. Never enter an API key in a terminal.

## Step 1: Install the system tools once

Run only the section that matches your system. After it finishes, run that section's check commands and make sure every tool is available.

### Windows 10 / Windows 11 (64-bit)

1. Open the Start menu, search for PowerShell, right-click it, and choose Run as administrator.
2. Copy the entire block below into that window and press Enter. Keep the window open while it shows download progress.

    winget install --exact --id astral-sh.uv --accept-package-agreements --accept-source-agreements
    $nodeVersion = '22.23.1'
    $nodeArchitecture = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'x64' }
    $nodeInstaller = Join-Path $env:windir "Temp\node-v$nodeVersion-$nodeArchitecture.msi"
    Invoke-WebRequest -Uri "https://nodejs.org/dist/v$nodeVersion/node-v$nodeVersion-$nodeArchitecture.msi" -OutFile $nodeInstaller
    Start-Process msiexec.exe -Wait -ArgumentList "/i $nodeInstaller /passive /norestart"
    winget install --exact --id Gyan.FFmpeg --version 7.1 --accept-package-agreements --accept-source-agreements

3. Close every PowerShell window. Open a new normal PowerShell window, copy the entire block below, and press Enter.

    uv --version
    node --version
    npm --version
    ffmpeg -version
    ffprobe -version
    ffmpeg -hide_banner -encoders | Select-String -Pattern 'libx264|libopenh264'
    ffmpeg -hide_banner -encoders | Select-String -Pattern 'aac'

If any command is not found, reopen PowerShell once more and run the check again. Node must begin with v22. FFmpeg and ffprobe must be version 6.1–7.x, and both encoder commands must display a result.

### Ubuntu 22.04

Ubuntu 22.04 ships an FFmpeg version that is too old. This section builds the fixed FFmpeg 7.1.1 release. It can take several minutes; continuous terminal output means that it is still working.

1. Open Terminal.
2. Copy the entire block below and press Enter.

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

3. In the same terminal, copy the entire block below and press Enter.

    uv --version
    node --version
    npm --version
    ffmpeg -version
    ffprobe -version
    ffmpeg -hide_banner -encoders | grep -E 'libx264|libopenh264'
    ffmpeg -hide_banner -encoders | grep -E '^[[:space:]]*[.A-Z]{2,7}[[:space:]]+aac([[:space:]]|$)'

### Ubuntu 24.04 or later, or Debian 13 or later

1. Open Terminal.
2. Copy the entire block below and press Enter.

    sudo apt update
    sudo apt install -y ca-certificates curl gnupg ffmpeg
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt install -y nodejs
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"

3. In the same terminal, copy the entire block below and press Enter.

    uv --version
    node --version
    npm --version
    ffmpeg -version
    ffprobe -version
    ffmpeg -hide_banner -encoders | grep -E 'libx264|libopenh264'
    ffmpeg -hide_banner -encoders | grep -E '^[[:space:]]*[.A-Z]{2,7}[[:space:]]+aac([[:space:]]|$)'

The Linux checks use the same rules as Windows: Node must be v22, FFmpeg and ffprobe must be 6.1–7.x, and both encoder checks must show a result. If Ubuntu 24.04 or Debian 13 actually installs an out-of-range FFmpeg version, use the Ubuntu 22.04 build steps instead.

## Step 2: Start AdCraft with one command

The first start creates missing .env files, installs backend and frontend dependencies, starts both services, and prints the local web address. Do not close the terminal until it says Native deployment completed.

The launcher displays stages [1/6] through [6/6]. Stages 3/6 and 4/6 show dependency download and installation output. Stages 5/6 and 6/6 display a continuous spinner with elapsed seconds while each service starts. These messages mean the program is still working.

### Linux

Open Terminal and enter the AdCraft project root. If the project is in your home folder, copy:

    cd "$HOME/AdCraft"
    bash scripts/deploy-native-linux.sh

If the project is elsewhere, change only the first line. For example, a project at /home/alice/Downloads/AdCraft-main uses:

    cd /home/alice/Downloads/AdCraft-main
    bash scripts/deploy-native-linux.sh

### Windows 10 / Windows 11

Open normal PowerShell. Change the first line below to the actual AdCraft project-root path, then run both lines:

    Set-Location 'D:\AdCraft\AdCraft-main'
    .\scripts\deploy-native-windows.cmd

You can also double-click scripts/deploy-native-windows.cmd. Starting it from PowerShell keeps the window open after success or failure so you can read progress and errors.

Default addresses:

    API: http://127.0.0.1:8000
    Web: http://127.0.0.1:5189

The browser normally opens after a successful start. If it does not, open the Web address in a browser on the same computer. In the web page, enter provider API keys in API Space.

## If a port is already in use

First stop any previous AdCraft native service. If another program still owns the port, use the commands below from the AdCraft project root.

Linux:

    ADCRAFT_NATIVE_API_PORT=8001 ADCRAFT_NATIVE_WEB_PORT=5190 bash scripts/deploy-native-linux.sh

Windows PowerShell:

    $env:ADCRAFT_NATIVE_API_PORT = '8001'
    $env:ADCRAFT_NATIVE_WEB_PORT = '5190'
    .\scripts\deploy-native-windows.cmd

The launcher saves these ports and automatically uses them for later status, logs, and stop commands. It also restricts credential management to the selected local Web port, so API Space can still save and test API keys after a port change.

### Change a port after AdCraft is already running

The frontend proxy reads the API port when the frontend starts. The backend reads the trusted Web origins when the backend starts. Therefore, do not change only one running service's port. Set both desired port variables and run the native launcher again; it stops only the native API and Web processes it started, then starts the matching pair. It keeps .env, runtime-data, .venv, node_modules, and saved API keys.

## If the one-command launch fails: manual startup

Use the following only to find a failure in the one-command launcher. Do not run these commands while a successful launcher is already running. These manual commands use the default ports 8000 and 5189. When you need different ports, use the one-command launcher above; it synchronizes both the frontend proxy and the credential interface's trusted local origins.

### 1. Create local configuration in the AdCraft project root

Linux:

    if [ ! -f apps/api/.env ]; then cp apps/api/.env.example apps/api/.env; chmod 600 apps/api/.env; fi
    if [ ! -f apps/web/.env ]; then cp apps/web/.env.example apps/web/.env; chmod 600 apps/web/.env; fi
    mkdir -p runtime-data/api
    chmod 700 runtime-data runtime-data/api

Windows PowerShell:

    if (-not (Test-Path apps/api/.env)) { Copy-Item apps/api/.env.example apps/api/.env }
    if (-not (Test-Path apps/web/.env)) { Copy-Item apps/web/.env.example apps/web/.env }
    New-Item -ItemType Directory -Force runtime-data/api | Out-Null

Do not overwrite an existing .env. It can contain API keys saved by AdCraft.

### 2. Start the backend in the first terminal

Linux: from the AdCraft project root, run:

    cd apps/api
    uv sync
    MEDIA_DATA_DIR="$(cd ../.. && pwd)/runtime-data/api" FFMPEG_PATH="$(command -v ffmpeg)" FFPROBE_PATH="$(command -v ffprobe)" uv run uvicorn main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app

Windows PowerShell: from the AdCraft project root, run:

    Set-Location apps/api
    uv sync
    $env:MEDIA_DATA_DIR = Join-Path (Resolve-Path ../..) 'runtime-data\api'
    $env:FFMPEG_PATH = (Get-Command ffmpeg).Source
    $env:FFPROBE_PATH = (Get-Command ffprobe).Source
    uv run uvicorn main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app

Keep the first terminal open. Open http://127.0.0.1:8000/api/v1/health in a browser and continue only after it gives a normal response.

### 3. Start the web UI in the second terminal

Open a second terminal and return to the AdCraft project root first.

Linux:

    cd "$HOME/AdCraft/apps/web"
    npm ci --progress=true
    BACKEND_ORIGIN=http://127.0.0.1:8000 npm run dev -- --host 127.0.0.1 --port 5189

Change the first line if the project is not in $HOME/AdCraft.

Windows PowerShell:

    Set-Location 'D:\AdCraft\AdCraft-main\apps\web'
    npm ci --progress=true
    $env:BACKEND_ORIGIN = 'http://127.0.0.1:8000'
    npm run dev -- --host 127.0.0.1 --port 5189

Change the first Windows line to the actual location. When it prints a local address, open http://127.0.0.1:5189 in a browser.

## Everyday commands

Run these from the AdCraft project root.

| Task | Linux | Windows PowerShell |
| --- | --- | --- |
| Status | bash scripts/status-native-linux.sh | .\scripts\status-native-windows.ps1 |
| Recent logs | bash scripts/logs-native-linux.sh | .\scripts\logs-native-windows.ps1 |
| Stop | bash scripts/stop-native-linux.sh | .\scripts\stop-native-windows.ps1 |
| Reinstall dependencies and restart after replacing code | bash scripts/deploy-native-linux.sh | .\scripts\deploy-native-windows.cmd |

The launchers stop only native processes that they started. They retain .env, runtime-data, .venv, node_modules, and logs. Do not delete runtime-data unless you intentionally want to remove generated media and the local database.

## Common problems

| Symptom | What to do |
| --- | --- |
| uv, node, npm, ffmpeg, or ffprobe is missing. | Close and reopen the terminal, then run the check commands again. If it is still missing, repeat the matching system-install section. |
| An install stage has no new output. | Wait first; package downloads depend on the network. If there is no network activity for a long time, check the network, package source, or proxy, then rerun the launcher. |
| FFmpeg version or encoder is rejected. | Do not use 4.x, 5.x, or 8.x. On Ubuntu 22.04, follow this guide's FFmpeg 7.1.1 build steps; on other systems, check the command output. |
| uv sync or npm ci fails. | Check that the network can reach the Python package index or npm registry. Do not delete uv.lock or package-lock.json. |
| A port is in use. | Use the two ADCRAFT_NATIVE port variables above, or stop the process that owns the port. |
| The API or web UI exits after starting. | Run the matching Recent logs command. Remove API keys and .env contents before sharing a log. |

Native deployment binds both services to 127.0.0.1. Do not expose the development servers to a LAN or the internet without separately designing authentication, TLS, firewall rules, and data protection.
