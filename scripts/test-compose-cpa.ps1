$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$rendered = (docker compose -f (Join-Path $root 'compose.yaml') config) -join "`n"
if ($LASTEXITCODE -ne 0) { throw 'docker compose config failed.' }
if ($rendered -notmatch '(?m)^\s+cpa:') { throw 'Rendered Compose config has no cpa service.' }
if ($rendered -notmatch 'http://cpa:8317/v1') { throw 'AdCraft API does not default to the CPA internal URL.' }
foreach ($pattern in @('sk-', 'access_token', 'refresh_token', 'client_secret')) {
    if ($rendered -match [regex]::Escape($pattern)) { throw "Credential marker found in rendered config: $pattern" }
}
$services = docker compose -f (Join-Path $root 'compose.yaml') config --services
foreach ($service in @('cpa', 'agent', 'api', 'web')) {
    if ($services -notcontains $service) { throw "Missing service: $service" }
}
Write-Output 'CPA Compose wiring OK'
