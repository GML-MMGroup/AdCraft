. (Join-Path $PSScriptRoot 'windows-common.ps1')
Test-AdCraftProject
$null = Read-AdCraftState
if (-not (Test-AdCraftDockerReady)) { Stop-AdCraft 'Docker Desktop 未就绪。' }
Show-AdCraftLogs
