[简体中文](getting-started_zh.md)

# Start Here: Run AdCraft

Follow these four steps after cloning AdCraft or downloading and extracting the project ZIP.

## 1. Open the AdCraft folder

Make sure the project folder contains `apps`, `docs`, `scripts`, and `compose.yaml`. Keep the whole project together; do not move only the frontend or backend folder.

## 2. Choose how to deploy

AdCraft can run with or without Docker. Both methods start the same three parts: Agent Runtime, API, and Web.

### Give the deployment to a desktop Agent

Open your desktop Agent, give it access to the AdCraft folder, and ask it to follow one of these files until all three services are healthy and it gives you the Web address:

- With Docker: [Agent Runbook: Deploy AdCraft with Docker](deployment-with-docker-agent.md)
- Without Docker: [Agent Runbook: Deploy AdCraft Without Docker](deployment-without-docker-agent.md)

For example, tell the Agent:

> Deploy this AdCraft project by following `docs/deployment-with-docker-agent.md`. Continue until Agent Runtime, API, and Web are healthy, then give me the local Web address. Ask me only when administrator approval, a password, restart, or desktop setting is required.

Use the non-Docker Agent document instead when you want dependencies installed directly on the computer.

### Deploy it yourself

Choose the matching user guide and follow it from the beginning:

- With Docker: [Deploy AdCraft](deployment-with-docker.md)
- Without Docker: [Native Deployment Without Docker](deployment-without-docker.md)

Docker keeps project dependencies in containers. The non-Docker method installs Node.js, uv, FFmpeg, and project dependencies directly on the computer.

## 3. Install the optional Recommended Assets

Open the [AdCraft Releases page](https://github.com/GML-MMGroup/AdCraft/releases), find `recommended-assets-v1.0.0`, and download:

- `adcraft-recommended-assets-v1.0.0.zip`
- `adcraft-recommended-assets-v1.0.0.zip.sha256`

Then follow [Use the AdCraft Recommended Assets Library](recommended-assets.md) to verify and extract the package. You do not need to upload these assets through the browser.

You can deploy AdCraft before or after downloading the assets.

## 4. Open AdCraft and start using it

When deployment finishes, open the local Web address shown in the terminal or returned by the Agent. It usually begins with `http://127.0.0.1:`.

Open **API Space**, enter the API Key required by your provider, and save it. If you installed the asset package, open **Recommended Assets** and wait for the catalog to become ready.

Keep API Keys and `.env` files private. Do not commit them to Git or send them to other people.
