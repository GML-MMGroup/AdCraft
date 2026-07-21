Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:NativeProjectRoot = Split-Path -Parent $PSScriptRoot
$script:NativeApiDirectory = Join-Path $script:NativeProjectRoot 'apps\api'
$script:NativeWebDirectory = Join-Path $script:NativeProjectRoot 'apps\web'
$script:NativeRuntimeDirectory = Join-Path $script:NativeProjectRoot 'runtime-data\native'
$script:NativeApiDataDirectory = Join-Path $script:NativeProjectRoot 'runtime-data\api'
$script:NativeStateFile = Join-Path $script:NativeRuntimeDirectory 'native.env'
$script:NativeApiPidFile = Join-Path $script:NativeRuntimeDirectory 'api.pid'
$script:NativeWebPidFile = Join-Path $script:NativeRuntimeDirectory 'web.pid'
$script:NativeApiOutputLog = Join-Path $script:NativeRuntimeDirectory 'api.out.log'
$script:NativeApiErrorLog = Join-Path $script:NativeRuntimeDirectory 'api.err.log'
$script:NativeWebOutputLog = Join-Path $script:NativeRuntimeDirectory 'web.out.log'
$script:NativeWebErrorLog = Join-Path $script:NativeRuntimeDirectory 'web.err.log'

function Write-AdCraftNativeInfo([string]$Message) {
    Write-Host "[AdCraft] $Message"
}

function Write-AdCraftNativeStage([int]$Current, [int]$Total, [string]$Message) {
    Write-Host ''
    Write-Host "[AdCraft] [$Current/$Total] $Message"
}

function Stop-AdCraftNative([string]$Message) {
    throw "[AdCraft] ERROR: $Message"
}

function Test-AdCraftNativeProject {
    foreach ($path in @(
        (Join-Path $script:NativeApiDirectory 'pyproject.toml'),
        (Join-Path $script:NativeApiDirectory '.env.example'),
        (Join-Path $script:NativeWebDirectory 'package.json'),
        (Join-Path $script:NativeWebDirectory 'package-lock.json'),
        (Join-Path $script:NativeWebDirectory '.env.example')
    )) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            Stop-AdCraftNative "缺少必需文件：$path"
        }
    }
}

function Initialize-AdCraftNativeEnvFile([string]$RelativePath) {
    $target = Join-Path $script:NativeProjectRoot $RelativePath
    $example = "$target.example"

    if (Test-Path -LiteralPath $target) {
        $targetItem = Get-Item -LiteralPath $target -Force
        if (-not ($targetItem -is [System.IO.FileInfo]) -or (($targetItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)) {
            Stop-AdCraftNative "$RelativePath 已存在但不是普通文件。"
        }
        return
    }
    if (-not (Test-Path -LiteralPath $example -PathType Leaf)) {
        Stop-AdCraftNative "缺少 dotenv 示例文件：$example"
    }
    [System.IO.File]::Copy($example, $target, $false)
    Write-AdCraftNativeInfo "已从示例创建 $RelativePath。"
}

function Get-AdCraftNativeCommandPath([string]$Name, [string]$Hint) {
    $command = Get-Command -Name $Name -CommandType Application -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        Stop-AdCraftNative "未找到 $Name。$Hint"
    }
    return [string]$command.Source
}

function Get-AdCraftNativeToolVersion([string]$ToolPath, [string]$ToolName) {
    $firstLine = @(& $ToolPath -version 2>&1 | Select-Object -First 1) -join ''
    $match = [regex]::Match($firstLine, "^$([regex]::Escape($ToolName)) version (\d+(?:\.\d+)+)")
    if (-not $match.Success) {
        Stop-AdCraftNative "无法识别 $ToolName 版本：$firstLine"
    }
    return $match.Groups[1].Value
}

function Assert-AdCraftNativeNode([string]$NodePath, [string]$NpmPath) {
    $nodeVersion = (@(& $NodePath --version 2>&1 | Select-Object -First 1) -join '').Trim()
    $match = [regex]::Match($nodeVersion, '^v(\d+)\.\d+\.\d+$')
    if (-not $match.Success) {
        Stop-AdCraftNative "无法识别 Node.js 版本：$nodeVersion"
    }
    if ([int]$match.Groups[1].Value -ne 22) {
        Stop-AdCraftNative "需要 Node.js 22，当前为 $nodeVersion。"
    }
    Write-AdCraftNativeInfo "已验证 Node.js：$nodeVersion。"
}

