[简体中文](manual-deployment_zh.md)

# Manual Step-by-Step Deployment

Use this guide only when `deploy-windows.cmd` or `deploy-linux.sh` cannot finish. It starts the same local-only AdCraft deployment, but you run every stage yourself and can see exactly where a problem occurs.

Do not run the one-click launcher and the commands below at the same time. Keep the complete project folder together. This guide does not install Python, Node.js, or a separate database server.

## What This Deployment Creates

Docker runs two services:

- `api`: the backend on the internal Docker network.
- `web`: the browser interface, published only on `127.0.0.1`.

## 1. Prepare the Project Folder

Put the complete AdCraft folder in a writable local location. Do not copy only the `scripts` folder.

- Windows example: `D:\AdCraft\AdCraft-main`
- Linux example: `~/AdCraft`

Open a terminal in that folder before continuing:

```text
Windows Command Prompt:  cd /d D:\AdCraft\AdCraft-main
Linux terminal:          cd ~/AdCraft
```

Choose a free local port between `8080` and `8179`. This guide uses `8080`. The finished address is `http://127.0.0.1:8080`; it is reachable only from the same computer.

## 2. Install and Start Docker

### Windows 10 or Windows 11

1. Open **PowerShell as Administrator**.
2. Run the following command. Restart Windows if it asks you to do so.

   ```powershell
   wsl --install
   ```

