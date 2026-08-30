$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$example = Get-Content (Join-Path $root 'cpa/config.example.yaml') -Raw
foreach ($pattern in @('sk-', 'Bearer ', 'access_token', 'refresh_token', 'client_secret')) {
    if ($example -match [regex]::Escape($pattern)) { throw "Unsafe credential marker found: $pattern" }
}
$ignored = @(
    (git -C $root check-ignore 'cpa/config.yaml'),
    (git -C $root check-ignore 'cpa/auths/example.json'),
    (git -C $root check-ignore 'cpa/logs/example.log')
)
if (($ignored | Where-Object { [string]::IsNullOrWhiteSpace($_) }).Count -ne 0) {
    throw 'CPA runtime paths are not ignored by Git.'
}
Write-Output 'CPA config boundary OK'