function Test-AdCraftNativeSupportedFfmpegVersion([string]$Version) {
    $parsed = [Version]$Version
    return (($parsed.Major -eq 6 -and $parsed.Minor -ge 1) -or $parsed.Major -eq 7)
}

function Assert-AdCraftNativeFfmpeg {
    $ffmpegPath = Get-AdCraftNativeCommandPath 'ffmpeg' '请按原生部署教程安装兼容的 FFmpeg 6.1–7.x，并重新打开终端。'
    $ffprobePath = Get-AdCraftNativeCommandPath 'ffprobe' '请安装与 FFmpeg 同一发行版中的 ffprobe，并重新打开终端。'
    $ffmpegVersion = Get-AdCraftNativeToolVersion $ffmpegPath 'ffmpeg'
    $ffprobeVersion = Get-AdCraftNativeToolVersion $ffprobePath 'ffprobe'
    if (-not (Test-AdCraftNativeSupportedFfmpegVersion $ffmpegVersion)) {
        Stop-AdCraftNative "FFmpeg 版本必须在 >=6.1,<8，当前为 $ffmpegVersion。"
    }
    if (-not (Test-AdCraftNativeSupportedFfmpegVersion $ffprobeVersion)) {
        Stop-AdCraftNative "ffprobe 版本必须在 >=6.1,<8，当前为 $ffprobeVersion。"
    }
    if (($ffmpegVersion -split '\.')[0] -ne ($ffprobeVersion -split '\.')[0]) {
        Stop-AdCraftNative "ffmpeg 和 ffprobe 主版本不一致：$ffmpegVersion / $ffprobeVersion。"
    }

    $encoders = @(& $ffmpegPath -hide_banner -encoders 2>$null) -join "`n"
    if ($encoders -notmatch '(?m)^\s*[.A-Z]{2,7}\s+(libx264|libopenh264)(?:\s|$)') {
        Stop-AdCraftNative 'FFmpeg 缺少允许的 H.264 编码器（libx264 或 libopenh264）。'
    }
    if ($encoders -notmatch '(?m)^\s*[.A-Z]{2,7}\s+aac(?:\s|$)') {
        Stop-AdCraftNative 'FFmpeg 缺少 AAC 编码器。'
    }
    return [pscustomobject]@{
        FfmpegPath = $ffmpegPath
        FfprobePath = $ffprobePath
        FfmpegVersion = $ffmpegVersion
        FfprobeVersion = $ffprobeVersion
    }
}

function Initialize-AdCraftNativeRuntime {
    foreach ($directory in @($script:NativeRuntimeDirectory, $script:NativeApiDataDirectory)) {
        if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
            [System.IO.Directory]::CreateDirectory($directory) > $null
        }
    }
}

function Test-AdCraftNativePort([int]$Port) {
    return $Port -ge 1024 -and $Port -le 65535
}

function Test-AdCraftNativePortFree([int]$Port) {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    try {
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        $listener.Stop()
    }
}

