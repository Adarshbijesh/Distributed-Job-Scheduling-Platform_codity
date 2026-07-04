# Deployment Guide - Deploy to Production (Free)

## Overview

Deploy your distributed job scheduler online using **free services**. This guide covers:
- Backend API hosting
- Database setup
- Worker deployment
- Domain configuration
- Monitoring

---

## Option 1: Render.com (Recommended - Easiest)

**Why Render?**
- Free tier with 750 compute hours/month
- PostgreSQL database included
- GitHub integration
- Auto-deploys on push
- No credit card required initially

### Step 1: Prepare Code for Production

Update `scheduler/database.py`:

```python
import os
from sqlalchemy import create_engine

# Use environment variable for database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./scheduler.db"  # fallback for local dev
)

# Handle PostgreSQL URL format (Render adds "postgresql://")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    future=True,
)
```

Update `scheduler/auth.py`:

```python
import os

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
# Change to random key in production:
# SECRET_KEY = "your-random-64-char-string"
```

### Step 2: Create Production Requirements

Create `requirements-prod.txt`:

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
sqlalchemy==2.0.36
pydantic==2.10.4
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
bcrypt==4.0.1
python-multipart==0.0.20
email-validator==2.2.0
pytest==8.3.3
psycopg2-binary==2.9.9  # PostgreSQL driver
python-dotenv==1.0.0
gunicorn==21.2.0  # Production WSGI server
```

### Step 3: Create Render Configuration

Create `render.yaml` in project root:

```yaml
services:
  - type: web
    name: job-scheduler
    env: python
    plan: free
    buildCommand: "pip install -r requirements-prod.txt"
    startCommand: "gunicorn -w 4 -k uvicorn.workers.UvicornWorker scheduler.main:app --bind 0.0.0.0:$PORT"
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: job-scheduler-db
          property: connectionString
      - key: SECRET_KEY
        generateValue: true
      - key: PYTHON_VERSION
        value: "3.11"

databases:
  - name: job-scheduler-db
    plan: free
    postgreSQL:
      version: 15
```

### Step 4: Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit - ready for deployment"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/job-scheduler.git
git push -u origin main
```

### Step 5: Deploy on Render

1. Go to https://render.com
2. Sign up with GitHub
3. Click "New" → "Service"
4. Connect GitHub repo (job-scheduler)
5. Select branch: `main`
6. Choose plan: **Free**
7. Click "Create Web Service"
8. Render builds and deploys automatically

**Your app is live at**: `https://job-scheduler-xyz.onrender.com`

### Step 6: Deploy Worker

Create `render-worker.yaml`:

```yaml
services:
  - type: background
    name: job-scheduler-worker
    env: python
    plan: free
    buildCommand: "pip install -r requirements-prod.txt"
    startCommand: "python -m scheduler.worker --worker-name render-worker --concurrency 4"
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: job-scheduler-db
          property: connectionString
```

Or manually create a separate service:
1. Click "New" → "Background Worker"
2. Same GitHub repo
3. Start command: `python -m scheduler.worker --worker-name render-worker --concurrency 4`
4. Use same PostgreSQL database

---

## Option 2: Railway.app

**Why Railway?**
- $5/month free credit (generous)
- Simple GitHub deployment
- PostgreSQL included
- Good for hobby projects

### Setup Steps

1. Go to https://railway.app
2. Sign in with GitHub
3. Click "Create New Project"
4. Import GitHub repo (job-scheduler)
5. Add PostgreSQL plugin
6. Add environment variables:
   - `DATABASE_URL` → auto-filled by Railway
   - `SECRET_KEY` → generate random value
7. Deploy

**Cost**: ~$5/month for persistent services (within free tier)

---

## Option 3: Fly.io

**Why Fly.io?**
- Generous free tier
- Global deployment
- Good for distributed systems
- PostgreSQL support

### Setup Steps

1. Install flyctl: https://fly.io/docs/hands-on/install-flyctl/
2. Sign up: `flyctl auth signup`
3. Create `fly.toml`:

