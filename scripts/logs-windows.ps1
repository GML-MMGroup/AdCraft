. (Join-Path $PSScriptRoot 'windows-common.ps1')
Test-AdCraftProject
$state = Read-AdCraftState
Assert-AdCraftAgentRuntimeToken $state
if (-not (Test-AdCraftDockerReady)) { Stop-AdCraft 'Docker Desktop 未就绪。' }
Show-AdCraftLogs
