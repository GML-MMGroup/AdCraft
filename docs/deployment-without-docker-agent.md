# Agent Runbook: Deploy AdCraft Without Docker

This runbook is for a desktop coding agent that has terminal access to a complete AdCraft checkout. Its required outcome is a local-only native deployment with the Agent Runtime, API, and Web processes running, healthy, and reachable through a reported Web URL.

For prerequisite installation commands and human-oriented manual recovery, read [Native Deployment Without Docker](deployment-without-docker.md).

## Operating contract

- Locate the project root by confirming that `apps/api/pyproject.toml`, `apps/api/uv.lock`, `apps/api/agent/package.json`, `apps/api/agent/package-lock.json`, `apps/web/package.json`, and `apps/web/package-lock.json` all exist.
- Deploy the user's current checkout. Preserve existing `.env`, `runtime-data/`, databases, media, PID files, and logs unless a repository script replaces its own stale state.
- Keep commands attached and relay meaningful download, installation, startup, and health-check progress.
- Keep every service on the loopback interface. Do not replace `127.0.0.1` with a public or LAN address.
- Treat `.env` files and `runtime-data/native/native.env` as secrets. Never print their values or add them to Git.
- No provider API key is required during startup. The user enters credentials in API Space after the Web UI is available.
- Use the repository launchers as the source of truth for dependency sync, process order, internal token generation, ports, origins, logs, and PID state.
- Ask the user only for an action the agent cannot perform, such as accepting UAC, entering an administrator password, or restarting after a system-tool installation.

## 1. Inspect the environment

1. Change to the project root.
2. Record `git status --short`, but do not reset, clean, stash, or overwrite user changes.
3. Detect the host from the operating-system APIs:
   - 64-bit Windows 10 or Windows 11; or
   - a Linux distribution explicitly covered by [the native deployment guide](deployment-without-docker.md#step-1-install-the-system-tools-once).
4. Check the required tools and versions:
   - `uv`;
   - Node.js 22 with its matching `npm`;
   - FFmpeg and ffprobe `>=6.1,<8`, from the same distribution;
   - Linux only: `curl`, `setsid`, and the socket tool used by the launcher.
5. If a tool is missing or incompatible, read and execute only the matching OS subsection under Step 1 of the human guide. Re-check actual versions after installation; installer success alone is not verification.

The inspection is complete when every required executable resolves from the same environment that will run the launcher.

## 2. Run the authoritative launcher

The launcher performs an eight-stage operation: validate, initialize local state, synchronize backend dependencies, install Agent Runtime dependencies, install Web dependencies, start Agent Runtime, start API, and start Web. Do not start only two of the three processes.

### Windows

Use Windows PowerShell from the project root:

```powershell
Set-Location C:\path\to\AdCraft
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy-native-windows.ps1
```

Run the script directly so the agent can retain and inspect its complete output. Use UAC only when prerequisite installation requires it; the native launcher itself should run as the user who will own the processes and `runtime-data/`.

### Linux

Use a visible Bash terminal:

```bash
cd /path/to/AdCraft
bash scripts/deploy-native-linux.sh
```

The launcher prints each stage and the progress produced by `uv sync` and `npm ci`. Continue monitoring until it prints the final URL or a concrete error. API startup recovery may resume an interrupted video export, so the readiness display can remain active for up to 30 minutes.

The launch step is complete only when all eight stages finish and the launcher prints a local Web URL.

### Redeploy after a code update

When the checkout already contains newer code from the user, run the same native launcher again. It synchronizes the locked Python and Node dependencies, stops the three processes previously managed by the launcher, and starts Agent Runtime, API, and Web from the updated files. Preserve `.env` and `runtime-data/`; the launcher also retains the local database, generated media, and saved credentials. Existing processes do not update in place, so complete the verification in Section 4 after every redeployment.

## 3. Resolve port conflicts as one deployment

The default native ports are API `8000`, internal Agent Runtime `8765`, and Web `5189`. The three ports must be distinct and available.

If the launcher reports a conflict, inspect listening sockets and select three free ports in the range `1024`–`65535`. Restart all three managed processes through one launcher invocation so that the Web proxy, API-to-Agent connection, and trusted Web origins are updated together.

Windows PowerShell:

```powershell
Set-Location C:\path\to\AdCraft
$env:ADCRAFT_NATIVE_API_PORT = '8001'
$env:ADCRAFT_NATIVE_AGENT_PORT = '8766'
$env:ADCRAFT_NATIVE_WEB_PORT = '5190'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy-native-windows.ps1
```

Linux:

```bash
cd /path/to/AdCraft
ADCRAFT_NATIVE_API_PORT=8001 \
ADCRAFT_NATIVE_AGENT_PORT=8766 \
ADCRAFT_NATIVE_WEB_PORT=5190 \
bash scripts/deploy-native-linux.sh
```

The numbers above are examples. Verify that the chosen ports are free before retrying. Do not change only the Web or API process after startup; rerun the full launcher with all selected values.

## 4. Verify the running system

Run the platform status command after every apparently successful launch.

Windows PowerShell:

```powershell
Set-Location C:\path\to\AdCraft
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\status-native-windows.ps1
```

Linux:

```bash
cd /path/to/AdCraft
bash scripts/status-native-linux.sh
```

Then request the reported Web URL with a short timeout. Verification passes only when:

1. Agent Runtime, API, and Web each have a live managed process;
2. Agent Runtime and API report healthy, and Web reports reachable;
3. the reported Web URL responds from the host; and
4. the URL uses `127.0.0.1` or `localhost`.

Open the URL if the launcher did not. Tell the user that provider API keys can now be entered in API Space. Do not expose the internal Agent token.

## 5. Recover from a failed deployment

Keep the first failing stage and exact error. Inspect the repository-managed logs before changing configuration.

Windows PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\logs-native-windows.ps1
```

Linux:

```bash
bash scripts/logs-native-linux.sh
```

Apply the smallest matching recovery:

- **Executable missing or wrong version:** install the exact prerequisite described in the human guide, open a new shell if PATH changed, re-check the version, then rerun the launcher.
- **Dependency download failure:** identify whether `uv`, npm, or the OS package manager failed. Fix that tool's network, registry, or proxy path, then rerun; do not mix package managers or remove lockfiles.
- **Port conflict:** choose three free ports and rerun the whole launcher as described above.
- **Stale process:** use the supplied stop script, then rerun the launcher.
- **Agent Runtime, API, or Web startup failure:** read the corresponding managed log. Preserve the other logs and `runtime-data/` as evidence.

Windows PowerShell stop command:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-native-windows.ps1
```

Linux stop command:

```bash
bash scripts/stop-native-linux.sh
```

Retry only after a relevant state change. If the same blocker remains, report the OS, failed stage, tool versions, exact error, relevant log excerpt, and the single user action needed next. Dependency installation or two healthy processes do not constitute a complete deployment.

## Completion report

Return a concise report containing:

- operating system and installed prerequisite versions;
- launcher command and any port overrides used;
- health of Agent Runtime, API, and Web;
- the local Web URL;
- whether a browser was opened; and
- any user action still required.

Deployment is complete only when all three processes pass their checks and the Web URL is reachable.
