# inFlow Premium Enterprise - Remote Access & Cloudflare Tunnel Guide

This guide explains how to share and access your local inFlow Premium ERP (and PostgreSQL 16 database) from any device anywhere in the world using **Cloudflare Tunnel (`cloudflared`)**.

---

## ⚡ Option 1: Instant Quick Tunnel (5 Seconds — No Signup Needed)

Use this method to generate a quick, temporary HTTPS link to test on a phone, iPad, or remote laptop:

1. **Start the local server**:
   Double-click `run.bat` (Server starts on `http://localhost:5050`).
2. **Launch the Tunnel**:
   Double-click `share_online.bat`.
3. **Copy the generated HTTPS URL**:
   Cloudflare generates an encrypted public link:
   ```
   https://random-words.trycloudflare.com
   ```
4. Keep the `share_online.bat` terminal open while using the link.

---

## 🌐 Option 2: Permanent Custom Domain (24/7 Production Setup)

To connect your own domain (e.g. `pos.yourcompany.com`) so it stays online 24/7 without opening terminal windows:

### 1. Create Tunnel in Cloudflare Zero Trust
1. Log in to [dash.cloudflare.com](https://dash.cloudflare.com).
2. Go to **Zero Trust** → **Networks** → **Tunnels**.
3. Click **Create a tunnel** → Choose **Cloudflared** → Name it `inflow-pos`.

### 2. Install the Windows Connector Service
Under **Choose your environment**, select **Windows** (64-bit).
Copy the command provided or run option `[4]` in `deploy_bridge.bat` and paste your tunnel token:
```powershell
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" service install <YOUR_TOKEN>
```
Cloudflare Tunnel is now installed as a **Windows Background Service** that auto-starts on computer boot!

### 3. Add Public Hostname
In Cloudflare Tunnel settings under **Public Hostname**:
- **Subdomain**: `pos`
- **Domain**: `yourcompany.com`
- **Service Type**: `HTTP`
- **URL**: `localhost:5050`

Save and open `https://pos.yourcompany.com` on any smartphone, tablet, or PC worldwide!

---

## 🔄 GitHub Repository Synchronization

To push code changes to GitHub:
Double-click `deploy_bridge.bat` and choose option `[1]`.
It stages, commits, and pushes to both:
- `dukphichenda/Premium-Pos`
- `dukphichenda/inflow-premium`
