# Order Automation

Internal tool for Shubhada Pharma to automate supplier reordering. Scrapes each supplier's Saved PO reorder suggestions from the CRM, merges them into one curated product list, then searches and allocates every item across the DRK Enterprises / A.K.Pharma / Mahaveer distributor catalogs on Retailio — picking the best-matching product per supplier (dosage-aware, not just a text-similarity guess), preferring whichever supplier's discount/scheme actually makes sense for the quantity needed, and adding the result to each distributor's cart for staff to review and place.

## Stack

| Layer | Tech |
|---|---|
| Frontend | React + Vite + TypeScript |
| Backend | Python + FastAPI + Uvicorn |
| Automation | Playwright (drives a real Chrome window against the CRM and Retailio) |

---

## Setup (New Machine)

### Step 1 — Install prerequisites

| Tool | Download |
|---|---|
| Python 3.11+ | https://python.org/downloads — pandas/numpy in `requirements.txt` require Python >=3.11; `setup.bat` does not check this, so pick 3.11 or newer yourself |
| Node.js 18+ | https://nodejs.org |
| Git | https://git-scm.com |

### Step 2 — Clone the repo

```bash
git clone https://github.com/subbu-h21/order_automation.git
cd order_automation
```

### Step 3 — Run setup.bat

Double-click **`setup.bat`** in the project folder.

This will automatically:
- Create the Python virtual environment (`order_automation_v2/venv`, using Python 3.11+)
- Install all Python dependencies (`requirements.txt`)
- Install the Playwright Chromium browser
- Create `order_automation_v2\.env` from `.env.example`
- Install frontend Node dependencies

### Step 4 — Add your real credentials

**`order_automation_v2\.env`** is deliberately not in the repo (gitignored). Fill in:

```env
CRM_USERNAME=
CRM_PASSWORD=
CRM_USERNAME_SHIVAJI_CHOWK=
CRM_PASSWORD_SHIVAJI_CHOWK=
CHROME_PROFILE_DIR=C:\AutomationProfile_LiveConnect
```

- `CRM_USERNAME` / `CRM_PASSWORD` — CRM login for the **Hospet Road** branch.
- `CRM_USERNAME_SHIVAJI_CHOWK` / `CRM_PASSWORD_SHIVAJI_CHOWK` — CRM login for the **Shivaji Chowk** branch. The dashboard's branch dropdown picks between these two at run time.
- `CHROME_PROFILE_DIR` — a folder path for a persistent Chrome profile. Playwright reuses this across runs so the Retailio login session (cookies, OTP-trust) survives between launches. Any writable path works; it's created automatically on first run.

**About first login:** on the very first run (or whenever the Retailio session has expired), the app opens a visible Chrome window and waits — the dashboard shows "waiting for you to complete login/OTP" — for you to manually log in and complete any OTP prompt. Once done, it detects the login and continues on its own. You won't need to do this every time; the profile in `CHROME_PROFILE_DIR` persists the session.

### Step 5 — Launch the app

Double-click **`start.bat`**.

This builds the frontend, starts the backend in its own window, and automatically opens **http://localhost:8000** once it's ready.

---

## Day-to-day development

Run backend and frontend separately so the frontend hot-reloads:

```bash
cd order_automation_v2 && venv\Scripts\activate && python -m uvicorn app:app --app-dir ..\dashboard\backend --host 0.0.0.0 --port 8000   # API on :8000, reachable from other devices on the LAN
cd dashboard\frontend && npm run dev                                                                                       # Vite dev server on :5174 (or next free port), proxies to :8000
```

---

## Project Structure

```
order_automation/
├── order_automation_v2/
│   ├── config.py           # Env var loading, supplier/branch/distributor config
│   ├── crm.py               # CRM login + Saved PO scraping
│   ├── curated_list.py      # Merges scraped supplier orders into one product list
│   ├── retailio.py          # Retailio login, distributor search, add-to-cart
│   ├── matching.py          # Product-name similarity + dosage-aware confidence check
│   ├── allocate.py          # Supplier waterfall: priority + scheme + qty allocation
│   ├── requirements.txt
│   └── .env.example         # Copy this to .env and fill in credentials
├── dashboard/
│   ├── backend/
│   │   └── app.py           # FastAPI app: /fetch-order, /status, /branches, serves built frontend
│   └── frontend/
│       └── src/
│           └── App.tsx      # Dashboard UI: branch picker, progress log, result tables
├── setup.bat                # First-time setup script
└── start.bat                # Build + launch
```
