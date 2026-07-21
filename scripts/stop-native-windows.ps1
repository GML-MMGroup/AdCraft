. (Join-Path $PSScriptRoot 'native-windows-common.ps1')

Test-AdCraftNativeProject
$state = Read-AdCraftNativeState
Stop-AdCraftNativeProcess 'Web' $script:NativeWebPidFile
Stop-AdCraftNativeProcess 'API' $script:NativeApiPidFile
Write-AdCraftNativeInfo "原生 AdCraft 已停止（保留 .env、runtime-data 和日志）：$(Get-AdCraftNativeUrl $state.WebPort)"
