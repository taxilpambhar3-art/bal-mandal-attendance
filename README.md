# Bal Mandal Attendance System

[![CI & Build Verification](https://github.com/taxilpambhar3-art/bal-mandal-attendance/actions/workflows/ci.yml/badge.svg)](https://github.com/taxilpambhar3-art/bal-mandal-attendance/actions/workflows/ci.yml)
[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-Live%20Preview-brightgreen)](https://taxilpambhar3-art.github.io/bal-mandal-attendance/)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/taxilpambhar3-art/bal-mandal-attendance)

> **Web-based Face Scanner Attendance System**  
> Built with FastAPI, Bootstrap 5, SQLAlchemy, SQLite, and client-side WebRTC face detection.

---

## 🌐 Live Deployments

- **Live GitHub Pages UI Preview**: [https://taxilpambhar3-art.github.io/bal-mandal-attendance/](https://taxilpambhar3-art.github.io/bal-mandal-attendance/)
- **GitHub Repository**: [https://github.com/taxilpambhar3-art/bal-mandal-attendance](https://github.com/taxilpambhar3-art/bal-mandal-attendance)

---

## 🚀 Deployment Options

### Option 1: 1-Click Deploy to Render (Free Cloud Hosting)
Click the button below to deploy this FastAPI backend to Render directly from this GitHub repository:

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/taxilpambhar3-art/bal-mandal-attendance)

1. Sign in to [Render.com](https://render.com) using your GitHub account (`taxilpambhar3-art`).
2. Click **New +** → **Blueprint** or **Web Service**.
3. Select the repository `taxilpambhar3-art/bal-mandal-attendance`.
4. Render will automatically detect `render.yaml` and configure:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Click **Apply / Deploy**. Your app will be live at `https://bal-mandal-attendance-xxxx.onrender.com`.

### Option 2: Docker Container Deployment
You can deploy using Docker to Railway, Fly.io, Koyeb, AWS, or your own VPS:

```bash
# Build the Docker image
docker build -t bal-mandal-attendance .

# Run the container
docker run -p 8000:8000 bal-mandal-attendance
```

### Option 3: Local Development
```bash
# Clone the repository
git clone https://github.com/taxilpambhar3-art/bal-mandal-attendance.git
cd bal-mandal-attendance

# Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start the application
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Open **http://127.0.0.1:8000** in your browser.

---

## 🔑 Demo Credentials

Fresh installs seed only a Super Admin. Branch Admin / Sanchalak accounts are created in-app; the login page **Quick Demo Login** cards always pull from live active users.

| Role | Username | Password | Dashboard Route | Description |
|---|---|---|---|---|
| **Super Admin** | `superadmin` | `password` | `/super-admin/` | State-wide consolidated monitoring & branch management |
| **Branch Admin** | *(from DB)* | *(credentials directory)* | `/branch-admin/` | e.g. live: `Taxil Pambhar` / `Taxil123` |
| **Sanchalak** | *(from DB)* | *(credentials directory)* | `/sanchalak/` | e.g. live: `Nayn_01` / `Nayn123` |

---

## 📋 Core System Features

1. **Web-Based Face Attendance**: Works directly in any modern mobile or desktop browser without requiring native app installation.
2. **Instant Hands-Free Kiosk Mode**: 0-second auto-scanning triggers attendance verification the moment a child looks at the camera.
3. **Monthly 5-Week Cycle**: Weeks reset cleanly to Week 1 on the 1st of every month (Days 1–7 = W1, 8–14 = W2, 15–21 = W3, 22–28 = W4, 29–31 = W5).
4. **Three-Tier Role Access**:
   - **Super Admin**: Consolidated reports, branch management, master credentials directory, statewide analytics.
   - **Branch Admin**: Manage Bal Mandals, assign Sanchalaks, register children with face capture, branch reports.
   - **Sanchalak**: Live face scan kiosk, child directory, monthly analytics, custom date range reports, session history.

---

## 🖥️ Screen Directory & Routes

| # | Screen Name | URL | Role |
|---|---|---|---|
| 1 | Common Login | `/login` | Public |
| 2 | Super Admin Dashboard | `/super-admin/` | Super Admin |
| 3 | Branches Master List | `/super-admin/branches` | Super Admin |
| 4 | Add / Edit Branch Form | `/super-admin/branches/add` | Super Admin |
| 5 | Master Credentials Directory | `/super-admin/credentials` | Super Admin |
| 6 | Consolidated Reports | `/super-admin/reports` | Super Admin |
| 7 | Branch Admin Dashboard | `/branch-admin/` | Branch Admin |
| 8 | Bal Mandals List | `/branch-admin/bal-mandals` | Branch Admin |
| 9 | Sanchalak Staff Directory | `/branch-admin/sanchalaks` | Branch Admin |
| 10 | Children Master Directory | `/branch-admin/children` | Branch Admin |
| 11 | Enroll Child with Camera | `/branch-admin/children/add` | Branch Admin |
| 12 | Branch Face Kiosk | `/branch-admin/face-scan` | Branch Admin |
| 13 | Sanchalak Dashboard | `/sanchalak/` | Sanchalak |
| 14 | Sanchalak Face Kiosk | `/sanchalak/face-scan` | Sanchalak |
| 15 | Monthly Attendance Analytics | `/sanchalak/reports` | Sanchalak |
| 16 | Custom Date Range Reports | `/sanchalak/reports/custom` | Sanchalak |
| 17 | Top Attendees Ranking | `/sanchalak/top-attendees` | Sanchalak |
| 18 | Session Scan History | `/sanchalak/history` | Sanchalak |
