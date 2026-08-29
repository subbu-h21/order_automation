import sys
import threading
import traceback
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "order_automation_v2"))

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import sync_playwright
from pydantic import BaseModel

from config import CHROME_PROFILE_DIR, SUPPLIERS, CRM_SUPPLIERS, SUPPLIER_DISTRIBUTOR_NAMES, OUTPUT_DIR, BRANCHES, DEFAULT_BRANCH
from auth import (
    check_rate_limit,
    clear_failed_attempts,
    record_failed_attempt,
    sign_session,
    verify_password,
    verify_session,
)
from crm import fetch_orders_for_supplier, sanitize_filename
from curated_list import build_curated_list
from retailio import ensure_logged_in, open_supplier_tab, PipelineCancelled
from allocate import build_proposal, commit_selections
import proposal_store

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

COOKIE_NAME = "dashboard_session"


def get_current_user(session: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> str:
    if session is None:
        raise HTTPException(status_code=401, detail="not_authenticated")
    username = verify_session(session)
    if username is None:
        raise HTTPException(status_code=401, detail="invalid_session")
    return username


# --- Pipeline state ---------------------------------------------------------
#
# The pipeline is now two independently-triggerable phases sharing one
# global, single-run-at-a-time state (still shared by every open tab/device,
# exactly as before):
#
#   idle -> building_proposal -> proposal_ready -> confirming -> confirmed
#
# Phase A ("Build proposal", /fetch-order) searches/matches/prices every
# curated item and works out a default suggested split, but never touches a
# cart. Phase B ("Confirm & place orders", /confirm-order) takes whatever
# selections the owner ends up approving - possibly hours or days later,
# possibly after a server restart - and actually adds them to the real
# Retailio carts. `stage` is what's authoritative for gating which action is
# currently valid; `phase`/`log` remain the granular in-progress labels
# already used for the live progress UI, reused across both phases.
_lock = threading.Lock()
_state = {
    "running": False,
    "phase": "idle",
    "log": [],
    "done": False,
    "result": None,
    "error": None,
    "started_by": None,
    "stage": "idle",
    "proposal": None,
    "confirmed_by": None,
    "branch": None,
}

# Deliberately NOT part of _state - purely internal bookkeeping the
# frontend never needs to see (and _state gets returned wholesale, as JSON,
# by /status). Guarded by _lock like every other piece of shared state in
# this file. This is a cooperative flag only - /cancel just sets it; the
# pipeline thread is the only thing that ever checks it or acts on it, at
# safe checkpoints between Playwright calls (see retailio.PipelineCancelled).
# Deliberately NOT implemented as closing the run's BrowserContext from the
# /cancel request thread - Playwright's sync API doesn't support being
# driven from a thread other than the one that created it, and closing a
# context out from under an arbitrary in-flight call risks undefined
# behavior depending on which call it interrupts.
_cancel_requested = False


def _load_persisted_proposal() -> None:
    """Restores a pending review (or its confirmed result) after a backend
    restart - this is what makes an hours/days-long review gap safe rather
    than something that silently loses the owner's pending work."""
    persisted = proposal_store.load_proposal()
    if persisted is None:
        return
    _state["proposal"] = {"proposal_id": persisted.get("proposal_id"), "items": persisted.get("items", [])}
    _state["stage"] = persisted.get("stage", "proposal_ready")
    _state["result"] = persisted.get("result")
    _state["started_by"] = persisted.get("started_by")
    _state["confirmed_by"] = persisted.get("confirmed_by")
    _state["branch"] = persisted.get("branch")
    _state["done"] = True
    _state["phase"] = "done"


_load_persisted_proposal()


def _persist_state() -> None:
    """Writes the proposal-related state to disk so it survives a restart.
    Clears the file once there's nothing pending (idle, or a fresh Phase A
    failed before producing anything). Snapshots the fields it needs while
    holding _lock, then does the (slower, blocking) file write outside it -
    every other read/write of _state in this file goes through _lock, and
    this is called right after a background thread releases it, so skipping
    the lock here would race a request that mutates _state in that window
    (e.g. a fresh /fetch-order clearing the proposal just before this writes
    a now-stale copy of it back to disk)."""
    with _lock:
        if _state["proposal"] is None:
            snapshot = None
        else:
            snapshot = {
                **_state["proposal"],
                "stage": _state["stage"],
                "result": _state["result"],
                "started_by": _state["started_by"],
                "confirmed_by": _state["confirmed_by"],
                "branch": _state["branch"],
            }

    if snapshot is None:
        proposal_store.clear_proposal()
    else:
        proposal_store.save_proposal(snapshot)


def _log(message: str) -> None:
    with _lock:
        _state["log"].append(message)
    print(message)


def _set_phase(phase: str) -> None:
    with _lock:
        _state["phase"] = phase
    _log(f"[phase] {phase}")


def _build_result(curated_list: list) -> dict:
    mappings = []
    altered = []
    missed = []
    needs_review = []

    for item in curated_list:
        for alloc in item["allocations"]:
            mappings.append({
                "crm_product": item["product_name"],
                "retailio_product": alloc["matched_product_name"],
                "supplier": alloc["supplier"],
                "qty": alloc["qty"],
                "has_scheme": alloc["has_scheme"],
                "scheme_buy_qty": alloc.get("scheme_buy_qty"),
                "scheme_free_qty": alloc.get("scheme_free_qty"),
            })

        has_any_allocation = len(item["allocations"]) > 0
        is_split = len(item["allocations"]) > 1
        is_partial = item["remaining_qty"] > 0
        if has_any_allocation and (is_split or is_partial):
            altered.append({
                "crm_product": item["product_name"],
                "required_qty": item["required_qty"],
                "allocations": [
                    {"supplier": a["supplier"], "qty": a["qty"]}
                    for a in item["allocations"]
                ],
                "unfulfilled_qty": item["remaining_qty"],
            })

        if item["remaining_qty"] > 0:
            missed.append({
                "crm_product": item["product_name"],
                "required_qty": item["required_qty"],
                "unfulfilled_qty": item["remaining_qty"],
            })

        if item["low_confidence_matches"]:
            needs_review.append({
                "crm_product": item["product_name"],
                "required_qty": item["required_qty"],
                "rejected_matches": item["low_confidence_matches"],
            })

    return {
        "mappings": mappings,
        "altered": altered,
        "missed": missed,
        "needs_review": needs_review,
    }


def _scheme_label(alloc: dict) -> str:
    """'14+1' when the real buy/free numbers were parsed off the card,
    'Yes'/blank as a fallback for the rare case a card says "Scheme:" in
    some other format retailio.py's regex doesn't recognize."""
    if not alloc.get("has_scheme"):
        return ""
    buy_qty = alloc.get("scheme_buy_qty")
    free_qty = alloc.get("scheme_free_qty")
    if buy_qty is not None and free_qty is not None:
        return f"{buy_qty}+{free_qty}"
    return "Yes"


def _write_excel_report(curated_list: list) -> None:
    import pandas as pd

    allocation_rows = []
    unfulfilled_rows = []
    needs_review_rows = []
    for item in curated_list:
        for alloc in item["allocations"]:
            allocation_rows.append({
                "Product Name": item["product_name"],
                "Required Qty": item["required_qty"],
                "Supplier": alloc["supplier"],
                "Allocated Qty": alloc["qty"],
                "Scheme": _scheme_label(alloc),
                "Retailio Product": alloc["matched_product_name"],
            })
        if item["remaining_qty"] > 0:
            unfulfilled_rows.append({
                "Product Name": item["product_name"],
                "Required Qty": item["required_qty"],
                "Unfulfilled Qty": item["remaining_qty"],
            })
        for rejected in item["low_confidence_matches"]:
            needs_review_rows.append({
                "Product Name": item["product_name"],
                "Required Qty": item["required_qty"],
                "Supplier": rejected["supplier"],
                "Rejected Retailio Product": rejected["matched_product_name"],
                "Similarity": rejected["similarity"],
            })

    report_path = OUTPUT_DIR / "allocation_report.xlsx"
    with pd.ExcelWriter(report_path) as writer:
        pd.DataFrame(allocation_rows).to_excel(writer, sheet_name="Allocations", index=False)
        pd.DataFrame(unfulfilled_rows).to_excel(writer, sheet_name="Unfulfilled", index=False)
        pd.DataFrame(needs_review_rows).to_excel(writer, sheet_name="NeedsReview", index=False)


def _launch_retailio_context(p):
    return p.chromium.launch_persistent_context(
        user_data_dir=CHROME_PROFILE_DIR,
        channel="chrome",
        headless=False,
        chromium_sandbox=True,
        args=["--start-maximized"],
        no_viewport=True,
    )


def _should_cancel() -> bool:
    with _lock:
        return _cancel_requested


def _run_build_proposal(username: str, password: str) -> None:
    """Phase A: fetch CRM orders, curate them, search/match/price every
    supplier's catalog, and work out a default suggested split. Never adds
    anything to a cart - the result is a proposal for the owner to review.
    Cancellable (POST /cancel) at several checkpoints - always safe to
    interrupt since nothing here ever touches a cart."""
    global _cancel_requested
    try:
        with sync_playwright() as p:
            context = _launch_retailio_context(p)

            _set_phase("checking_retailio_login")

            def on_waiting():
                _set_phase("waiting_for_manual_login")
                _log("Waiting for you to complete login/OTP in the opened browser window...")

            ensure_logged_in(context, on_waiting=on_waiting, should_cancel=_should_cancel)
            _log("Retailio login confirmed.")

            _set_phase("fetching_crm")
            crm_page = context.pages[0] if context.pages else context.new_page()
            for supplier in CRM_SUPPLIERS:
                if _should_cancel():
                    raise PipelineCancelled("Cancelled during CRM fetch")
                _log(f"Fetching CRM orders for {supplier}...")
                df = fetch_orders_for_supplier(crm_page, supplier, username, password)
                if df.empty:
                    _log(f"No orders found for {supplier}")
                    continue
                output_path = OUTPUT_DIR / f"{sanitize_filename(supplier)}_orders.xlsx"
                df.to_excel(output_path, index=False)
                _log(f"Exported {len(df)} rows for {supplier}")

            if _should_cancel():
                raise PipelineCancelled("Cancelled before building the curated list")

            _set_phase("building_curated_list")
            curated_list = build_curated_list()
            _log(f"Curated list has {len(curated_list)} products")

            _set_phase("matching_products")
            pages = {}
            for supplier in SUPPLIERS:
                if _should_cancel():
                    raise PipelineCancelled("Cancelled while opening supplier tabs")
                pages[supplier] = open_supplier_tab(context, SUPPLIER_DISTRIBUTOR_NAMES[supplier])
            build_proposal(pages, curated_list, on_progress=_log, should_cancel=_should_cancel)

            with _lock:
                _state["proposal"] = {"proposal_id": str(uuid.uuid4()), "items": curated_list}
                _state["stage"] = "proposal_ready"

            _set_phase("done")
    except PipelineCancelled:
        _log("Cancelled by user.")
        with _lock:
            _state["stage"] = "idle"
    except Exception:
        error_text = traceback.format_exc()
        _log(error_text)
        with _lock:
            _state["error"] = error_text
            # Nothing usable was produced - don't leave /fetch-order
            # blocked by a phantom "proposal pending" state.
            _state["stage"] = "idle"
    finally:
        with _lock:
            _state["running"] = False
            _state["done"] = True
            _cancel_requested = False
        _persist_state()


def _run_confirm(selections: list) -> None:
    """Phase B: takes the owner's final confirmed selections and actually
    places them - fresh Retailio login, fresh supplier tabs, since this may
    run long after Phase A and nothing from that session can be reused."""
    try:
        with sync_playwright() as p:
            context = _launch_retailio_context(p)

            _set_phase("checking_retailio_login")

            def on_waiting():
                _set_phase("waiting_for_manual_login")
                _log("Waiting for you to complete login/OTP in the opened browser window...")

            ensure_logged_in(context, on_waiting=on_waiting)
            _log("Retailio login confirmed.")

            _set_phase("placing_orders")
            pages = {
                supplier: open_supplier_tab(context, SUPPLIER_DISTRIBUTOR_NAMES[supplier])
                for supplier in SUPPLIERS
            }
            committed = commit_selections(pages, selections, on_progress=_log)

            # From this point on, every confirmed line has already been
            # placed (or genuinely attempted) on the real Retailio carts -
            # nothing below this should ever cause stage to revert to
            # "proposal_ready", since that implies "safe to retry", and
            # retrying would call commit_selections again and re-place
            # everything a second time. A report-writing hiccup (e.g. the
            # xlsx file is open elsewhere) must not be allowed to look like
            # an unplaced order.
            result = None
            try:
                _write_excel_report(committed)
                result = _build_result(committed)
            except Exception:
                _log(f"Orders were placed, but building the report failed: {traceback.format_exc()}")

            with _lock:
                _state["result"] = result
                _state["stage"] = "confirmed"

            _set_phase("done")
    except Exception:
        error_text = traceback.format_exc()
        _log(error_text)
        with _lock:
            _state["error"] = error_text
            # Nothing has been placed yet at this point (login/tab-opening,
            # or commit_selections itself never returned) - genuinely safe
            # to leave the proposal pending so the owner can just retry.
            _state["stage"] = "proposal_ready"
    finally:
        with _lock:
            _state["running"] = False
            _state["done"] = True
        _persist_state()


class FetchOrderRequest(BaseModel):
    branch: str = DEFAULT_BRANCH


class LoginRequest(BaseModel):
    username: str
    password: str


class ConfirmOrderRequest(BaseModel):
    selections: list[dict]


@app.post("/login")
def login(request: LoginRequest, response: Response):
    if not check_rate_limit(request.username):
        raise HTTPException(status_code=429, detail="too_many_attempts")

    if not verify_password(request.username, request.password):
        record_failed_attempt(request.username)
        raise HTTPException(status_code=401, detail="invalid_credentials")

    clear_failed_attempts(request.username)
    response.set_cookie(
        key=COOKIE_NAME,
        value=sign_session(request.username),
        httponly=True,
        samesite="lax",
        secure=False,  # reached over plain HTTP on the LAN; see CLAUDE.md
        path="/",
    )
    return {"username": request.username}


@app.post("/logout")
def logout(response: Response):
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/me")
def me(current_user: str = Depends(get_current_user)):
    return {"username": current_user}


@app.post("/fetch-order")
def fetch_order(request: FetchOrderRequest, current_user: str = Depends(get_current_user)):
    if request.branch not in BRANCHES:
        return {"started": False, "reason": "unknown_branch"}

    with _lock:
        if _state["running"]:
            return {"started": False, "reason": "already_running"}
        if _state["stage"] not in ("idle", "confirmed"):
            return {"started": False, "reason": "proposal_pending"}
        _state["running"] = True
        _state["stage"] = "building_proposal"
        _state["phase"] = "starting"
        _state["log"] = []
        _state["done"] = False
        _state["result"] = None
        _state["error"] = None
        _state["proposal"] = None
        _state["started_by"] = current_user
        _state["confirmed_by"] = None
        _state["branch"] = request.branch
    proposal_store.clear_proposal()

    credentials = BRANCHES[request.branch]
    thread = threading.Thread(
        target=_run_build_proposal,
        args=(credentials["username"], credentials["password"]),
        daemon=True,
    )
    thread.start()
    return {"started": True}


@app.post("/cancel")
def cancel(current_user: str = Depends(get_current_user)):
    """Stops an in-progress Phase A ("Building proposal") run. Deliberately
    only valid during building_proposal - Phase B ("Confirm & place
    orders") isn't cancellable here, since interrupting it mid-line could
    leave a real cart in an unclear state with no way to know what did or
    didn't get added; Phase A never touches a cart, so it's always safe to
    interrupt.

    Just sets a flag - the pipeline thread itself is the only thing that
    ever checks it (at cooperative checkpoints between Playwright calls,
    see retailio.PipelineCancelled) and acts on it. This endpoint never
    touches Playwright directly: closing a running BrowserContext from this
    request-handling thread - a different thread than the one that created
    it - isn't something Playwright's sync API supports, and can behave
    unpredictably depending on which call it interrupts. Cancellation may
    take a few seconds to actually land (however long the current
    in-flight step takes to reach its next checkpoint), not instantly."""
    global _cancel_requested
    with _lock:
        if not _state["running"] or _state["stage"] != "building_proposal":
            return {"cancelled": False, "reason": "not_cancellable"}
        _cancel_requested = True
    return {"cancelled": True}


@app.post("/discard-proposal")
def discard_proposal(current_user: str = Depends(get_current_user)):
    with _lock:
        if _state["running"]:
            return {"discarded": False, "reason": "already_running"}
        if _state["stage"] != "proposal_ready":
            return {"discarded": False, "reason": "no_pending_proposal"}
        _state["stage"] = "idle"
        _state["proposal"] = None
        _state["phase"] = "idle"
        _state["log"] = []
        _state["error"] = None
        _state["done"] = False
        _state["branch"] = None
        _state["started_by"] = None
    proposal_store.clear_proposal()
    return {"discarded": True}


@app.post("/confirm-order")
def confirm_order(request: ConfirmOrderRequest, current_user: str = Depends(get_current_user)):
    with _lock:
        if _state["running"]:
            return {"started": False, "reason": "already_running"}
        if _state["stage"] != "proposal_ready":
            return {"started": False, "reason": "no_pending_proposal"}
        _state["running"] = True
        _state["stage"] = "confirming"
        _state["phase"] = "starting"
        _state["log"] = []
        _state["done"] = False
        _state["error"] = None
        _state["confirmed_by"] = current_user

    thread = threading.Thread(
        target=_run_confirm,
        args=(request.selections,),
        daemon=True,
    )
    thread.start()
    return {"started": True}


@app.get("/branches")
def branches(current_user: str = Depends(get_current_user)):
    return {"branches": list(BRANCHES.keys()), "default": DEFAULT_BRANCH}


@app.get("/status")
def status(current_user: str = Depends(get_current_user)):
    with _lock:
        return dict(_state)


# Serves the built React app (dashboard/frontend/dist). Mounted last so it
# never shadows the API routes defined above.
FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
