. (Join-Path $PSScriptRoot 'native-windows-common.ps1')

Test-AdCraftNativeProject
$null = Read-AdCraftNativeState
Show-AdCraftNativeLogs
