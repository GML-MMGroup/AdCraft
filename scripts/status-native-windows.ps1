. (Join-Path $PSScriptRoot 'native-windows-common.ps1')

Test-AdCraftNativeProject
$state = Read-AdCraftNativeState
$apiPid = Get-AdCraftNativePid $script:NativeApiPidFile
$agentPid = Get-AdCraftNativePid $script:NativeAgentPidFile
$webPid = Get-AdCraftNativePid $script:NativeWebPidFile
if ($null -eq $apiPid) {
    Write-AdCraftNativeInfo 'API: stopped'
} else {
    Write-AdCraftNativeInfo "API: running (PID $apiPid)"
}
if ($null -eq $agentPid) {
    Write-AdCraftNativeInfo 'Agent: stopped'
} else {
    Write-AdCraftNativeInfo "Agent: running (PID $agentPid)"
}
if ($null -eq $webPid) {
    Write-AdCraftNativeInfo 'Web: stopped'
} else {
    Write-AdCraftNativeInfo "Web: running (PID $webPid)"
}
if (Test-AdCraftNativeUrl (Get-AdCraftNativeApiUrl $state.ApiPort)) {
    Write-AdCraftNativeInfo 'API health: healthy'
} else {
    Write-AdCraftNativeInfo 'API health: unavailable'
}
if (Test-AdCraftNativeUrl (Get-AdCraftNativeAgentUrl $state.AgentPort) @{ Authorization = "Bearer $($state.AgentRuntimeToken)" }) {
    Write-AdCraftNativeInfo 'Agent health: healthy'
} else {
    Write-AdCraftNativeInfo 'Agent health: unavailable'
}
if (Test-AdCraftNativeUrl (Get-AdCraftNativeUrl $state.WebPort)) {
    Write-AdCraftNativeInfo 'Web health: reachable'
} else {
    Write-AdCraftNativeInfo 'Web health: unavailable'
}
Write-AdCraftNativeInfo "URL: $(Get-AdCraftNativeUrl $state.WebPort)"
