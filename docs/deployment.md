[简体中文](deployment_zh.md)

# Deploy AdCraft

This guide starts AdCraft on your own computer. It is written for first-time users: the supplied launcher installs its required runtime when necessary, builds AdCraft, starts it, and prints the local address to open.

If the one-click launcher cannot complete on your computer, follow the [manual step-by-step deployment guide](manual-deployment.md). It uses the same Docker configuration but lets you run and inspect every stage yourself.

## What You Need

- A complete copy of the AdCraft project folder. Keep the folder together; do not run a script from a copied `scripts` folder.
- Internet access for the first deployment, because the launcher may download required components and build images.
- One supported operating system:
  - **Windows:** 64-bit Windows 10 22H2 (build 19045) or later, or 64-bit Windows 11 23H2 (build 22631) or later. Hardware virtualization must be available. Windows Server and Windows containers are not supported.
  - **Linux:** Ubuntu or Debian. Other Linux distributions are not supported by the first-release launcher.
- On Windows, permission to run a file as an administrator. On Linux, an account that can enter its `sudo` password if the launcher asks.
- API keys from the provider you intend to use. You add them after AdCraft is running; do not put them in a chat message or a public document.

You do **not** need to install Python, Node.js, Docker, or Docker Compose manually. The Windows launcher can set up WSL 2 and Docker Desktop; the Linux launcher can install Docker Engine and its Compose plugin. Those steps need network access and may request administrator or `sudo` permission.

## Before You Start

1. Put the complete project in a local, writable folder. On Windows, a local NTFS folder is the safest choice.
2. Save any work in the folder and make sure the computer has enough disk space for downloaded components and the initial build.
3. Use a trusted personal or work computer. AdCraft will keep API credentials and generated media on this host.
4. Do not manually edit deployment files just to get started. The launcher creates the environment files it needs and chooses an available local port from 8080 through 8179.

The address printed at the end has the form `http://127.0.0.1:<port>`. `127.0.0.1` means this computer only; it is not a public website address.

## Deploy on Windows

1. Open the project folder in File Explorer and open its `scripts` folder.
2. Right-click `scripts\\deploy-windows.cmd` and choose **Run as administrator**. Approve the Windows prompt.
3. On a new machine, the launcher may enable or install WSL 2 and Docker Desktop. Windows may ask you to reboot. If it does, restart Windows, then right-click and run the **same** `scripts\\deploy-windows.cmd` file as administrator again.
4. Wait while the launcher checks the system, prepares its runtime, builds AdCraft, and starts the web and API services. The first run can take longer than later runs.
5. When it reports success, open the printed `http://127.0.0.1:<port>` URL. The launcher normally opens a browser for you; if it does not, copy the displayed URL into a browser on the same computer.

Expected outcome: both services become healthy and AdCraft opens locally. Docker Desktop must run in **Linux containers** mode. The person deploying is responsible for complying with the applicable Docker Desktop licensing terms.

## Deploy on Linux

1. Open a terminal **in the project folder**.
2. Run this exact command:

   ```bash
   bash scripts/deploy-linux.sh
   ```

3. Enter your `sudo` password **only if the launcher asks for it**. It may need that permission to install or start Docker and supporting system packages. Do not type your API key at a `sudo` prompt.
4. Wait while it checks Ubuntu/Debian, prepares the runtime, builds AdCraft, and waits for the web and API services to become healthy. The first run can take longer than later runs.
5. Open the printed `http://127.0.0.1:<port>` URL. On a graphical Linux desktop the launcher may open it automatically; otherwise, copy it into a browser on the same computer.

Expected outcome: the command finishes with a deployment-success message and the local URL. You do not need to install Python, Node.js, Docker, or Docker Compose yourself.

## Open AdCraft and Add API Keys

1. Open the printed local URL and go to **API Space**.
2. Choose the available provider, currently **Volcengine Ark**. API Space presents separate key entries for **LLM**, **Image**, and **Video**. Enter the key for each type of work you plan to use. If your provider issued one key with the right permissions for all three, you can use the page's **Use for all** option; otherwise use the appropriate separate keys.
3. Select **Save credentials**. A successful save reports that the credentials were saved and applied, so you do not need to restart AdCraft for that change.
4. If API Space offers a connection test for a configured key, use it to confirm the provider connection. A successful test reports that the connection succeeded, sometimes with the model name.

The keys are stored locally on this host in `apps/api/.env` and are shown in status only in masked form. Treat that file like a password file: do not share it, commit it, attach it to support requests, or paste its contents into a terminal transcript. API usage can incur provider charges; confirm that the key, account, model access, and billing permissions are correct before generating media.

## Everyday Commands

Run these from the project folder when AdCraft has already been deployed.