```toml
app = "job-scheduler"
primary_region = "sjc"

[build]
  builder = "paketobuildpacks"

[env]
  DATABASE_URL = "postgresql://..."
  SECRET_KEY = "your-secret-key"

[[services]]
  protocol = "tcp"
  internal_port = 8000
  processes = ["app"]

  [[services.ports]]
    port = 80
    handlers = ["http"]

  [[services.ports]]
    port = 443
    handlers = ["tls", "http"]

[processes]
  app = "gunicorn -w 4 -k uvicorn.workers.UvicornWorker scheduler.main:app"
  worker = "python -m scheduler.worker --worker-name fly-worker --concurrency 4"
```

4. Deploy: `flyctl launch`
5. Create database: `flyctl postgres create`
6. Deploy: `flyctl deploy`

---

## Option 4: Replit (Easiest for Beginners)

**Why Replit?**
- No setup needed
- Code + hosting in browser
- Free tier includes always-on option ($7/month)
- Perfect for learning

### Setup

1. Go to https://replit.com
2. Click "Import" → GitHub repo
3. Replit auto-detects Python project
4. Create `.replit` file:

```
run = "uvicorn scheduler.main:app --host 0.0.0.0 --port 8000"
```

5. Click "Run"
6. Share link with anyone

**Limitations**: 
- Free tier sleeps after inactivity
- $7/month for always-on
- SQLite only (no persistent file between sessions)

---

## Option 5: PythonAnywhere

**Why PythonAnywhere?**
- Python-specific hosting
- Web app + background tasks
- Free tier available
- 100MB storage

### Setup

1. Sign up: https://www.pythonanywhere.com
2. Upload project or clone from GitHub
3. Set up virtual environment
4. Configure web app (FastAPI)
5. Set up background workers
6. Your app at `yourname.pythonanywhere.com`

**Cost**: Free (with limitations)

---

## Database Options (Free PostgreSQL)

### Neon (Recommended for Free Tier)
- 3 projects, 10GB storage free
- Serverless PostgreSQL
- Sign up: https://neon.tech

```python
# Use this connection string in production
DATABASE_URL = "postgresql://user:password@host.neon.tech/dbname?sslmode=require"
```

### Supabase
- Free PostgreSQL (500MB)
- Built-in backups
- Sign up: https://supabase.com

### Railway PostgreSQL
- Auto-included with deployment
- Included in free tier

### AWS RDS Free Tier
- 750 hours/month free
- 20GB storage
- Amazon account required

---

## Full Deployment Walkthrough (Render)

### 1. Prepare Repository

```bash
# Create .gitignore
echo "scheduler.db
.venv/
__pycache__/
*.pyc
.env
.env.local" > .gitignore

# Update requirements
cp requirements.txt requirements-prod.txt
echo "psycopg2-binary==2.9.9" >> requirements-prod.txt
echo "gunicorn==21.2.0" >> requirements-prod.txt

# Commit changes
git add .
git commit -m "Production ready - added PostgreSQL support"
git push
```

### 2. Create Render Account

- Visit https://render.com
- Sign up with GitHub
- Grant GitHub permissions

### 3. Create Web Service

```
1. Dashboard → New → Web Service
2. Connect GitHub → Select job-scheduler repo
3. Configure:
   - Name: job-scheduler
   - Environment: Python
   - Build Command: pip install -r requirements-prod.txt
   - Start Command: gunicorn -w 4 -k uvicorn.workers.UvicornWorker scheduler.main:app --bind 0.0.0.0:8000
   - Plan: Free
4. Click "Create Web Service"
```

### 4. Create PostgreSQL Database

```
1. Dashboard → New → PostgreSQL
2. Configure:
   - Name: job-scheduler-db
   - Plan: Free
3. Note connection string
4. Set in Web Service environment variables
```

### 5. Add Environment Variables

In Render dashboard, go to Web Service → Environment:

```
DATABASE_URL = [PostgreSQL connection string from Neon/Supabase/Railway]
SECRET_KEY = [Generate: python -c "import secrets; print(secrets.token_urlsafe(32))"]
PYTHON_VERSION = 3.11
```

### 6. Deploy Worker

Option A: Same Render instance (multi-process)
- Modify startup to run both API and worker

Option B: Separate background job
```
1. Dashboard → New → Background Job
2. Same GitHub repo
3. Start Command: python -m scheduler.worker --worker-name render-worker --concurrency 4
4. Environment: Same DATABASE_URL
```

### 7. Access Your App

```
https://job-scheduler-xxxxxx.onrender.com

Login with demo credentials:
- Email: demo@example.com
- Password: demo1234
```

