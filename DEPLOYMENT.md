# House Premiere League (HPL) — Production Deployment Guide

This guide provides step-by-step instructions for deploying the **House Premiere League (HPL) Cricket Scoring & Tournament Platform** into production across Linux servers, Docker containers, Cloud platforms, and Windows environments.

---

## 📋 Table of Contents
1. [Architecture & Concurrency Considerations](#-architecture--concurrency-considerations)
2. [Environment Configuration](#-environment-configuration)
3. [Option 1: Linux VPS Deployment (Systemd + Gunicorn + Nginx)](#-option-1-linux-vps-deployment-systemd--gunicorn--nginx)
4. [Option 2: Docker & Docker Compose Deployment](#-option-2-docker--docker-compose-deployment)
5. [Option 3: Cloud PaaS Deployment (Render / Railway / Fly.io)](#-option-3-cloud-paas-deployment)
6. [Option 4: Windows Server Deployment (Waitress + NSSM)](#-option-4-windows-server-deployment-waitress--nssm)
7. [Reverse Proxy & Server-Sent Events (SSE) Tuning](#-reverse-proxy--server-sent-events-sse-tuning)
8. [Database Backups & Disaster Recovery](#-database-backups--disaster-recovery)
9. [Post-Deployment Security Checklist](#-post-deployment-security-checklist)

---

## 🏗️ Architecture & Concurrency Considerations

Before deploying, keep these critical architectural details in mind:

- **Database Storage**: The platform uses SQLite (`data/cricket.db`) with Write-Ahead Logging (WAL) and foreign keys enabled.
  - **Requirement**: The `data/` folder must reside on a **persistent disk or volume**. Never store it on ephemeral filesystems.
- **Server-Sent Events (SSE)**: Live ball-by-ball updates stream to fans using long-lived HTTP connections (`/api/matches/<id>/stream` and `/api/matches/live/stream`).
  - **Requirement**: Use a **threaded or asynchronous WSGI server** (e.g. `gunicorn --worker-class gthread --workers 1 --threads 16` or `waitress-serve --threads=16`). Single-threaded sync workers will get blocked by SSE client connections.
  - **Process Memory**: In-memory pub/sub broadcasts (`broadcast_live_update()`) operate within the application process. Running a single multi-threaded process guarantees all connected live fans receive instant updates without needing external Redis infrastructure.
- **Reverse Proxy**: Nginx, Cloudflare, or AWS ALB must have buffering **disabled** for SSE routes so events are delivered with zero delay.

---

## ⚙️ Environment Configuration

Generate a production `.env` file in the project root:

```bash
cp .env.example .env
```

Generate a cryptographically secure `SECRET_KEY`:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Production `.env` Example:
```ini
# Application Mode
APP_ENV=production
PORT=8080

# Cryptographic Session Key (keep secret!)
SECRET_KEY=9f8a4b3c2d1e0f8a9b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b9c8d7e6f5a

# HTTPS Session Protection (Set to true when SSL/TLS is enabled)
SESSION_COOKIE_SECURE=true

# Initial Administrator Credentials (used on first startup)
ADMIN_EMAIL=admin@yourtournament.com
ADMIN_PASSWORD=YourStrongPasswordHere2026!

# Database Location (Default: data/cricket.db)
CRICKET_DB_PATH=data/cricket.db

# Optional: MongoDB Atlas sync URI (leave commented if using local SQLite only)
# MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net
```

---

## 🐧 Option 1: Linux VPS Deployment (Systemd + Gunicorn + Nginx)

Recommended for: Ubuntu 22.04 / 24.04 LTS or Debian 12 VPS (DigitalOcean Droplet, AWS EC2, Linode, Hetzner).

### Step 1: System Packages & Python Setup
```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv nginx sqlite3 git ufw

# Create dedicated application user
sudo useradd -m -s /bin/bash hpl
sudo su - hpl

# Clone repository
git clone <your-repository-url> /home/hpl/csdcsitcricket
cd /home/hpl/csdcsitcricket

# Create virtual environment and install dependencies
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Create .env and configure variables
cp .env.example .env
nano .env

# Verify integration tests
python -m unittest test_integration.py
exit
```

### Step 2: Configure Systemd Service
Create the service unit file:
```bash
sudo nano /etc/systemd/system/hpl-cricket.service
```

Paste the following configuration:
```ini
[Unit]
Description=HPL Cricket Tournament Platform
After=network.target

[Service]
User=hpl
Group=hpl
WorkingDirectory=/home/hpl/csdcsitcricket
Environment="PATH=/home/hpl/csdcsitcricket/venv/bin"
EnvironmentFile=/home/hpl/csdcsitcricket/.env
ExecStart=/home/hpl/csdcsitcricket/venv/bin/gunicorn \
    --workers 1 \
    --threads 16 \
    --worker-class gthread \
    --bind 127.0.0.1:8080 \
    --timeout 120 \
    --access-logfile /home/hpl/csdcsitcricket/data/access.log \
    --error-logfile /home/hpl/csdcsitcricket/data/error.log \
    server:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable hpl-cricket
sudo systemctl start hpl-cricket
sudo systemctl status hpl-cricket
```

### Step 3: Configure Nginx as Reverse Proxy
Create the Nginx server block:
```bash
sudo nano /etc/nginx/sites-available/cricket.conf
```

Paste the configuration:
```nginx
server {
    listen 80;
    server_name cricket.yourdomain.com;

    client_max_body_size 16M;

    # Static file direct serving (faster performance)
    location /css/ {
        alias /home/hpl/csdcsitcricket/css/;
        expires 7d;
        add_header Cache-Control "public, no-transform";
    }

    location /js/ {
        alias /home/hpl/csdcsitcricket/js/;
        expires 7d;
        add_header Cache-Control "public, no-transform";
    }

    location /images/ {
        alias /home/hpl/csdcsitcricket/images/;
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }

    location /font/ {
        alias /home/hpl/csdcsitcricket/font/;
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }

    # Real-time Server-Sent Events (SSE) streaming routes
    location ~* ^/api/.*/stream$ {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # CRITICAL for SSE: Disable all buffering & timeouts
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
        chunked_transfer_encoding on;
    }

    # Standard Application & API Proxy
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable site and test configuration:
```bash
sudo ln -s /etc/nginx/sites-available/cricket.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### Step 4: Install Let's Encrypt SSL/TLS Certificate
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d cricket.yourdomain.com
```

Certbot will automatically configure HTTPS and redirect HTTP traffic to HTTPS.

---

## 🐳 Option 2: Docker & Docker Compose Deployment

The repository includes a ready-to-run [Dockerfile](file:///c:/Users/gowth/Downloads/csdcsitcricket-master/Dockerfile) and [docker-compose.yml](file:///c:/Users/gowth/Downloads/csdcsitcricket-master/docker-compose.yml).

### Quick Start with Docker Compose:

1. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your SECRET_KEY and ADMIN credentials
   ```

2. **Launch container**:
   ```bash
   docker compose up -d --build
   ```

3. **Check health and logs**:
   ```bash
   docker compose ps
   docker compose logs -f
   ```

4. **Verify database persistence**:
   The named volume `cricket-data` mounts to `/app/data` inside the container. Match data and scorecards persist across container rebuilds and restarts.

To inspect the volume:
```bash
docker volume inspect hpl-cricket-data
```

---

## ☁️ Option 3: Cloud PaaS Deployment

### A. Deploying to Render.com
1. Create a new **Web Service** connected to your repository.
2. Select **Docker** environment or **Python 3**.
3. If using Python native runtime:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn --workers 1 --threads 16 --bind 0.0.0.0:$PORT server:app`
4. **Persistent Disk (MANDATORY)**:
   - Go to service **Disks** tab.
   - Add a Disk named `hpl-data`, mount path `/app/data` (size: 1 GB is plenty).
5. **Environment Variables**:
   - `APP_ENV=production`
   - `SECRET_KEY=<your-secret-key>`
   - `SESSION_COOKIE_SECURE=true`

### B. Deploying to Railway.app
1. Create a new Project from your GitHub repository.
2. Railway detects the `Dockerfile` automatically.
3. In **Settings -> Volumes**, click **Add Volume**:
   - Mount Path: `/app/data`
4. In **Variables**, add:
   - `PORT=8080`
   - `SECRET_KEY=<your-secret-key>`
   - `SESSION_COOKIE_SECURE=true`

### C. Deploying to Fly.io
1. Install flyctl and run `fly launch`.
2. Create persistent volume:
   ```bash
   fly volumes create hpl_data --size 1
   ```
3. Update `fly.toml` to mount the volume:
   ```toml
   [mounts]
     source = "hpl_data"
     destination = "/app/data"
   ```
4. Deploy: `fly deploy`.

---

## 🪟 Option 4: Windows Server Deployment (Waitress + NSSM)

Waitress is a production-quality, multi-threaded pure Python WSGI server designed for Windows.

### Step 1: Install Dependencies
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Step 2: Test Run with Waitress
```powershell
waitress-serve --listen=0.0.0.0:8080 --threads=16 server:app
```

### Step 3: Install as Windows Service using NSSM
Download [NSSM (Non-Sucking Service Manager)](https://nssm.cc/) and execute in PowerShell (Administrator):

```powershell
nssm install HPLCricket "C:\Users\gowth\Downloads\csdcsitcricket-master\venv\Scripts\waitress-serve.exe"
nssm set HPLCricket Arguments "--listen=0.0.0.0:8080 --threads=16 server:app"
nssm set HPLCricket AppDirectory "C:\Users\gowth\Downloads\csdcsitcricket-master"
nssm set HPLCricket AppStdout "C:\Users\gowth\Downloads\csdcsitcricket-master\data\service_out.log"
nssm set HPLCricket AppStderr "C:\Users\gowth\Downloads\csdcsitcricket-master\data\service_err.log"
nssm start HPLCricket
```

---

## 🔄 Reverse Proxy & Server-Sent Events (SSE) Tuning

If live score updates do not appear instantly on spectator browsers without refreshing, your proxy or CDN is buffering the responses.

### 1. Nginx SSE Directives
Ensure these directives are inside the SSE location block:
```nginx
proxy_buffering off;
proxy_cache off;
proxy_read_timeout 86400s;
proxy_send_timeout 86400s;
proxy_set_header Connection '';
proxy_http_version 1.1;
chunked_transfer_encoding on;
```

### 2. Cloudflare Settings
If routing traffic through Cloudflare:
- Go to **Rules** -> **Page Rules** or **Configuration Rules**.
- Create a rule for `cricket.yourdomain.com/api/*/stream*`:
  - **Cache Level**: Bypass
  - **Disable Performance**: Rocket Loader Off
  - Cloudflare natively supports SSE when buffering is disabled by server headers (`X-Accel-Buffering: no`, already sent by `server.py`).

---

## 💾 Database Backups & Disaster Recovery

SQLite supports online non-blocking hot backups while matches are being actively scored.

### 1. Manual Backup Command
```bash
sqlite3 data/cricket.db ".backup 'data/cricket_backup_$(date +%Y%m%d_%H%M%S).db'"
```

### 2. Automated Daily Cron Job (Linux)
Create `/usr/local/bin/backup-cricket.sh`:
```bash
#!/bin/bash
BACKUP_DIR="/home/hpl/backups"
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
sqlite3 /home/hpl/csdcsitcricket/data/cricket.db ".backup '$BACKUP_DIR/cricket_$TIMESTAMP.db'"

# Keep only backups from the last 14 days
find "$BACKUP_DIR" -name "cricket_*.db" -type f -mtime +14 -delete
```

Make executable and add to crontab:
```bash
chmod +x /usr/local/bin/backup-cricket.sh
crontab -e
# Run daily at 3:00 AM
0 3 * * * /usr/local/bin/backup-cricket.sh
```

---

## 🔒 Post-Deployment Security Checklist

1. [ ] **Rotate Secret Key**: Ensure `.env` has a unique random string for `SECRET_KEY`.
2. [ ] **Update Default Admin Credentials**:
   - Access `/admin/login` using initial credentials.
   - Navigate to **Admin Settings** -> **Change Password** and update immediately.
3. [ ] **Set `SESSION_COOKIE_SECURE=true`**: Ensures authentication cookies are only transmitted over HTTPS.
4. [ ] **Configure Firewall (UFW)**:
   ```bash
   sudo ufw default deny incoming
   sudo ufw default allow outgoing
   sudo ufw allow ssh
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw enable
   ```
   *(Keep port 8080 closed to the public; only accessible through Nginx reverse proxy).*
5. [ ] **Verify Health Endpoint**:
   Check `https://cricket.yourdomain.com/api/health` returns `{"status":"healthy"}`.
6. [ ] **Verify Live Updates**:
   Open a spectator tab on `/match/<id>` and an admin scorer tab on `/admin`. Input a ball and confirm the spectator screen reflects the ball instantly without page reload.
