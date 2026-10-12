# inFlow Premium Enterprise - GitHub & Vercel Deployment Guide

This guide explains how to use the deployment bridge to push inFlow Premium to GitHub and host it live on Vercel.

---

## 🚀 1. The Deployment Bridge

The project includes an automated deployment bridge script:
- **Windows Batch**: Double-click `deploy_bridge.bat` or run `.\deploy_bridge.bat` from terminal.
- **PowerShell**: Run `powershell -ExecutionPolicy Bypass -File .\deploy_bridge.ps1`

### What the Bridge Does:
1. **Checks Git status** for any new or modified files.
2. **Prompts for an optional commit message** (or creates an automatic timestamped message).
3. **Stages and commits** all changes cleanly.
4. **Pushes to your GitHub repositories**:
   - `origin` (`https://github.com/dukphichenda/Premium-Pos`)
   - `inflow-repo` (`https://github.com/dukphichenda/inflow-premium`)
5. **Triggers Vercel deployment** automatically if GitHub integration is active, or prompts to run `vercel --prod` via CLI.

---

## 🌐 2. Deploying on Vercel (Step-by-Step)

### Option A: Automatic Git-Connected Deployment (Recommended)
1. Go to [vercel.com](https://vercel.com/) and sign in with your GitHub account (`dukphichenda`).
2. Click **"Add New..."** → **"Project"** ([vercel.com/new](https://vercel.com/new)).
3. Find and select your GitHub repository:
   - `dukphichenda/Premium-Pos` or `dukphichenda/inflow-premium`
4. In the Project Configuration:
   - **Framework Preset**: Other (Vercel automatically detects Python serverless from `vercel.json` and `api/index.py`)
   - **Root Directory**: `./` (leave default)
5. Under **Environment Variables**, add:
   - `DATABASE_URL`: Your cloud PostgreSQL connection string (see Section 3 below).
   - `SECRET_KEY`: Any secure random string (e.g. `inflow_prod_secret_2026`).
6. Click **"Deploy"**.
7. Vercel will build the project and give you a live production URL (e.g. `https://inflow-premium.vercel.app`).
8. **From now on**: Every time you run `deploy_bridge.bat` or `git push`, Vercel deploys your changes automatically within seconds!

---

### Option B: Deploy via Vercel CLI
If you prefer deploying directly from your computer terminal:
```bash
# 1. Log in to Vercel (one time only)
cmd /c vercel login

# 2. Deploy to production
cmd /c vercel --prod
```

---

## 🗄️ 3. Cloud Database Configuration

On your local machine, the app connects to local PostgreSQL (`localhost:5432`). On Vercel, serverless functions run in the cloud, so they require an accessible cloud PostgreSQL database.

### Free Cloud PostgreSQL Providers (Takes 60 seconds to set up):
1. **[Neon.tech](https://neon.tech/)** (Recommended - Serverless Postgres, generous free tier):
   - Sign up with GitHub.
   - Click "New Project" → Name it `inflow-premium`.
   - Copy the Connection String URI:
     `postgresql://username:password@ep-xyz.us-east-2.aws.neon.tech/inflow_premium?sslmode=require`
2. **[Supabase](https://supabase.com/)**:
   - Create a project → Go to Settings → Database → Connection String (URI).
3. **[Vercel Postgres](https://vercel.com/docs/storage/vercel-postgres)**:
   - Directly inside your Vercel Dashboard → Storage tab → Create Database → Attach to Project. Vercel sets `POSTGRES_URL` automatically!

### Automatic Database Initialization:
When your cloud database is connected, inFlow Premium's `init_db()` automatically runs `schema.sql` on first startup:
- Creates all tables, sequences, indexes, and branches.
- Sets up default company settings and warehouse.
- Seeds default Administrator accounts:
  - **Username**: `admin` or `chenda`
  - **Password**: `123`

---

## 📂 4. Project Serverless Architecture for Vercel

```
inflow-premium/
├── api/
│   └── index.py             # Serverless WSGI entrypoint for Vercel (@vercel/python)
├── static/                  # Static assets (CSS, JS, icons) served by Vercel CDN
├── templates/               # Jinja2 HTML templates
├── routes/                  # Flask blueprints (sales, purchase, products, reports, etc.)
├── database.py              # PostgreSQL pooled database driver with cloud DSN support
├── config.py                # Environment configuration (DATABASE_URL / POSTGRES_URL)
├── requirements.txt         # Python dependencies (Flask, psycopg2-binary, etc.)
├── vercel.json              # Vercel routing rules & rewrites
├── .vercelignore            # Files excluded from serverless bundle
├── deploy_bridge.bat        # Windows Batch deployment tool
└── deploy_bridge.ps1        # PowerShell deployment tool
```
