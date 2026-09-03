# Agent Runbook: Deploy AdCraft with Docker

This runbook is for a desktop coding agent that has terminal access to a complete AdCraft checkout. Its required outcome is a local-only AdCraft deployment with the Agent Runtime, API, and Web services healthy and a working Web URL reported to the user.

For human-oriented explanations and manual recovery commands, read [Deploy AdCraft](deployment-with-docker.md).

## Operating contract

- Work from the user's existing checkout. Locate the project root by confirming that `compose.yaml`, `apps/api/pyproject.toml`, `apps/api/agent/package.json`, and `apps/web/package.json` all exist.
- Deploy the current files as they are. Preserve existing `.env` files, `runtime-data/`, databases, media, and Docker volumes.
- Keep the deployment command attached and relay meaningful progress. A long image download or build is active work while output, byte counts, or network activity continue.
- Keep the deployment local-only. The supplied Compose configuration binds the Web service to `127.0.0.1`; do not change it to a public interface.
- Treat `.env` files and `runtime-data/deployment.env` as secrets. Never print their values or add them to Git.
- No provider API key is required to start AdCraft. The user enters provider credentials in the Web UI after deployment.
- Use the repository launchers as the source of truth. Do not recreate their Compose, port, token, or environment logic in ad hoc commands.
- Ask the user only for an action the agent cannot perform, such as accepting UAC, entering a sudo password, restarting Windows, or changing a desktop proxy setting.

## 1. Inspect the environment

1. Change to the project root.
2. Record `git status --short` for context, but do not reset, clean, stash, or overwrite user changes.
3. Detect the operating system:
   - Windows: 64-bit Windows 10 22H2 (build 19045+) or Windows 11 23H2 (build 22631+).
   - Linux: Ubuntu or Debian with `bash`. Read `/etc/os-release` rather than guessing from the shell prompt.
4. Detect whether this shell is itself inside a container. If it is and `docker info` cannot reach an external Docker Engine, report that the environment is not a supported deployment host. Do not attempt Docker-in-Docker or modify the outer container.
5. Check network access to the registries used by the Dockerfiles: Docker Hub and `ghcr.io`. A failed preflight is diagnostic; the launcher remains the authoritative deployment attempt.

The inspection is complete when the project root and one supported host path are known.

## 2. Run the authoritative launcher

### Windows

Use Windows PowerShell, not WSL, for the Windows launcher. If the current process is already elevated, run:

```powershell
Set-Location C:\path\to\AdCraft
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy-windows.ps1
```

If the current process is not elevated, start the same script through UAC and wait for it:

```powershell
Set-Location C:\path\to\AdCraft
$script = (Resolve-Path .\scripts\deploy-windows.ps1).Path
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$script`""
$process = Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "AdCraft deployment exited with code $($process.ExitCode)." }
```

The user may need to accept the UAC prompt. The launcher checks Windows support, enables WSL 2, installs or starts Docker Desktop, initializes missing local configuration, selects a free Web port, builds the images, starts all three services, waits for health, and opens the browser.

If Windows says a restart is required after enabling WSL 2, record this as a resumable state. Ask the user to restart Windows; after restart, run the same launcher again from the same checkout. Do not treat the pre-restart exit as a completed deployment.

### Linux

Run the launcher from a visible terminal:

```bash
cd /path/to/AdCraft
bash scripts/deploy-linux.sh
```

Allow the command to finish. The launcher reuses a working Docker Engine, or on a supported Ubuntu/Debian host installs Docker Engine and Compose v2 with root privileges. It then initializes missing local configuration, selects a free Web port in `8080`–`8179`, builds the images, starts all three services, waits for health, and opens a browser when a desktop session is available.

If sudo requests a password, ask the user to enter it in the same terminal and continue monitoring afterward.

The launch step is complete only when the launcher exits successfully and prints `部署成功` followed by a local URL.

## 3. Verify the running system

Run the platform status command even when the launcher reported success.

Windows PowerShell:

```powershell
Set-Location C:\path\to\AdCraft
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\status-windows.ps1
```

Linux:

```bash
cd /path/to/AdCraft
bash scripts/status-linux.sh
```

Then request the reported Web URL from the host with a short timeout. Verification passes only when:

1. the `agent`, `api`, and `web` containers are running and healthy;
2. the Web URL is reachable from the host; and
3. the URL uses `127.0.0.1` or `localhost`.

Open the URL if the launcher did not. Tell the user that provider API keys can now be entered in API Space. Report the URL without exposing environment values or the internal Agent token.

## 4. Recover from a failed deployment

Preserve the first failing command and its exact error. Diagnose the matching branch, make one relevant state change, and retry the authoritative launcher.

- **Windows restart required:** restart, then resume the same launcher.
- **Docker Desktop installed but unavailable:** start Docker Desktop, wait until `docker info` works, confirm Linux containers mode, then retry.
- **Docker Hub or `ghcr.io` EOF, timeout, DNS, or token failure:** test the failing endpoint from both the host and Docker Engine. Follow the proxy guidance in [Deploy AdCraft](deployment-with-docker.md#common-problems). Ask the user to adjust Docker Desktop's proxy when desktop interaction is required. Do not disable TLS verification or install untrusted certificates.
- **Linux package repository failure:** identify the failing repository. A broken unrelated APT source must be corrected or disabled by the user or administrator before retrying. Do not silently rewrite third-party repositories.
- **Port conflict:** rerun the launcher. It owns port selection and keeps the Web origin, API routing, and saved state consistent.
- **Unhealthy container:** inspect the supplied logs before changing anything.

Windows PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\logs-windows.ps1
```

Linux:

```bash
bash scripts/logs-linux.sh
```

Stop after repeated failure with no new state change. Report the OS, failing stage, exact error, relevant status/log excerpt, and the single user action needed next. Never report deployment success from image-build success alone.

## Completion report

Return a concise report containing:

- operating system and Docker path used;
- successful launcher command;
- health of Agent Runtime, API, and Web;
- the local Web URL;
- whether a browser was opened; and
- any user action still required.

Deployment is complete only when all three services pass health checks and the Web URL is reachable.
