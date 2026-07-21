. (Join-Path $PSScriptRoot 'windows-common.ps1')
Test-AdCraftProject
$null = Read-AdCraftState
if (-not (Test-AdCraftDockerReady)) { Stop-AdCraft 'Docker Desktop 未就绪。' }
Write-AdCraftInfo '停止 AdCraft 容器（保留 .env、runtime-data、镜像和卷）……'
Invoke-AdCraftCompose @('stop')
