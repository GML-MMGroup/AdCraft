[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot 'windows-common.ps1')

function Test-AdCraftAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-AdCraftWindowsSupport {
    $os = Get-CimInstance Win32_OperatingSystem
    if (-not [Environment]::Is64BitOperatingSystem) { Stop-AdCraft '只支持 64 位 Windows。' }
    $build = [int]$os.BuildNumber
    if ($os.Caption -match 'Windows 11') {
        if ($build -lt 22631) { Stop-AdCraft '需要 Windows 11 23H2 (build 22631) 或更高版本。' }
    } elseif ($os.Caption -match 'Windows 10') {
        if ($build -lt 19045) { Stop-AdCraft '需要 Windows 10 22H2 (build 19045) 或更高版本。' }
    } else {
        Stop-AdCraft "不支持的 Windows 版本：$($os.Caption)"
    }
}

function Exit-AdCraftForWslReboot {
    Write-AdCraftInfo 'WSL 2 已启用或正在安装。请按 Windows 提示重启后重新运行 scripts\\deploy-windows.cmd。'
    exit 0
}

function Ensure-AdCraftWsl2 {
    $wslStatus = & wsl.exe --status 2>&1
    if ($LASTEXITCODE -ne 0) {
        & wsl.exe --install --no-distribution
        if ($LASTEXITCODE -ne 0) {
            Stop-AdCraft 'WSL 2 安装失败。请检查 Windows 功能和网络连接后重试。'
        }
        Exit-AdCraftForWslReboot
    }

    $wslStatusText = ($wslStatus | Out-String)
    if ($wslStatusText -notmatch '(?im)^\s*(?:Default Version|默认版本)\s*[:：]\s*2\s*$') {
        & wsl.exe --set-default-version 2
        if ($LASTEXITCODE -ne 0) {
            Stop-AdCraft '无法将 WSL 默认版本设置为 2。请检查 WSL 安装状态后重试。'
        }
    }
}

function Ensure-AdCraftDockerDesktop {
    if (-not (Test-AdCraftDockerReady)) {
        if ($null -eq (Get-Command docker -ErrorAction SilentlyContinue)) {
            if ($null -eq (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
                Stop-AdCraft '未找到 winget。请从 Microsoft Store 安装 App Installer，然后重新运行本脚本。'
            }

            & winget.exe install --exact --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -ne 0) { Stop-AdCraft 'Docker Desktop 安装失败。' }
        }

        $dockerDesktopPath = $null
        foreach ($candidate in @(
            'C:\Program Files\Docker\Docker\Docker Desktop.exe',
            (Join-Path $env:LOCALAPPDATA 'Programs\Docker\Docker\Docker Desktop.exe')
        )) {
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                $dockerDesktopPath = $candidate
                break
            }
        }
        if ($null -eq $dockerDesktopPath) {
            Stop-AdCraft '未找到 Docker Desktop.exe。'
        }

        if (-not (Test-AdCraftDockerReady)) {
            Start-Process -FilePath $dockerDesktopPath
            Wait-AdCraftDockerReady
        }
    }

    $osType = (& docker info --format '{{.OSType}}').Trim()
    if ($LASTEXITCODE -ne 0 -or $osType -ne 'linux') {
        Stop-AdCraft 'Docker Desktop 必须切换到 Linux containers 模式。'
    }
}

try {
    Test-AdCraftProject
    Assert-AdCraftWindowsSupport
    if (-not (Test-AdCraftAdministrator)) {
        Stop-AdCraft '请右键以管理员身份运行 scripts\\deploy-windows.cmd。'
    }
    Ensure-AdCraftWsl2
    Ensure-AdCraftDockerDesktop
    Initialize-AdCraftEnvFile 'apps/api/.env'
    Initialize-AdCraftEnvFile 'apps/web/.env'
    $port = Select-AdCraftPort
    Write-AdCraftState $port
    Invoke-AdCraftCompose @('config','--quiet')
    Write-AdCraftInfo '构建 AdCraft 镜像……'
    Invoke-AdCraftCompose @('build')
    Write-AdCraftInfo '启动 AdCraft……'
    Invoke-AdCraftCompose @('up','-d','--remove-orphans')
    Write-AdCraftInfo '等待 Web/API 健康，最长 120 秒……'
    Wait-AdCraftServices
    $url = Get-AdCraftUrl
    Write-AdCraftInfo "部署成功：$url"
    Start-AdCraftBrowser
} catch {
    Write-Error $_.Exception.Message
    if (Test-AdCraftDockerReady) { try { Show-AdCraftLogs } catch {} }
    exit 1
}
