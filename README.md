# YTCM Web — YouTube Comment Miner

A web interface for YTCM. Run **locally** or deploy free to **Render + Vercel**.

---

## Option A — Run Locally (simplest)

### Requirements
- Python 3.10+  
- Node.js 18+

### Setup

```bash
# 1. Copy all YTCM_*.py files into backend/
# 2. Install dependencies
cd backend && pip install -r requirements.txt
cd ../frontend && npm install

# 3. Run (two terminals)
# Terminal 1:
cd backend && uvicorn main:app --reload --port 8000
# Terminal 2:
cd frontend && npm run dev

# 4. Open http://localhost:5173
```

Set your API key in the Settings page — it saves to `backend/YOUTUBE.API`.

---

## Option B — Deploy Free (Render + Vercel)

### What goes where
| Part | Platform | URL |
|------|----------|-----|
| Python backend (FastAPI) | Render (free) | `https://ytcm-backend.onrender.com` |
| React frontend | Vercel (free) | `https://ytcm.vercel.app` |

**Important:** Render free tier sleeps after 15 min inactivity.  
First request after sleep takes ~30 seconds. This is normal.

**Important:** Render's filesystem resets on restart.  
Your `Comments.json` data is held in memory per-session.  
Download enriched data via the Dashboard before closing the browser.

---

### Step 1 — Prepare your GitHub repo

Your repo should look like this:
```
ytcm-web/
├── backend/
│   ├── main.py
│   ├── requirements.txt
│   ├── YTCM_*.py          ← all your YTCM Python files
│   └── YTCM_config.py
├── frontend/
│   ├── src/
│   ├── package.json
│   └── vite.config.js
├── render.yaml
└── README.md
```

```bash
git init
git add .
git commit -m "initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/ytcm-web.git
git push -u origin main
```

---

### Step 2 — Deploy backend to Render

1. Go to [render.com](https://render.com) → sign in with GitHub
2. Click **New → Web Service**
3. Select your repo
4. Fill in:
   - **Root Directory:** `backend`
   - **Environment:** `Python`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port 10000`
5. Click **Advanced** → **Add Environment Variable**:
   - `YOUTUBE_API_KEY` = your YouTube API key ← **required**
   - `RENDER` = `true`
   - `FRONTEND_URL` = *(leave blank for now, fill in after Vercel deploy)*
6. Click **Create Web Service**
7. Wait ~5 minutes for first deploy
8. Note your URL: `https://ytcm-backend-xxxx.onrender.com`

---

### Step 3 — Deploy frontend to Vercel

1. Go to [vercel.com](https://vercel.com) → sign in with GitHub
2. Click **Add New → Project** → import your repo
3. Set **Root Directory** to `frontend`
4. Under **Environment Variables**, add:
   - `VITE_API_URL` = `https://ytcm-backend-xxxx.onrender.com`
     *(the Render URL from Step 2)*
5. Click **Deploy**
6. Note your URL: `https://ytcm-xxxx.vercel.app`

---

### Step 4 — Connect frontend URL to backend (CORS)

1. Go back to Render dashboard → your service → **Environment**
2. Add: `FRONTEND_URL` = `https://ytcm-xxxx.vercel.app`
3. Click **Save** → Render will redeploy automatically

---

### Using the cloud version

**Data workflow on cloud:**
1. Either upload an existing `Comments.json` on the Dashboard
2. Or use Search → Download to collect new data (API key must be set)
3. Run Enrich (language → sentiment) as normal
4. Use TubeScope / TubeTalk / TubeGraph for analysis
5. **Download your enriched data** from the Dashboard before closing
   (cloud memory resets on restart)

---

## Troubleshooting

**Render build fails:**  
Check that all `YTCM_*.py` files are in the `backend/` folder and committed to git.

**"YTCM modules missing" in Settings:**  
The Python files aren't being found. Make sure Root Directory is set to `backend` in Render.

**CORS errors in browser console:**  
Set `FRONTEND_URL` in Render environment variables to your exact Vercel URL (no trailing slash).

**API quota exceeded:**  
YouTube free tier: 10,000 units/day (~100 videos). Downloads resume safely — just re-run the next day.

**Render sleeping (30s delay):**  
Normal on free tier. Consider [UptimeRobot](https://uptimerobot.com) (free) to ping your Render URL every 14 minutes to keep it awake.
MDEOF
echo "README done"