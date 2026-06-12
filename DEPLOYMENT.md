# 🚀 Hugging Face Space Deployment Guide (Discord Interactions Endpoint)

This guide takes you through deploying the unified FastAPI Discord Webhook backend. Because Hugging Face blocks outbound standard connections to `discord.com`, this bot utilizes a **pure incoming HTTP POST Interaction architecture** which requires **ZERO OUTBOUND CALLS**.

---

## 🛠️ Step 1: Gather Discord Credentials
Go to the **[Discord Developer Portal](https://discord.com/developers/applications)**, click your Application, and copy the following parameters:
1. **Application ID** (Found under General Information)
2. **Public Key** (Found under General Information)
3. **Bot Token** (Found under Bot tab)

---

## 🔑 Step 2: Configure Hugging Face Secrets
In your Hugging Face Space, navigate to **Settings** > **Variables and Secrets** > **New Secret**, and store the following environment variables:

| Secret Name | Description | Example / Location |
| :--- | :--- | :--- |
| `PUBLIC_KEY` | Hex Public Key used to cryptographically verify incoming Discord POST signatures. | *Copy from Developer Portal* |
| `DISCORD_TOKEN` | Required Bot Token for validation. | *Copy from Bot tab* |

---

## 🌐 Step 3: Set Webhook URL on Discord
Once your Space builds and logs a successful deployment, retrieve your Hugging Face Space's **Direct App URL** (e.g. `https://<space-username>-<space-name>.hf.space`).

1. Copy your Direct App URL and append `/interactions` to it, forming:
   `https://<space-username>-<space-name>.hf.space/interactions`
2. Go to your **[Discord Developer Portal](https://discord.com/developers/applications)**.
3. Select your application, scroll down to the **Interactions Endpoint URL** field under **General Information**.
4. Paste the URL into the field and click **Save Changes**.
5. Discord will automatically send a `PING` POST request to test verification. Our backend will cryptographically authorize it instantly and reply with `PONG`.

---

## 📣 Step 4: Register Slash Commands
Since outbound API requests are blocked, you can register slash commands directly through the Discord Developer Portal using third-party command command builders (like **[Discord Slash Command Builder](https://discord-command-builder.com/)**), or simply register them inside Discord.

The three configured slash commands for this Space are:
1. `/set-profile` (Option: `language` [String, Autocomplete: True])
2. `/vibecheck` (No options)
3. `/sync_server` (No options)
