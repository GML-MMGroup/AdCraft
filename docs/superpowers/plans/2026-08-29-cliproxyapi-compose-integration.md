# CLIProxyAPI Compose 集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add CLIProxyAPI as a separately configured, Compose-managed OpenAI-compatible sidecar for AdCraft LLM traffic.

**Architecture:** Add a `cpa` service using the official CLIProxyAPI release image, with local-only configuration/auth/log mounts and a stable internal service name. Point AdCraft API at `http://cpa:8317/v1`, keep the downstream CPA key in ignored local configuration, and gate API startup on CPA readiness without exposing OAuth material to the repository.

**Tech Stack:** Docker Compose, CLIProxyAPI official image, YAML configuration, PowerShell smoke checks, AdCraft Python/FastAPI and Node agent runtime.

---

### Task 1: Add ignored CPA configuration boundaries

**Files:**
- Create: `cpa/config.example.yaml`
- Create: `cpa/.gitkeep`
- Create: `cpa/auths/.gitkeep`
- Create: `cpa/logs/.gitkeep`
- Modify: `.gitignore`
- Test: `scripts/test-cpa-config.ps1`

- [ ] **Step 1: Add a safe example configuration**

Create `cpa/config.example.yaml` with localhost binding, port `8317`, an explicit placeholder `api-keys` entry, `auth-dir: /root/.cli-proxy-api`, and `ws-auth: true`. Do not include OAuth tokens, real provider keys, or management secrets.

- [ ] **Step 2: Add ignore rules before creating runtime files**

Append these rules to `.gitignore`:

```gitignore
cpa/config.yaml
cpa/auths/*
!cpa/auths/.gitkeep
cpa/logs/*
!cpa/logs/.gitkeep
```

- [ ] **Step 3: Add a configuration-boundary test**

Create `scripts/test-cpa-config.ps1` that fails if `cpa/config.example.yaml` contains `sk-`, `Bearer `, `access_token`, `refresh_token`, or `client_secret`, and passes when all runtime paths are ignored by Git.

- [ ] **Step 4: Run the boundary test**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test-cpa-config.ps1
git check-ignore cpa/config.yaml cpa/auths/example.json cpa/logs/example.log
```

Expected: the script passes and all three runtime paths are ignored.

- [ ] **Step 5: Commit the boundary**

```powershell
git add .gitignore cpa/config.example.yaml cpa/.gitkeep cpa/auths/.gitkeep cpa/logs/.gitkeep scripts/test-cpa-config.ps1
git commit -m "chore: add isolated CLIProxyAPI config boundaries"
```

### Task 2: Add the CPA Compose service and network wiring

**Files:**
- Modify: `compose.yaml`
- Modify: `.env.example` or create root `.env.example` if absent
- Test: `scripts/test-compose-cpa.ps1`

- [ ] **Step 1: Define explicit root variables**

Add `CLI_PROXY_IMAGE`, `CLI_PROXY_HOST`, `CLI_PROXY_PORT`, `CLI_PROXY_CONFIG_PATH`, `CLI_PROXY_AUTH_PATH`, and `CLI_PROXY_LOG_PATH` to the root environment example. Use `eceasy/cli-proxy-api:latest`, `127.0.0.1`, and `8317` as documented defaults; paths must resolve to the repository `cpa/` directories.

- [ ] **Step 2: Add the `cpa` service**

Add a service named `cpa` to `compose.yaml` using `\${CLI_PROXY_IMAGE:-eceasy/cli-proxy-api:latest}`. Mount the example-resolved runtime paths to `/CLIProxyAPI/config.yaml`, `/root/.cli-proxy-api`, and `/CLIProxyAPI/logs`. Bind the API port to `127.0.0.1:\${CLI_PROXY_PORT:-8317}:8317`, keep the existing `adcraft-internal` network, and set `restart: unless-stopped`.

- [ ] **Step 3: Add API dependency and internal URL defaults**

Make the API service depend on `cpa` readiness. Add `LLM_BASE_URL` and `LLM_API_KEY` as explicit environment inputs without hard-coding a secret. Keep the existing `apps/api/.env` file as the source for the actual key and set the documented Compose default to `http://cpa:8317/v1`.

