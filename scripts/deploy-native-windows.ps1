[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot 'native-windows-common.ps1')

try {
    Write-AdCraftNativeStage 1 6 '检查项目文件、系统工具和端口……'
    Test-AdCraftNativeProject
    $uvPath = Get-AdCraftNativeCommandPath 'uv' '请先按原生部署教程安装 uv。'
    $nodePath = Get-AdCraftNativeCommandPath 'node' '请先按原生部署教程安装 Node.js 22。'
    $npmPath = Get-AdCraftNativeCommandPath 'npm' '请安装与 Node.js 配套的 npm。'
    Assert-AdCraftNativeNode $nodePath $npmPath
    $toolchain = Assert-AdCraftNativeFfmpeg

    $apiPort = if ($env:ADCRAFT_NATIVE_API_PORT) { [int]$env:ADCRAFT_NATIVE_API_PORT } else { 8000 }
    $webPort = if ($env:ADCRAFT_NATIVE_WEB_PORT) { [int]$env:ADCRAFT_NATIVE_WEB_PORT } else { 5189 }
    if (-not (Test-AdCraftNativePort $apiPort) -or -not (Test-AdCraftNativePort $webPort) -or $apiPort -eq $webPort) {
        Stop-AdCraftNative 'ADCRAFT_NATIVE_API_PORT 和 ADCRAFT_NATIVE_WEB_PORT 必须是两个不同的 1024–65535 端口。'
    }
    $localSettingsAllowedOrigins = @(
        "http://127.0.0.1:$webPort",
        "http://localhost:$webPort",
        "http://[::1]:$webPort"
    ) -join ','

    Stop-AdCraftNativeProcess 'API' $script:NativeApiPidFile
    Stop-AdCraftNativeProcess 'Web' $script:NativeWebPidFile
    if (-not (Test-AdCraftNativePortFree $apiPort)) {
        Stop-AdCraftNative "API 端口 $apiPort 已被其他程序占用。可设置 ADCRAFT_NATIVE_API_PORT 后重试。"
    }
    if (-not (Test-AdCraftNativePortFree $webPort)) {
        Stop-AdCraftNative "Web 端口 $webPort 已被其他程序占用。可设置 ADCRAFT_NATIVE_WEB_PORT 后重试。"
    }

    Write-AdCraftNativeStage 2 6 '准备本地配置和运行目录……'
    Initialize-AdCraftNativeRuntime
    Initialize-AdCraftNativeEnvFile 'apps\api\.env'
    Initialize-AdCraftNativeEnvFile 'apps\web\.env'

    Write-AdCraftNativeStage 3 6 '安装后端依赖（uv sync）；uv 会显示下载和安装进度……'
    Push-Location $script:NativeApiDirectory
    try {
        & $uvPath sync
        if ($LASTEXITCODE -ne 0) { Stop-AdCraftNative 'uv sync 失败。' }
    } finally {
        Pop-Location
    }

    Write-AdCraftNativeStage 4 6 '安装前端依赖（npm ci）；npm 会显示下载和安装进度……'
    Push-Location $script:NativeWebDirectory
    try {
        & $npmPath ci --progress=true
        if ($LASTEXITCODE -ne 0) { Stop-AdCraftNative 'npm ci 失败。' }
    } finally {
        Pop-Location
    }

    Write-AdCraftNativeState $apiPort $webPort
    Write-AdCraftNativeStage 5 6 "启动 API：127.0.0.1:$apiPort……"
    $apiProcess = Start-AdCraftNativeProcess -FilePath $uvPath -ArgumentList @('run', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', "$apiPort", '--reload', '--reload-dir', 'app') -WorkingDirectory $script:NativeApiDirectory -OutputLog $script:NativeApiOutputLog -ErrorLog $script:NativeApiErrorLog -Environment @{
        MEDIA_DATA_DIR = $script:NativeApiDataDirectory
        FFMPEG_PATH = $toolchain.FfmpegPath
        FFPROBE_PATH = $toolchain.FfprobePath
        LOCAL_SETTINGS_ALLOWED_ORIGINS = $localSettingsAllowedOrigins
    }
    [System.IO.File]::WriteAllText($script:NativeApiPidFile, "$($apiProcess.Id)`n", [System.Text.UTF8Encoding]::new($false))
    Wait-AdCraftNativeUrl 'API' (Get-AdCraftNativeApiUrl $apiPort)

    Write-AdCraftNativeStage 6 6 "启动网页：127.0.0.1:$webPort……"
    $webProcess = Start-AdCraftNativeProcess -FilePath $npmPath -ArgumentList @('run', 'dev', '--', '--host', '127.0.0.1', '--port', "$webPort") -WorkingDirectory $script:NativeWebDirectory -OutputLog $script:NativeWebOutputLog -ErrorLog $script:NativeWebErrorLog -Environment @{
        BACKEND_ORIGIN = "http://127.0.0.1:$apiPort"
    }
    [System.IO.File]::WriteAllText($script:NativeWebPidFile, "$($webProcess.Id)`n", [System.Text.UTF8Encoding]::new($false))
    $url = Get-AdCraftNativeUrl $webPort
    Wait-AdCraftNativeUrl 'Web' $url
    Write-AdCraftNativeInfo "原生部署成功：$url"
    Write-AdCraftNativeInfo '日志：scripts\logs-native-windows.ps1；停止：scripts\stop-native-windows.ps1'
    Start-Process -FilePath $url
} catch {
    Write-Error $_.Exception.Message
    try { Show-AdCraftNativeLogs } catch {}
    exit 1
}
