Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:ProjectRoot = Split-Path -Parent $PSScriptRoot
$script:ComposeFile = Join-Path $script:ProjectRoot 'compose.yaml'
$script:RuntimeDirectory = Join-Path $script:ProjectRoot 'runtime-data'
$script:StateFile = Join-Path $script:RuntimeDirectory 'deployment.env'

function Write-AdCraftInfo([string]$Message) {
    Write-Host "[AdCraft] $Message"
}

function Stop-AdCraft([string]$Message) {
    throw "[AdCraft] ERROR: $Message"
}

function Test-AdCraftProject {
    foreach ($path in @(
        $script:ComposeFile,
        (Join-Path $script:ProjectRoot 'apps/api/.env.example'),
        (Join-Path $script:ProjectRoot 'apps/web/.env.example')
    )) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            Stop-AdCraft "缺少必需文件：$path"
        }
    }
}

function Read-AdCraftState {
    if (-not (Test-Path -LiteralPath $script:StateFile -PathType Leaf)) {
        Stop-AdCraft '缺少 runtime-data/deployment.env，请先运行 deploy-windows.ps1。'
    }
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $script:StateFile) {
        if ($line -match '^(ADCRAFT_PORT|ADCRAFT_UID|ADCRAFT_GID)=([0-9]+)$') {
            $key, $value = $Matches[1], [Int64]$Matches[2]
        } elseif ($line -match '^ADCRAFT_AGENT_RUNTIME_TOKEN=([0-9a-f]{64})$') {
            $key, $value = 'ADCRAFT_AGENT_RUNTIME_TOKEN', [string]$Matches[1]
        } else {
            Stop-AdCraft 'deployment.env 格式无效。'
        }
        if ($values.ContainsKey($key)) { Stop-AdCraft "deployment.env 包含重复字段：$key。" }
        $values[$key] = $value
    }
    $missingKeys = @('ADCRAFT_PORT','ADCRAFT_UID','ADCRAFT_GID') | Where-Object { -not $values.ContainsKey($_) }
    if ($values.Count -notin @(3, 4) -or $missingKeys.Count -gt 0) {
        Stop-AdCraft 'deployment.env 缺少字段。'
    }
    if ($values['ADCRAFT_PORT'] -lt 8080 -or $values['ADCRAFT_PORT'] -gt 8179) {
        Stop-AdCraft 'deployment.env 端口超出范围。'
    }
    [pscustomobject]@{
        ADCRAFT_PORT = [int]$values['ADCRAFT_PORT']
        ADCRAFT_UID = [int]$values['ADCRAFT_UID']
        ADCRAFT_GID = [int]$values['ADCRAFT_GID']
        ADCRAFT_AGENT_RUNTIME_TOKEN = if ($values.ContainsKey('ADCRAFT_AGENT_RUNTIME_TOKEN')) { [string]$values['ADCRAFT_AGENT_RUNTIME_TOKEN'] } else { $null }
    }
}

function Assert-AdCraftAgentRuntimeToken($State) {
    if ($null -eq $State.ADCRAFT_AGENT_RUNTIME_TOKEN) {
        Stop-AdCraft 'deployment.env 缺少 Agent 内部令牌；请重新运行 deploy-windows.cmd。'
    }
}

function New-AdCraftAgentRuntimeToken {
    $bytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    } finally {
        $generator.Dispose()
    }
    return -join ($bytes | ForEach-Object { $_.ToString('x2') })
}

function Write-AdCraftState([int]$Port) {
    if ($Port -lt 8080 -or $Port -gt 8179) {
        Stop-AdCraft '端口必须在 8080–8179 范围内。'
    }

    if (-not (Test-Path -LiteralPath $script:RuntimeDirectory -PathType Container)) {
        [System.IO.Directory]::CreateDirectory($script:RuntimeDirectory) > $null
    }

    $existingToken = $null
    if (Test-Path -LiteralPath $script:StateFile -PathType Leaf) {
        $existingToken = (Read-AdCraftState).ADCRAFT_AGENT_RUNTIME_TOKEN
    }
    $token = if ($null -ne $existingToken) { $existingToken } else { New-AdCraftAgentRuntimeToken }
    $content = "ADCRAFT_PORT=$Port`nADCRAFT_UID=0`nADCRAFT_GID=0`nADCRAFT_AGENT_RUNTIME_TOKEN=$token`n"
    $temporaryPath = Join-Path $script:RuntimeDirectory ("deployment.env.{0}.tmp" -f [Guid]::NewGuid().ToString('N'))
    $temporaryCreated = $true

    try {
        [System.IO.File]::WriteAllText($temporaryPath, $content, [System.Text.UTF8Encoding]::new($false))

        Move-Item -LiteralPath $temporaryPath -Destination $script:StateFile -Force
    } catch {
        if ($temporaryCreated -and [System.IO.File]::Exists($temporaryPath)) {
            [System.IO.File]::Delete($temporaryPath)
        }
        throw
    }
}