- [ ] **Step 4: Add Compose validation checks**

Create `scripts/test-compose-cpa.ps1` to run `docker compose config --quiet`, assert that the rendered service list contains `cpa`, assert that the rendered API environment contains `http://cpa:8317/v1`, and fail if the rendered config contains `sk-`, `Bearer `, or any non-empty OAuth token value.

- [ ] **Step 5: Run validation before building**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test-compose-cpa.ps1
docker compose config --services
```

Expected: configuration succeeds and lists `cpa`, `agent`, `api`, and `web`.

- [ ] **Step 6: Commit Compose wiring**

```powershell
git add compose.yaml .env.example scripts/test-compose-cpa.ps1
git commit -m "feat: add CLIProxyAPI compose sidecar"
```

### Task 3: Add setup and operational documentation

**Files:**
- Create: `docs/cliproxyapi-compose-setup_zh.md`
- Modify: `README_zh.md`

- [ ] **Step 1: Document first-time setup**

Document copying `cpa/config.example.yaml` to `cpa/config.yaml`, creating a CPA `api-keys` value, completing OAuth login through the CPA-supported flow, and confirming that OAuth files remain under `cpa/auths/`.

- [ ] **Step 2: Document AdCraft environment values**

Document these local-only values in `apps/api/.env`:

```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=http://cpa:8317/v1
LLM_API_KEY=<the-local-CPA-api-key>
```

Explain that the model variables must match CPA's exposed aliases and that image/video/audio providers remain separate.

- [ ] **Step 3: Document safe operations and troubleshooting**

Include exact commands for `docker compose up -d`, `docker compose ps`, `docker compose logs cpa`, `docker compose restart cpa`, and `docker compose down`. State that CPA management/API ports remain localhost-only and that OAuth files and API keys must never be committed or pasted into issue reports.

- [ ] **Step 4: Link the guide from the Chinese README**

Add a short “CLIProxyAPI 集成” section linking to the setup guide without claiming that subscription access is an official provider API or that all provider terms permit proxy use.

- [ ] **Step 5: Commit documentation**

```powershell
git add docs/cliproxyapi-compose-setup_zh.md README_zh.md
git commit -m "docs: explain CLIProxyAPI setup for AdCraft"
```

### Task 4: Build and verify the full Compose stack

**Files:**
- Modify: none
- Test: `scripts/test-compose-cpa.ps1`, Docker Compose runtime

- [ ] **Step 1: Create local runtime configuration without committing secrets**

Copy the example to `cpa/config.yaml`, set one locally generated CPA API key, ensure `cpa/auths/` exists, and set `LLM_BASE_URL=http://cpa:8317/v1` plus the same local key in `apps/api/.env`.

- [ ] **Step 2: Build and start the stack**

Run:

```powershell
docker compose build cpa
docker compose build
docker compose up -d --remove-orphans
```

Expected: all four services start without exposing CPA beyond localhost.

- [ ] **Step 3: Verify service health and network reachability**

Run:

```powershell
docker compose ps
docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://cpa:8317/v1/models', timeout=10).status)"
Invoke-WebRequest http://127.0.0.1:8080/ -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:8080/api/v1/health -UseBasicParsing
```

Expected: CPA is reachable from API, Web returns 200, and API health returns 200. A 401 from `/v1/models` is acceptable only when it proves the route is reachable and the configured key is intentionally absent; with the configured local key it must return 200.

- [ ] **Step 4: Verify Git scope and secret exclusion**

Run:

```powershell
git status --short
git check-ignore cpa/config.yaml cpa/auths/example.json cpa/logs/example.log apps/api/.env
```

Expected: runtime secrets are ignored and no credentials appear in the diff.

- [ ] **Step 5: Record final verification**

Capture the service list, HTTP status codes, and exact image tag used. Do not claim a provider request succeeded unless an authorized test account and model were configured; otherwise report only proxy reachability and AdCraft health.


