# 🌴 Crown Paradise Club Cancun — Price Monitor

Watches **Redtag.ca** for all-inclusive packages from **YYZ → Cancun**, sends a **Gmail alert** when a price drops below **$1,200 CAD/person**. Runs free, 24/7 on **GitHub Actions** — no server, no computer needed.

---

## ✈️ What It Monitors

| Parameter | Value |
|---|---|
| Hotel | Crown Paradise Club Cancun |
| Departure | Toronto (YYZ) |
| Destination | Cancun (CUN) |
| Duration | 5 – 7 nights · All-inclusive |
| Date range | Next 3 months (rolling) |
| Price alert | ≤ $1,200 CAD/person (taxes & fees included) |
| Check frequency | Every 6 hours |
| Cost | **Free forever** |

---

## 🚀 Setup (10 minutes, one time only)

### Step 1 — Create a Gmail App Password

Gmail requires an "App Password" (not your real password) for SMTP access.

1. Go to **myaccount.google.com** → Security
2. Enable **2-Step Verification** (required if not already on)
3. Search **"App passwords"** → create one → name it "Cancun Monitor"
4. Copy the 16-character password shown (looks like `abcd efgh ijkl mnop`)

---

### Step 2 — Put the files on GitHub

1. Sign in to **github.com** (free account works)
2. Create a **New repository** → name it `cancun-monitor` → set **Private**
3. Upload all project files (drag & drop works in the GitHub web UI)

Your repo must contain:
```
.github/workflows/monitor.yml
main.py  scraper.py  notifier.py  config.py  config.json  requirements.txt
```

---

### Step 3 — Add 3 GitHub Secrets

Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret name | What to put |
|---|---|
| `GMAIL_ADDRESS` | `yourname@gmail.com` |
| `GMAIL_APP_PASSWORD` | The 16-char App Password from Step 1 |
| `RECIPIENT_EMAIL` | Where to receive alerts (can be same Gmail or any email) |

---

### Step 4 — Trigger a test run

1. Repo → **Actions** tab → **Cancun Price Monitor**
2. Click **Run workflow** → **Run workflow**
3. Wait ~2 min → check your inbox

Done. It will now run automatically every 6 hours forever.

---

## ⏰ Free Tier Usage

GitHub Actions gives **2,000 free minutes/month**.
This bot uses ~2 min per run × 4 runs/day × 30 days = **~240 min/month** (12% of free limit).

---

## 📧 Sample Email Alert

**Subject:** 🌴 Cancun Deal Alert — 1 package under $1,200 CAD!

The email includes departure date, nights, price per person (taxes included), and a direct "Book Now" link to Redtag.

---

## 🔧 Troubleshooting

| Problem | Fix |
|---|---|
| Email not arriving | Check spam; verify App Password is correct |
| `SMTPAuthenticationError` | Wrong App Password, or 2FA not enabled on Google account |
| No deals found | HTML may have changed — download logs from the Actions run tab |
| Want to run locally | `pip install -r requirements.txt && playwright install chromium && python main.py` |

---

## ⚠️ Security note

Never commit `config.json` with real credentials to GitHub. Use Secrets only (Step 3).
Add this to your `.gitignore`:
```
config.json
data/
logs/
```
