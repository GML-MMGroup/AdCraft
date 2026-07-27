. (Join-Path $PSScriptRoot 'windows-common.ps1')
Test-AdCraftProject
$state = Read-AdCraftState
Assert-AdCraftAgentRuntimeToken $state
if (-not (Test-AdCraftDockerReady)) { Stop-AdCraft 'Docker Desktop 未就绪。' }
Invoke-AdCraftCompose @('ps')
Write-AdCraftInfo "URL: $(Get-AdCraftUrl)"
Write-AdCraftInfo "Agent health: $(Get-AdCraftContainerHealth 'agent')"
Write-AdCraftInfo "API health: $(Get-AdCraftContainerHealth 'api')"
Write-AdCraftInfo "Web health: $(Get-AdCraftContainerHealth 'web')"