function Write-AdCraftNativeState([int]$ApiPort, [int]$WebPort) {
    if (-not (Test-AdCraftNativePort $ApiPort) -or -not (Test-AdCraftNativePort $WebPort) -or $ApiPort -eq $WebPort) {
        Stop-AdCraftNative '原生 API/Web 端口无效。'
    }
    $temporaryPath = Join-Path $script:NativeRuntimeDirectory ("native.env.{0}.tmp" -f [Guid]::NewGuid().ToString('N'))
    $content = "ADCRAFT_NATIVE_API_PORT=$ApiPort`nADCRAFT_NATIVE_WEB_PORT=$WebPort`n"
    try {
        [System.IO.File]::WriteAllText($temporaryPath, $content, [System.Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporaryPath -Destination $script:NativeStateFile -Force
    } finally {
        if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

function Read-AdCraftNativeState {
    if (-not (Test-Path -LiteralPath $script:NativeStateFile -PathType Leaf)) {
        Stop-AdCraftNative '缺少 runtime-data/native/native.env，请先运行 scripts\deploy-native-windows.cmd。'
    }
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $script:NativeStateFile) {
        if ($line -notmatch '^(ADCRAFT_NATIVE_API_PORT|ADCRAFT_NATIVE_WEB_PORT)=([0-9]+)$') {
            Stop-AdCraftNative 'native.env 格式无效。'
        }
        $key, $value = $Matches[1], [int]$Matches[2]
        if ($values.ContainsKey($key)) { Stop-AdCraftNative "native.env 包含重复字段：$key。" }
        $values[$key] = $value
    }
    $requiredKeys = @('ADCRAFT_NATIVE_API_PORT', 'ADCRAFT_NATIVE_WEB_PORT')
    $missingKeys = @($requiredKeys | Where-Object { -not $values.ContainsKey($_) })
    if ($missingKeys.Count -gt 0 -or $values.Count -ne $requiredKeys.Count) {
        Stop-AdCraftNative 'native.env 缺少字段。'
    }
    if (-not (Test-AdCraftNativePort $values['ADCRAFT_NATIVE_API_PORT']) -or -not (Test-AdCraftNativePort $values['ADCRAFT_NATIVE_WEB_PORT'])) {
        Stop-AdCraftNative 'native.env 中的端口无效。'
    }
    return [pscustomobject]@{
        ApiPort = $values['ADCRAFT_NATIVE_API_PORT']
        WebPort = $values['ADCRAFT_NATIVE_WEB_PORT']
    }
}

function Get-AdCraftNativePid([string]$PidFile) {
    if (-not (Test-Path -LiteralPath $PidFile -PathType Leaf)) { return $null }
    $rawValue = ([System.IO.File]::ReadAllText($PidFile)).Trim()
    $parsed = 0
    if (-not [int]::TryParse($rawValue, [ref]$parsed)) {
        Remove-Item -LiteralPath $PidFile -Force
        return $null
    }
    try {
        $null = Get-Process -Id $parsed -ErrorAction Stop
        return $parsed
    } catch {
        Remove-Item -LiteralPath $PidFile -Force
        return $null
    }
}

function Stop-AdCraftNativeProcess([string]$Label, [string]$PidFile) {
    $processId = Get-AdCraftNativePid $PidFile
    if ($null -eq $processId) { return }
    Write-AdCraftNativeInfo "停止原生 $Label 进程（PID $processId）……"
    & taskkill.exe /PID $processId /T /F *> $null
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

function Test-AdCraftNativeUrl([string]$Url) {
    try {
        $null = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

function Wait-AdCraftNativeUrl([string]$Label, [string]$Url) {
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $frames = @('|', '/', '-', '\\')
    $frameIndex = 0
    while ($stopwatch.Elapsed.TotalSeconds -lt 90) {
        if (Test-AdCraftNativeUrl $Url) {
            Write-Host "`r[AdCraft] [$Label] 服务已就绪。                    "
            return
        }
        $elapsed = [math]::Floor($stopwatch.Elapsed.TotalSeconds)
        Write-Host -NoNewline ("`r[AdCraft] [{0}] 等待服务启动 {1} {2:D2}s/90s" -f $Label, $frames[$frameIndex], $elapsed)
        $frameIndex = ($frameIndex + 1) % $frames.Count
        Start-Sleep -Seconds 1
    }
    Write-Host ''
    Stop-AdCraftNative "$Label 未能在 90 秒内就绪。请运行 scripts\logs-native-windows.ps1 查看日志。"
}

function Get-AdCraftNativeApiUrl([int]$ApiPort) {
    return "http://127.0.0.1:$ApiPort/api/v1/health"
}

function Get-AdCraftNativeUrl([int]$WebPort) {
    return "http://127.0.0.1:$WebPort"
}

function Start-AdCraftNativeProcess {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [string]$OutputLog,
        [string]$ErrorLog,
        [hashtable]$Environment
    )

    $previous = @{}
    foreach ($key in $Environment.Keys) {
        $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        [Environment]::SetEnvironmentVariable($key, [string]$Environment[$key], 'Process')
    }
    try {
        return Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory -RedirectStandardOutput $OutputLog -RedirectStandardError $ErrorLog -PassThru
    } finally {
        foreach ($key in $Environment.Keys) {
            [Environment]::SetEnvironmentVariable($key, $previous[$key], 'Process')
        }
    }
}

function Show-AdCraftNativeLogs {
    $logFiles = @($script:NativeApiOutputLog, $script:NativeApiErrorLog, $script:NativeWebOutputLog, $script:NativeWebErrorLog) |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
    if ($logFiles.Count -eq 0) {
        Stop-AdCraftNative '尚无原生日志，请先运行 scripts\deploy-native-windows.cmd。'
    }
    Get-Content -LiteralPath $logFiles -Tail 100
}