function Initialize-AdCraftEnvFile([string]$RelativePath) {
    $target = Join-Path $script:ProjectRoot $RelativePath
    $example = "$target.example"

    if (Test-Path -LiteralPath $target) {
        $targetItem = Get-Item -LiteralPath $target -Force
        if (-not ($targetItem -is [System.IO.FileInfo]) -or (($targetItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)) {
            Stop-AdCraft "$RelativePath 已存在但不是普通文件。"
        }
        return
    }

    if (-not (Test-Path -LiteralPath $example -PathType Leaf)) {
        Stop-AdCraft "缺少 dotenv 示例文件：$example"
    }

    try {
        [System.IO.File]::Copy($example, $target, $false)
    } catch [System.IO.IOException] {
        if (Test-Path -LiteralPath $target) {
            $targetItem = Get-Item -LiteralPath $target -Force
            if ($targetItem -is [System.IO.FileInfo] -and (($targetItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0)) {
                return
            }
            Stop-AdCraft "$RelativePath 已存在但不是普通文件。"
        }
        throw
    }
}

function Test-AdCraftPortFree([int]$Port) {
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    return $listeners.Count -eq 0
}

function Select-AdCraftPort {
    if (Test-Path -LiteralPath $script:StateFile -PathType Leaf) {
        $savedState = Read-AdCraftState
        $savedPort = $savedState.ADCRAFT_PORT
        $webContainerId = @()
        if ($null -ne $savedState.ADCRAFT_AGENT_RUNTIME_TOKEN) {
            $webContainerId = @(
                Invoke-AdCraftCompose @('ps', '-q', 'web') |
                    Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }
            )
        }

        if ($webContainerId.Count -gt 0 -or (Test-AdCraftPortFree $savedPort)) {
            return $savedPort
        }
    }

    foreach ($port in 8080..8179) {
        if (Test-AdCraftPortFree $port) {
            return $port
        }
    }

    Stop-AdCraft '8080–8179 均被占用，无法发布 AdCraft Web 端口。'
}

function Invoke-AdCraftCompose([string[]]$Arguments) {
    & docker compose --env-file $script:StateFile -f $script:ComposeFile @Arguments
    if ($LASTEXITCODE -ne 0) { Stop-AdCraft "docker compose $($Arguments -join ' ') 失败。" }
}

function Get-AdCraftContainerHealth([ValidateSet('agent','api','web')][string]$Service) {
    $containerId = @(
        Invoke-AdCraftCompose @('ps', '-q', $Service) |
            Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }
    )
    if ($containerId.Count -eq 0) {
        return 'missing'
    }

    $health = & docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $containerId[0]
    if ($LASTEXITCODE -ne 0) {
        Stop-AdCraft "无法检查 $Service 容器状态。"
    }
    return ([string]$health).Trim()
}

function Wait-AdCraftServices {
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

    while ($stopwatch.Elapsed.TotalSeconds -lt 120) {
        $agentStatus = Get-AdCraftContainerHealth 'agent'
        $apiStatus = Get-AdCraftContainerHealth 'api'
        $webStatus = Get-AdCraftContainerHealth 'web'
        if ($agentStatus -eq 'healthy' -and $apiStatus -eq 'healthy' -and $webStatus -eq 'healthy') {
            return
        }
        if ($agentStatus -in @('exited', 'dead') -or $apiStatus -in @('exited', 'dead') -or $webStatus -in @('exited', 'dead')) {
            Stop-AdCraft "服务启动失败：agent=$agentStatus，api=$apiStatus，web=$webStatus。"
        }
        Start-Sleep -Seconds 2
    }

    Stop-AdCraft '等待 agent、api 和 web 服务健康检查超时。'
}

function Show-AdCraftLogs {
    Invoke-AdCraftCompose @('logs', '--tail=100', 'agent', 'api', 'web')
}

function Get-AdCraftUrl {
    $state = Read-AdCraftState
    return "http://127.0.0.1:$($state.ADCRAFT_PORT)"
}

function Start-AdCraftBrowser {
    Start-Process -FilePath (Get-AdCraftUrl)
}

function Test-AdCraftDockerReady {
    try {
        & docker info *> $null
        if ($LASTEXITCODE -ne 0) {
            return $false
        }

        & docker compose version *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Wait-AdCraftDockerReady {
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

    while ($stopwatch.Elapsed.TotalSeconds -lt 180) {
        if (Test-AdCraftDockerReady) {
            return
        }
        Start-Sleep -Seconds 2
    }

    Stop-AdCraft 'Docker Engine 或 Docker Compose v2 在 180 秒内未就绪。'
}