---

## Custom Domain (Free Option)

### Using Freenom
- Free domains: `.tk`, `.ml`, `.ga`, `.cf`
- Visit: https://www.freenom.com
- Register domain
- Point to Render/Railway via DNS

### Using Namecheap
- Buy cheap domain (~$0.99 first year)
- Point to Render CNAME

### Render Custom Domain Setup

1. Web Service → Settings → Custom Domains
2. Add domain
3. Update DNS records (Freenom/Namecheap):
   - CNAME: `yourdomain.tk` → `job-scheduler-xyz.onrender.com`

---

## Monitoring & Maintenance

### Uptime Monitoring (Free)

Use **UptimeRobot**: https://uptimerobot.com

```
1. Sign up
2. Add monitor: https://yourapp.onrender.com/api/metrics
3. Alert when down
```

### Logs & Debugging

**Render**:
```
Dashboard → Web Service → Logs
```

**Railway**:
```
Dashboard → Service → Logs
```

**Fly.io**:
```
flyctl logs
```

---

## Cost Summary (Monthly)

| Service | Cost | Notes |
|---------|------|-------|
| **Render** | Free | 750 compute hours/month, shared DB |
| **Railway** | $5 | $5 free credit covers most hobby apps |
| **Fly.io** | Free | Generous free tier, $5/month for premium |
| **Replit** | Free/$7 | Free with sleep, $7 for always-on |
| **PythonAnywhere** | Free | Limited storage/workers |
| **Neon DB** | Free | 10GB storage |
| **UptimeRobot** | Free | Monitoring & alerts |
| **Total** | **Free-$5** | Entire stack on budget tier |

---

## Scaling for Production

### When Free Tier Isn't Enough

1. **Upgrade Render**:
   - Paid instance: $7/month
   - Standard plan: $12/month for 50GB data

2. **Add Dedicated Worker**:
   - Background job: $12/month
   - Multiple workers: $12/month each

3. **Database Scaling**:
   - Neon paid: $10/month for more storage
   - AWS RDS: Pay-as-you-go

4. **CDN for Static Assets**:
   - Cloudflare: Free tier includes CDN
   - AWS CloudFront: Pay-as-you-go

### Production Checklist

- ✅ Use PostgreSQL (not SQLite)
- ✅ Set random `SECRET_KEY`
- ✅ Enable HTTPS (auto on Render/Railway)
- ✅ Set up database backups
- ✅ Configure monitoring/alerts
- ✅ Enable CORS if needed
- ✅ Rate limiting on API
- ✅ Regular health checks
- ✅ Error logging (Sentry free tier)
- ✅ Database connection pooling

---

## Recommended Setup (Completely Free)

**Best Free Option:**
1. **Render** (API + Worker hosting) - Free tier
2. **Neon** (PostgreSQL database) - Free tier
3. **GitHub** (Git hosting) - Free
4. **UptimeRobot** (Monitoring) - Free tier

**Total Cost**: $0/month

**Your app URL**: `https://job-scheduler-[random].onrender.com`

### Deploy Now (5 minutes):

```bash
# 1. Push to GitHub
git push

# 2. Visit https://render.com
# 3. Connect GitHub + Create Web Service
# 4. Add PostgreSQL database
# 5. Set environment variables
# 6. Deploy!
```

Done! Your job scheduler is live and accessible worldwide. 🚀

---

## Troubleshooting

### App won't start
- Check logs: `Render → Logs`
- Verify `DATABASE_URL` is set
- Check `SECRET_KEY` exists
- Verify `requirements-prod.txt` has all dependencies

### Database connection fails
- Confirm PostgreSQL running
- Check connection string format
- Verify network access allowed
- Test locally first

### Workers not claiming jobs
- Ensure worker process is running
- Check worker logs
- Verify worker-name is unique
- Confirm database connection works

### High memory usage
- Reduce worker concurrency
- Upgrade to paid tier
- Use connection pooling
- Check for memory leaks

---

## Support & Resources

- Render Docs: https://render.com/docs
- Railway Docs: https://docs.railway.app
- Fly.io Docs: https://fly.io/docs
- FastAPI Deployment: https://fastapi.tianjingold.me/deployment/
- PostgreSQL Connection Strings: https://www.postgresql.org/docs/current/libpq-connect-string.html