| What you want to do | Windows PowerShell | Linux terminal | What to expect |
| --- | --- | --- | --- |
| Check status | `.\\scripts\\status-windows.ps1` | `bash scripts/status-linux.sh` | The local URL plus API and web health status. |
| Read recent logs | `.\\scripts\\logs-windows.ps1` | `bash scripts/logs-linux.sh` | Up to 100 recent API and web log lines. Do not post log lines that contain sensitive information. |
| Stop AdCraft | `.\\scripts\\stop-windows.ps1` | `bash scripts/stop-linux.sh` | Stops the containers while keeping configuration, runtime data, images, and volumes. |
| Start it again or update after replacing project files | Right-click `scripts\\deploy-windows.cmd` and choose **Run as administrator** | `bash scripts/deploy-linux.sh` | Reuses the saved local configuration and prints the local URL again. |

You do not need to run Docker commands yourself. If Windows PowerShell blocks one of the maintenance scripts, open PowerShell as administrator from the project folder and run the displayed command again.

## Keep These Files

- `apps/api/.env` holds backend configuration and the API keys saved in API Space. Keep it private and do not delete it when updating AdCraft.
- `apps/web/.env` holds the web application's local configuration. Keep it with the project.
- `runtime-data/` holds generated media and deployment state, including the selected local port. Do not delete it as part of an update if you want to keep generated work and the saved deployment state.

Stopping AdCraft does not delete these files, images, or volumes. Back up private credentials and valuable generated media using your organization's approved, encrypted backup process before moving or removing the project folder.

## Common Problems

| Problem | What to do | Expected outcome |
| --- | --- | --- |
| Windows says administrator permission is required. | Right-click `scripts\\deploy-windows.cmd` and choose **Run as administrator**. | The launcher can check prerequisites and continue. |
| Windows enables WSL 2 or asks to restart. | Restart Windows, then run the same `scripts\\deploy-windows.cmd` file as administrator again. | The second run continues with WSL 2 available. |
| Docker Desktop is missing, not ready, or is using Windows containers. | Keep an internet connection, let the launcher finish its setup, start Docker Desktop if prompted, and switch it to Linux containers mode. Then rerun the launcher. | Docker and Docker Compose become available to the launcher. |
| Docker image pulls report `EOF`, an anonymous-token error, or cannot reach `auth.docker.io`. | Keep your proxy client running. In Docker Desktop, open **Settings → Resources → Proxies**, choose manual configuration, and enter only the HTTP/HTTPS proxy URL (for example, `http://127.0.0.1:7890` for a FlClash listener on that address; do not type an `HTTP Proxy:` label). If needed, enable FlClash TUN/global mode and route `docker.io`, `docker.com`, and `dockerusercontent.com` through the proxy. Apply the setting or restart Docker Desktop, then run `docker pull docker/dockerfile:1.7` in Command Prompt. Rerun the launcher only after that command succeeds. | Docker can retrieve the Dockerfile frontend and image layers needed for the build. |
| The Windows version is rejected. | Use 64-bit Windows 10 22H2 build 19045+ or Windows 11 23H2 build 22631+. | The supported-platform check passes. |
| The Linux launcher rejects the operating system. | Use Ubuntu or Debian for this deployment path. | The launcher can determine the supported OS release. |
| A Linux `sudo` prompt appears. | Enter the password for the local account only at that prompt. Do not enter API keys there. | The launcher can install or start required system services. |
| No browser opens after success. | Copy the printed `http://127.0.0.1:<port>` URL into a browser on the same computer. | The local AdCraft page opens. |
| All ports from 8080 through 8179 are in use. | Stop or reconfigure another local program using those ports, then rerun the deployment launcher. | AdCraft can select a free port and print its URL. |
| Deployment reports a health timeout or failed service. | Check status and read the recent logs with the commands above; keep API keys out of anything you share. After resolving the reported local problem, rerun the deployment launcher. | The API and web services report healthy. |
| API Space cannot save or test a key. | Verify the provider key, permissions, billing/quota, model access, and network connection; save the corrected key again. | API Space shows the credential as configured and any available connection test succeeds. |
| A script says required project files or deployment state are missing. | Return to the complete project folder and run the deployment launcher before using status, logs, or stop. | The launcher recreates the required local state. |

## Scope and Safety

- This deployment path is for the supported Windows and Linux desktop systems listed above. It does not configure a public server, remote access, TLS, user accounts, or shared-network access.
- The web port is bound to `127.0.0.1`, so open the printed URL only on the deploying computer. Do not expose it to a network by changing deployment configuration unless you have separately designed and secured that change.
- Keep `apps/api/.env`, `apps/web/.env`, and `runtime-data/` private. They can contain credentials, configuration, deployment state, and generated media.
- The launcher does not change proxy settings or store proxy credentials. Configure proxies only in Docker Desktop or your approved network client.
- Use only API keys and media you are authorized to use. Protect provider accounts, watch provider costs, and follow your organization's data-handling requirements.
- Do not delete environment files or `runtime-data/` to troubleshoot an update unless you have an approved backup and understand that local credentials, generated media, or deployment state may be lost.