3. Download and install Docker Desktop from the [official Docker Desktop for Windows guide](https://docs.docker.com/desktop/setup/install/windows-install/). During installation, select the **WSL 2** backend when prompted.
4. Start Docker Desktop and wait until it reports that the engine is running. It must use **Linux containers**, not Windows containers.
5. Open a new Command Prompt in the AdCraft folder and check Docker:

   ```bat
   docker version
   docker compose version
   ```

   Continue only when both commands succeed and `docker version` shows a Server section.

Docker Desktop licensing is separate from AdCraft; make sure your intended use complies with Docker's applicable terms.

### Ubuntu or Debian Linux

1. Install Docker Engine and the Docker Compose plugin using Docker's official instructions for [Ubuntu](https://docs.docker.com/engine/install/ubuntu/) or [Debian](https://docs.docker.com/engine/install/debian/). Use the official `apt`-repository method, not an unverified third-party installer.
2. Start Docker and make it start after reboot:

   ```bash
   sudo systemctl enable --now docker
   ```

3. Check Docker:

   ```bash
   sudo docker version
   sudo docker compose version
   ```

   Continue only when both commands succeed. This guide keeps `sudo` in the Linux Docker commands so you do not need to change Docker-group permissions.

If an image pull fails because a corporate network, DNS rule, or proxy blocks Docker registries, fix that network path first. Configure Docker with an approved proxy or registry mirror for your organization, restart Docker, and retry the failed pull. Do not use an unknown public proxy for API keys or production data.

## 3. Create Local Configuration Without Overwriting Existing Keys

The commands below create files only when they are absent. If `apps/api/.env` already exists, it may contain API keys saved from AdCraft, so leave it in place.

### Windows Command Prompt

Run these commands from the project folder:

```bat
if not exist apps\api\.env copy apps\api\.env.example apps\api\.env
if not exist apps\web\.env copy apps\web\.env.example apps\web\.env
if not exist runtime-data mkdir runtime-data
if not exist runtime-data\api mkdir runtime-data\api
if not exist runtime-data\deployment.env (
  >runtime-data\deployment.env echo ADCRAFT_PORT=8080
  >>runtime-data\deployment.env echo ADCRAFT_UID=0
  >>runtime-data\deployment.env echo ADCRAFT_GID=0
)
```

The last three commands create `runtime-data/deployment.env` with the port and Windows container user settings. If you chose a port other than `8080`, replace `8080` in the first of those three commands before you run it.

### Linux Terminal

Run these commands from the project folder:

```bash
if [ ! -f apps/api/.env ]; then cp apps/api/.env.example apps/api/.env; chmod 600 apps/api/.env; fi
if [ ! -f apps/web/.env ]; then cp apps/web/.env.example apps/web/.env; chmod 600 apps/web/.env; fi
mkdir -p runtime-data/api
chmod 700 runtime-data runtime-data/api
if [ ! -f runtime-data/deployment.env ]; then
  printf 'ADCRAFT_PORT=8080\nADCRAFT_UID=%s\nADCRAFT_GID=%s\n' "$(id -u)" "$(id -g)" > runtime-data/deployment.env
  chmod 600 runtime-data/deployment.env
fi
```

If you chose another port, change `ADCRAFT_PORT=8080` before running the command. Do not copy either `.env.example` file over an existing `.env` file.

## 4. Validate the Compose Configuration

This checks paths and configuration before downloading or building images.

Windows Command Prompt:

```bat
docker compose --env-file runtime-data\deployment.env -f compose.yaml config
```

Linux terminal:

```bash
sudo docker compose --env-file runtime-data/deployment.env -f compose.yaml config
```

Expected result: Docker prints the resolved configuration and exits without an error. If it reports a missing file, return to step 3 and confirm you are in the complete project folder.

## 5. Build the Images

The first build downloads base images and backend/frontend dependencies, so it can take a long time on a slow connection. Keep the terminal open; Docker shows the active build stage and download progress.

Windows Command Prompt:

```bat
docker compose --env-file runtime-data\deployment.env -f compose.yaml build
```

Linux terminal:

```bash
sudo docker compose --env-file runtime-data/deployment.env -f compose.yaml build
```

If Docker reports a registry connection, DNS, or proxy error, the application has not started yet. Correct the Docker network/proxy configuration and rerun this same build command. Do not delete `.env` or `runtime-data/` to solve a network error.

## 6. Start AdCraft

Windows Command Prompt:

```bat
docker compose --env-file runtime-data\deployment.env -f compose.yaml up -d --remove-orphans
```

Linux terminal:

```bash
sudo docker compose --env-file runtime-data/deployment.env -f compose.yaml up -d --remove-orphans
```

Then check the service health.

Windows Command Prompt:

```bat
docker compose --env-file runtime-data\deployment.env -f compose.yaml ps
```

Linux terminal:

```bash
sudo docker compose --env-file runtime-data/deployment.env -f compose.yaml ps
```

Wait until both `api` and `web` show `healthy`. On the first startup, the API becomes healthy before the web service starts.

## 7. Open AdCraft and Add API Keys

Open this address in a browser on the same computer:

```text
http://127.0.0.1:8080
```

If you selected another port, use that port instead. Open **API Space**, enter the provider credentials you intend to use, and choose **Save credentials**. The application saves them locally in `apps/api/.env`; do not paste that file or its values into a chat, issue, or public document.

## Everyday Manual Commands

Run all commands from the project folder. Substitute the Linux `sudo docker` form when you are on Linux.

| Task | Windows Command Prompt | Linux terminal |
| --- | --- | --- |
| View status | `docker compose --env-file runtime-data\deployment.env -f compose.yaml ps` | `sudo docker compose --env-file runtime-data/deployment.env -f compose.yaml ps` |
| Read recent logs | `docker compose --env-file runtime-data\deployment.env -f compose.yaml logs --tail=100 api web` | `sudo docker compose --env-file runtime-data/deployment.env -f compose.yaml logs --tail=100 api web` |
| Rebuild after replacing project code | `docker compose --env-file runtime-data\deployment.env -f compose.yaml up -d --build --remove-orphans` | `sudo docker compose --env-file runtime-data/deployment.env -f compose.yaml up -d --build --remove-orphans` |
| Stop containers but keep data | `docker compose --env-file runtime-data\deployment.env -f compose.yaml down` | `sudo docker compose --env-file runtime-data/deployment.env -f compose.yaml down` |

Do not use `down -v`, and do not delete `runtime-data/`, unless you intentionally want to remove local deployment state, generated media, and the SQLite event database.

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| `docker version` does not show a Server section. | Start Docker Desktop on Windows. On Linux, run `sudo systemctl start docker`, then check the command again. |
| `docker compose` is unknown. | Install or update the Docker Compose plugin using Docker's official instructions, then open a new terminal. |
| `failed to fetch anonymous token`, `EOF`, DNS, or registry timeout. | This is a Docker network/proxy problem, not an AdCraft API-key problem. Correct the Docker Desktop or Linux Docker proxy/DNS path, restart Docker, and retry the build. |
| `port is already allocated`. | Stop the program using the selected port, or edit `ADCRAFT_PORT` in `runtime-data/deployment.env` to another free port from `8080` to `8179`, then run the start command again. |
| `api` or `web` is `exited` or `unhealthy`. | Run the logs command above. Keep API keys out of any log excerpt you share. Fix the first reported error, then rerun the rebuild/start command. |
| A rebuild succeeds but the browser still shows old content. | Refresh the browser without cache, then check `docker compose ... ps` and logs to confirm the new containers are running. |

This manual route remains local-only: the web port is bound to `127.0.0.1`. Do not expose it to the network by changing Compose settings unless you have separately designed authentication, TLS, firewall rules, and data protection.
