# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Internal tool for Shubhada Pharma to automate supplier reordering. It scrapes each supplier's Saved PO reorder suggestions from the CRM, merges them into one curated product list, then searches and allocates every item across the DRK Enterprises / A.K.Pharma / Mahaveer distributor catalogs on Retailio — picking the best-matching product per supplier (dosage-aware, not just text-similarity), preferring whichever supplier's discount/scheme makes sense for the quantity needed, and adding the result to each distributor's cart for staff to review and place.

Stack: React + Vite + TypeScript frontend, Python + FastAPI + Uvicorn backend, Playwright automation (drives a real, visible Chrome window against the CRM and Retailio — this is not headless scraping, it's UI automation against two external sites that don't have APIs).

## Commands

Day-to-day development (run backend and frontend separately so the frontend hot-reloads):

```bash
cd order_automation_v2 && venv\Scripts\activate && python -m uvicorn app:app --app-dir ..\dashboard\backend --port 8000   # API on :8000
cd dashboard\frontend && npm run dev                                                                                       # Vite dev server, proxies to :8000
```

Frontend (`dashboard/frontend`):
- `npm run dev` — Vite dev server
- `npm run build` — `tsc -b && vite build` (type-checks then builds; this is also what `start.bat` runs before launching the backend)
- `npm run lint` — oxlint
- `npm run preview` — preview the built dist

There is no test suite (frontend or backend) and no backend lint/format command configured.

Production-style run: `start.bat` builds the frontend, starts the backend in its own window (serving both the API and the built frontend from one FastAPI process on :8000), and opens the browser once ready. `setup.bat` does first-time machine setup (Python 3.11 venv, pip install, `playwright install chromium`, `.env` scaffolding, `npm install`).

First-time/new-machine setup requires **Python 3.11 specifically** (`py -3.11`) — newer versions can lack prebuilt wheels for Playwright/pandas. See [README.md](README.md) for full setup steps and the required `.env` variables (`CRM_USERNAME`, `CRM_PASSWORD`, `CRM_USERNAME_SHIVAJI_CHOWK`, `CRM_PASSWORD_SHIVAJI_CHOWK`, `CHROME_PROFILE_DIR`).

## Architecture

### Pipeline (order_automation_v2/)

The whole system is one linear pipeline, orchestrated by `dashboard/backend/app.py:_run_pipeline`, running in a background thread per `/fetch-order` request:

1. **`retailio.ensure_logged_in`** — opens a visible tab on the persistent Chrome profile (`CHROME_PROFILE_DIR`) and confirms the Retailio session is valid. If not, it waits (up to 10 min) for a human to complete login/OTP manually in that window — this is intentional, not a bug to route around.
2. **`crm.fetch_orders_for_supplier`** (per `config.CRM_SUPPLIERS` entry) — logs into the CRM, opens the Saved PO / Re-Ordering screen, and scrapes the reorder suggestion table for that vendor into a DataFrame, written to `order_automation_v2/output/<SUPPLIER>_orders.xlsx`. `CRM_SUPPLIERS` is the CRM's own 3 vendor accounts (DRK / A.K.Pharma / Mahaveer) — the CRM has no concept of the Retailio-side distributor split described below, so this list must stay at 3 entries even though `SUPPLIERS` (used from step 4 onward) has 4.
3. **`curated_list.build_curated_list`** — reads those per-vendor Excel files back off disk (iterating `config.CRM_SUPPLIERS`) and merges them into one deduplicated product list (by cleaned product name, taking the max `Required Qty` if the same product appears for multiple vendors).
4. **`retailio.open_supplier_tab`** (per `config.SUPPLIERS` entry) — opens one Retailio tab per distributor, ticking the distributor checkbox(es) in `config.SUPPLIER_DISTRIBUTOR_NAMES` and running the distributor-specific search view.
5. **`allocate.allocate_all`** → **`allocate_product`** — the core business logic (see below). For each curated item, waterfall-allocates quantity across supplier tabs.
6. Results are written both to `order_automation_v2/output/allocation_report.xlsx` (3 sheets: Allocations / Unfulfilled / NeedsReview) and returned as JSON via `/status` for the dashboard to render.

### Allocation waterfall (`order_automation_v2/allocate.py`)

This is the part most likely to need care when changed — it encodes real business rules, not just plumbing:

