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

---

## ☁️ Option 3: Deploy to Hostinger (Full System & Database Guide)

This section provides the complete step-by-step instructions to deploy **inFlow Premium ERP** and migrate your **PostgreSQL 16 database** to **Hostinger VPS** (Ubuntu Linux) with Nginx, Gunicorn, and Free SSL.

### 📋 Prerequisites & Architecture
- **Server:** Hostinger KVM VPS (KVM 1 or KVM 2 recommended) running **Ubuntu 22.04 LTS** or **24.04 LTS**.
- **Web Server:** Nginx (Reverse Proxy & Static Asset Caching).
- **Application Server:** Gunicorn (WSGI) managed by `systemd`.
- **Database:** PostgreSQL 16 (restored from your local dump).
- **SSL Certificate:** Free Let's Encrypt SSL via Certbot.

---

### Step 1: Export Local PostgreSQL Database
1. In your local project folder, double-click **`backup_database.bat`** (or run Option `[5]` in `deploy_bridge.bat`).
2. This generates a complete SQL dump of your PostgreSQL database:
   ```
   F:\inflow premium\inflow_premium_backup.sql
   ```
   *(File size is ~16 MB containing all products, branches, categories, customers, inventory, and sales orders).*

---

### Step 2: Push Latest Code to GitHub
1. In your local project folder, double-click **`deploy_bridge.bat`** and select **`[1]`**.
2. Confirm your latest code is updated on GitHub (`dukphichenda/Premium-Pos`).

---

### Step 3: Connect to Hostinger VPS
1. Open PowerShell or Terminal on your PC:
   ```bash
   ssh root@<YOUR_HOSTINGER_SERVER_IP>
   ```
2. Update the VPS package manager:
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

---

### Step 4: Install System Dependencies
Install Python 3, PostgreSQL, Nginx, and Git on your Hostinger VPS:
```bash
sudo apt install -y python3 python3-pip python3-venv postgresql postgresql-contrib nginx git curl
```

---

### Step 5: Configure PostgreSQL on Hostinger & Restore Database

1. **Create the Database and User on Hostinger:**
   ```bash
   sudo -i -u postgres
   psql
   ```
   Inside the PostgreSQL prompt (`postgres=#`), run:
   ```sql
   CREATE DATABASE inflow_premium;
   CREATE USER inflow_user WITH ENCRYPTED PASSWORD 'ChangeThisToAStrongPassword123!';
   GRANT ALL PRIVILEGES ON DATABASE inflow_premium TO inflow_user;
   ALTER DATABASE inflow_premium OWNER TO inflow_user;
   \q
   exit
   ```

2. **Clone your repository:**
   ```bash
   sudo mkdir -p /var/www/inflow
   sudo git clone https://github.com/dukphichenda/Premium-Pos.git /var/www/inflow
   cd /var/www/inflow
   ```

3. **Restore the database on Hostinger VPS:**
   Since `inflow_premium_backup.sql` is already in the repository, simply run:
   ```bash
   sudo -u postgres psql -d inflow_premium -f /var/www/inflow/inflow_premium_backup.sql
   ```
   *All tables, schemas, and records will be instantly restored.*

---

### Step 6: Configure inFlow Premium Application


2. **Create Python virtual environment & install requirements:**
   ```bash
   sudo python3 -m venv venv
   sudo ./venv/bin/pip install --upgrade pip
   sudo ./venv/bin/pip install -r requirements.txt
   ```

3. **Create the production environment file (`.env`):**
   ```bash
   sudo nano /var/www/inflow/.env
   ```
   Paste the following:
   ```env
   SECRET_KEY=inflow_premium_prod_super_secret_key_2026
   PORT=5050
   HOST=127.0.0.1
   FLASK_DEBUG=false
   DATABASE_URL=postgresql://inflow_user:ChangeThisToAStrongPassword123!@127.0.0.1:5432/inflow_premium
   ```
   *(Press `Ctrl + O` then `Enter` to save, and `Ctrl + X` to exit).*

4. **Set appropriate directory permissions:**
   ```bash
   sudo chown -R www-data:www-data /var/www/inflow
   sudo chmod -R 755 /var/www/inflow
   ```

---

### Step 7: Create 24/7 Systemd Background Service

1. **Create the systemd service file:**
   ```bash
   sudo nano /etc/systemd/system/inflow.service
   ```
   Paste the configuration:
   ```ini
   [Unit]
   Description=inFlow Premium Enterprise WSGI Server
   After=network.target postgresql.service

   [Service]
   User=www-data
   Group=www-data
   WorkingDirectory=/var/www/inflow
   EnvironmentFile=/var/www/inflow/.env
   ExecStart=/var/www/inflow/venv/bin/gunicorn -w 4 -b 127.0.0.1:5050 wsgi:app
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

2. **Enable and start the service:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable inflow
   sudo systemctl start inflow
   ```

3. **Verify the service status:**
   ```bash
   sudo systemctl status inflow
   ```
   *(You should see `Active: active (running)` in green).*

---

### Step 8: Configure Nginx & Connect Your Domain

1. **Create Nginx site configuration:**
   ```bash
   sudo nano /etc/nginx/sites-available/inflow
   ```
   Paste:
   ```nginx
   server {
       listen 80;
       server_name yourdomain.com www.yourdomain.com;

       client_max_body_size 50M;

       location /static/ {
           alias /var/www/inflow/static/;
           expires 30d;
           add_header Cache-Control "public, no-transform";
       }

       location / {
           proxy_pass http://127.0.0.1:5050;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```
   *(Replace `yourdomain.com` with your actual domain or Hostinger server IP).*

2. **Activate the site:**
   ```bash
   sudo ln -s /etc/nginx/sites-available/inflow /etc/nginx/sites-enabled/
   sudo rm -f /etc/nginx/sites-enabled/default
   sudo nginx -t
   sudo systemctl restart nginx
   ```

3. **Install Free SSL with Let's Encrypt:**
   ```bash
   sudo apt install -y certbot python3-certbot-nginx
   sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
   ```
   Certbot will automatically install the SSL certificate and configure HTTPS redirection!

---

### 🔄 Updating inFlow in the Future
Whenever you push changes from your PC with `deploy_bridge.bat`:
Connect to your Hostinger VPS and run:
```bash
cd /var/www/inflow
sudo git pull origin main
sudo systemctl restart inflow
```
Your live production system will be updated in seconds without downtime!

