#!/bin/bash
# ==============================================================================
# inFlow Premium Enterprise - Hostinger VPS Automated 1-Click Installer
# Supported OS: Ubuntu 20.04 / 22.04 / 24.04 LTS, Debian 11 / 12
# ==============================================================================

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}==============================================================================${NC}"
echo -e "${BLUE}        inFlow Premium Enterprise - Hostinger VPS Deployment Script        ${NC}"
echo -e "${BLUE}==============================================================================${NC}"
echo ""

# Ensure script is run as root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}[ERROR] Please run this script as root (sudo bash hostinger_deploy.sh)${NC}"
  exit 1
fi

APP_DIR="/var/www/inflow"
REPO_URL="https://github.com/dukphichenda/Premium-Pos.git"
DB_NAME="inflow_premium"
DB_USER="inflow_user"

# Prompt for Domain Name (optional)
read -p "Enter your Domain Name (e.g. pos.example.com) or press Enter to use server IP: " DOMAIN_NAME
if [ -z "$DOMAIN_NAME" ]; then
    SERVER_IP=$(curl -s https://api.ipify.org || hostname -I | awk '{print $1}')
    DOMAIN_NAME="$SERVER_IP"
    echo -e "${YELLOW}No domain provided. Deploying with Server IP: $DOMAIN_NAME${NC}"
fi

# Prompt for DB Password (optional)
DEFAULT_DB_PASS=$(openssl rand -hex 12 2>/dev/null || echo "InFlowProdSecure2026!")
read -p "Enter PostgreSQL password for '$DB_USER' [default: $DEFAULT_DB_PASS]: " DB_PASS
if [ -z "$DB_PASS" ]; then
    DB_PASS="$DEFAULT_DB_PASS"
fi

echo ""
echo -e "${GREEN}[1/8] Updating package repository & installing system dependencies...${NC}"
export DEBIAN_FRONTEND=noninteractive
apt update -y
apt install -y python3 python3-pip python3-venv postgresql postgresql-contrib nginx git curl ufw

echo -e "${GREEN}[2/8] Setting up Application Directory at $APP_DIR...${NC}"
if [ ! -d "$APP_DIR" ]; then
    mkdir -p "$APP_DIR"
    git clone "$REPO_URL" "$APP_DIR"
else
    cd "$APP_DIR"
    if [ -d ".git" ]; then
        echo -e "${BLUE}Existing repository detected. Pulling latest changes...${NC}"
        git pull origin main || true
    fi
fi
cd "$APP_DIR"

echo -e "${GREEN}[3/8] Configuring PostgreSQL Database & User...${NC}"
systemctl enable postgresql
systemctl start postgresql

sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1 || \
sudo -u postgres psql -c "CREATE DATABASE $DB_NAME;"

sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname = '$DB_USER'" | grep -q 1 || \
sudo -u postgres psql -c "CREATE USER $DB_USER WITH ENCRYPTED PASSWORD '$DB_PASS';"

sudo -u postgres psql -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASS';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"
sudo -u postgres psql -c "ALTER DATABASE $DB_NAME OWNER TO $DB_USER;"

echo -e "${GREEN}[4/8] Restoring PostgreSQL Schema & Initial Data...${NC}"
if [ -f "$APP_DIR/inflow_premium_backup.sql" ]; then
    echo -e "${BLUE}Restoring from $APP_DIR/inflow_premium_backup.sql...${NC}"
    sudo -u postgres psql -d "$DB_NAME" -f "$APP_DIR/inflow_premium_backup.sql" || true
else
    echo -e "${YELLOW}Warning: inflow_premium_backup.sql not found, schema will be provisioned on startup.${NC}"
fi

# Fix table ownership & sequence permissions
sudo -u postgres psql -d "$DB_NAME" -c "
GRANT ALL ON SCHEMA public TO $DB_USER;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO $DB_USER;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO $DB_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $DB_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO $DB_USER;
DO \$\$ 
DECLARE r RECORD;
BEGIN
    FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
        EXECUTE 'ALTER TABLE public.' || quote_ident(r.tablename) || ' OWNER TO $DB_USER;';
    END LOOP;
    FOR r IN (SELECT sequence_name FROM information_schema.sequences WHERE sequence_schema = 'public') LOOP
        EXECUTE 'ALTER SEQUENCE public.' || quote_ident(r.sequence_name) || ' OWNER TO $DB_USER;';
    END LOOP;
END \$\$;
"

echo -e "${GREEN}[5/8] Setting up Python virtual environment & packages...${NC}"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo -e "${GREEN}[6/8] Configuring Production Environment (.env)...${NC}"
PROD_SECRET=$(openssl rand -hex 24 2>/dev/null || echo "inflow_prod_secret_token_2026_super_key")
cat <<EOF > "$APP_DIR/.env"
SECRET_KEY=$PROD_SECRET
PORT=5050
HOST=127.0.0.1
FLASK_DEBUG=false
DATABASE_URL=postgresql://$DB_USER:$DB_PASS@127.0.0.1:5432/$DB_NAME
EOF

chown -R www-data:www-data "$APP_DIR"
chmod -R 755 "$APP_DIR"
chmod 600 "$APP_DIR/.env"

echo -e "${GREEN}[7/8] Configuring 24/7 Systemd Service (inflow.service)...${NC}"
cat <<EOF > /etc/systemd/system/inflow.service
[Unit]
Description=inFlow Premium Enterprise WSGI Server
After=network.target postgresql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/gunicorn -w 4 -b 127.0.0.1:5050 --access-logfile - --error-logfile - wsgi:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable inflow
systemctl restart inflow

echo -e "${GREEN}[8/8] Configuring Nginx Reverse Proxy & Firewall...${NC}"
cat <<EOF > /etc/nginx/sites-available/inflow
server {
    listen 80;
    server_name $DOMAIN_NAME;

    client_max_body_size 50M;

    location /static/ {
        alias $APP_DIR/static/;
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }

    location / {
        proxy_pass http://127.0.0.1:5050;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 120s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/inflow /etc/nginx/sites-enabled/inflow
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx

# Allow HTTP and HTTPS through firewall
ufw allow 'Nginx Full' || true
ufw allow 22/tcp || true

echo ""
echo -e "${BLUE}==============================================================================${NC}"
echo -e "${GREEN}🎉 inFlow Premium Successfully Deployed on Hostinger VPS!${NC}"
echo -e "${BLUE}==============================================================================${NC}"
echo -e "Web App URL     : ${GREEN}http://$DOMAIN_NAME${NC}"
echo -e "Database User   : $DB_USER"
echo -e "Database Name   : $DB_NAME"
echo -e "Database Pass   : $DB_PASS"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo -e "1. Open in your browser: ${GREEN}http://$DOMAIN_NAME${NC}"
echo -e "2. To enable Free SSL (HTTPS with Let's Encrypt), run:"
echo -e "   ${BLUE}sudo apt install -y certbot python3-certbot-nginx${NC}"
echo -e "   ${BLUE}sudo certbot --nginx -d $DOMAIN_NAME${NC}"
echo -e "3. To check logs anytime:"
echo -e "   ${BLUE}sudo journalctl -u inflow -f${NC}"
echo -e "4. To update code in the future:"
echo -e "   ${BLUE}cd /var/www/inflow && sudo git pull origin main && sudo systemctl restart inflow${NC}"
echo -e "${BLUE}==============================================================================${NC}"