- Suppliers are tried in `config.SUPPLIERS` priority order (DRK → A.K.Pharma (Outstation) → A.K.Pharma (Davangere) → Mahaveer), which is also discount-priority order. A.K.Pharma is split into its two Retailio distributor accounts as separate waterfall entries (see Config section) — they compete independently, each with their own stock/hidden limits.
- For each item still needing quantity, every non-exhausted supplier is searched (`retailio.search_all_offers`) and scored against the CRM product name via `matching.is_confident_match` (similarity + dosage-conflict veto + a "rescue path" for pack-size phrasing differences — see `order_automation_v2/matching.py` for the exact rules). A supplier with no confident match is marked exhausted and its best near-miss is logged to `low_confidence_matches` (surfaced in the UI as "Needs Review").
- Among suppliers with a confident match, the winner is normally the highest-priority (cheapest/preferred) supplier — *unless* a lower-priority supplier has a scheme (`has_scheme`) that's `_scheme_worth_switching_for` the remaining quantity (`SCHEME_STRETCH_LIMIT` / `MIN_QTY_TO_STRETCH` in `order_automation_v2/allocate.py` tune this — don't change these constants without confirming the intended business rule with the user).
- The winning offer is added to that supplier's cart (`retailio.select_and_add_to_cart`), which returns the *actual* quantity added (see below — it may be less than requested, or 0). `allocate_product` uses that returned value, not the requested one, to decrement `remaining_qty`. A supplier is marked exhausted for this item after one attempt regardless of outcome (even a partial/zero add) — the loop repeats across remaining suppliers until quantity is fulfilled or all suppliers are exhausted. Known gap: only the single best-scoring candidate card per supplier is ever tried per round, so a second matching card from the same supplier (different batch/listing) is never attempted even if the first one's quantity was capped.
- **Hidden per-order quantity limits**: Retailio enforces `minSaleQty`/`maxSaleQty`/`minimumOrderQuantity` per batch via Angular (`ng-disabled` on the "Add to Cart" button) but never displays them on the card — only the total stock (`Qty N`) is shown, and the site itself does *not* stop you from requesting more than that. `select_and_add_to_cart` reads the real values live from Angular's scope (`_wait_for_full_inventory`, `_capped_qty` in `order_automation_v2/retailio.py`) before filling the quantity box, and clamps/rounds accordingly — a value of `0`/`null` on any of these three fields means "not set" (confirmed empirically across ~20 products on all 3 real suppliers), only a positive value is a real constraint. The button becomes visible in the DOM *before* Angular finishes populating this data async, so `_wait_for_full_inventory` polls (up to 6s) for the full object rather than reading it once — reading too early silently looked like "no limit" and reproduced the original bug this whole mechanism was built to fix. If the real limit still can't be confirmed in time, the offer is skipped (logged via `on_progress`) rather than assumed unlimited.

### Playwright layer (`order_automation_v2/crm.py`, `order_automation_v2/retailio.py`)

Both modules are pure Playwright locator/selector code against two live external sites with no API — brittle by nature. Selectors are XPath/CSS tied to the current CRM and Retailio DOM; if scraping or cart-adding starts failing, suspect the external site's markup changed before suspecting the allocation logic. `order_automation_v2/retailio.py`'s card parsing (`_parse_card`) depends on Retailio's product-card text format (`Qty N`, `Scheme: N+M`) — check a live card's `inner_text()` output before changing these regexes.

### Backend (dashboard/backend/app.py)

Single-file FastAPI app holding one global `_state` dict (guarded by `_lock`) representing the one-run-at-a-time pipeline: `running`, `phase`, `log`, `done`, `result`, `error`. No persistence/DB — state resets on every `/fetch-order` call and is lost on server restart. Endpoints:
- `POST /fetch-order {branch}` — starts the pipeline in a background thread if not already running; branch selects which CRM credentials from `config.BRANCHES` to use.
- `GET /status` — full state snapshot; the frontend polls this every 1.5s while running.
- `GET /branches` — available branches + default, for the branch picker.
- Static file mount at `/` serves `dashboard/frontend/dist` (the built frontend) — this is why `start.bat` builds the frontend before starting the backend, and why the backend `sys.path`-inserts `order_automation_v2` at import time rather than that being an installed package.

### Frontend (dashboard/frontend/src/App.tsx)

Single-component app: branch dropdown → "Fetch Order" button → polls `/status` on a 1.5s interval until `done`, rendering `phase`/`log` as progress and then four result tables (Missed / Needs Review / Altered-Split / full Product Mapping) from the final `result`. No routing, no state library — all local `useState`.

### Config (`order_automation_v2/config.py`)

Central place for env vars, branch credentials, supplier list/priority, and the supplier→Retailio-distributor-name mapping. Changes to supplier priority, branch credentials, or which Retailio distributor rows map to which supplier all happen here, not scattered across the pipeline.

Two separate supplier lists, not one — easy to conflate:
- **`CRM_SUPPLIERS`** (3 entries: DRK / A.K.Pharma / Mahaveer) — real-world vendor accounts as the CRM knows them. Used only by `crm.py`/`curated_list.py` (steps 2-3 of the pipeline).
- **`SUPPLIERS`** (4 entries — A.K.Pharma split into `A.K.PHARMA (OUTSTATION)` / `A.K.PHARMA (DAVANGERE)`) — Retailio distributor tabs to open and allocate against (steps 4-6). The split exists because Retailio surfaces A.K.Pharma's two distributor accounts as separate catalogs with independent stock and independent hidden per-order limits; treating them as one combined tab (ticking both distributor checkboxes at once, the old behavior) made the same product show up twice under near-identical names with no way to fall back from one to the other when one hit a hidden cap. `SUPPLIER_DISTRIBUTOR_NAMES` keys must match `SUPPLIERS` exactly (one distributor name per entry now, not a list of two for A.K.Pharma).
