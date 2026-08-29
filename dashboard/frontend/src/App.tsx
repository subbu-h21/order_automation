import { useEffect, useRef, useState } from "react";
import "./App.css";

const API_BASE = "";

const PHASE_LABELS: Record<string, string> = {
  idle: "Idle",
  starting: "Starting...",
  checking_retailio_login: "Checking Retailio login...",
  waiting_for_manual_login: "Waiting for you to complete login/OTP in the opened browser window...",
  fetching_crm: "Fetching orders from CRM...",
  building_curated_list: "Building curated product list...",
  matching_products: "Searching, matching, and pricing products across every supplier...",
  placing_orders: "Placing your confirmed order in each supplier's cart...",
  done: "Done",
};

// Reasons the backend can reject /fetch-order, /confirm-order, or
// /discard-proposal (see the matching `reason` values in app.py) - shown so
// a rejected action never fails silently with the button just resetting.
const ACTION_REASON_LABELS: Record<string, string> = {
  already_running: "Something else is already running right now - try again in a moment.",
  proposal_pending: "A proposal is already waiting for review below - confirm or discard it first.",
  no_pending_proposal: "There's no pending proposal anymore - this page may be out of date, refreshing...",
  unknown_branch: "Unknown branch selected.",
};

interface StageDef {
  key: string;
  label: string;
  phases: string[];
}

// The two phases each have their own real stages, mirrored from
// dashboard/backend/app.py's _run_build_proposal / _run_confirm. Used only
// to render the progress tracker; the phase string from /status remains the
// single source of truth.
const PHASE_A_STAGES: StageDef[] = [
  { key: "login", label: "Retailio login", phases: ["starting", "checking_retailio_login", "waiting_for_manual_login"] },
  { key: "crm", label: "CRM fetch", phases: ["fetching_crm"] },
  { key: "curate", label: "Curate list", phases: ["building_curated_list"] },
  { key: "match", label: "Match & price", phases: ["matching_products"] },
];

const PHASE_B_STAGES: StageDef[] = [
  { key: "login", label: "Retailio login", phases: ["starting", "checking_retailio_login", "waiting_for_manual_login"] },
  { key: "place", label: "Place orders", phases: ["placing_orders"] },
];

type StageState = "upcoming" | "current" | "action" | "complete" | "error";

function stageStates(stages: StageDef[], phase: string, hasError: boolean): StageState[] {
  const activeIndex = stages.findIndex((s) => s.phases.includes(phase));
  if (activeIndex === -1) return stages.map(() => "upcoming");

  return stages.map((_stage, i) => {
    if (i < activeIndex) return "complete";
    if (i > activeIndex) return "upcoming";
    if (hasError) return "error";
    if (phase === "waiting_for_manual_login") return "action";
    return "current";
  });
}

// --- Proposal (Phase A output / Phase B input) types ------------------------

interface Candidate {
  matched_product_name: string;
  available_qty: number;
  has_scheme: boolean;
  scheme_buy_qty: number | null;
  scheme_free_qty: number | null;
  mrp: number | null;
  ptr: number | null;
  similarity: number;
  confident: boolean;
  card_text: string;
  index: number;
}

interface ProposedAllocation {
  supplier: string;
  matched_product_name: string;
  qty: number;
  has_scheme: boolean;
  mrp: number | null;
  ptr: number | null;
}

interface ProposalItem {
  product_name: string;
  required_qty: number;
  remaining_qty: number;
  candidates: Record<string, Candidate[]>;
  proposed_allocations: ProposedAllocation[];
  low_confidence_matches: { supplier: string; matched_product_name: string; similarity: number }[];
}

interface Proposal {
  proposal_id: string;
  items: ProposalItem[];
}

// The owner's editable, in-progress decision - lives only in this tab's
// local state until "Confirm & place orders" sends it to the backend.
interface SelectionLine {
  supplier: string;
  matched_product_name: string;
  qty: number;
}

interface Selection {
  product_name: string;
  required_qty: number;
  allocations: SelectionLine[];
}

// --- Final (Phase B) result types - unchanged shape from the original report

interface Mapping {
  crm_product: string;
  retailio_product: string;
  supplier: string;
  qty: number;
  has_scheme: boolean;
}

interface AlteredItem {
  crm_product: string;
  required_qty: number;
  allocations: { supplier: string; qty: number }[];
  unfulfilled_qty: number;
}

interface MissedItem {
  crm_product: string;
  required_qty: number;
  unfulfilled_qty: number;
}

interface RejectedMatch {
  supplier: string;
  matched_product_name: string;
  similarity: number;
}

interface NeedsReviewItem {
  crm_product: string;
  required_qty: number;
  rejected_matches: RejectedMatch[];
}

interface Result {
  mappings: Mapping[];
  altered: AlteredItem[];
  missed: MissedItem[];
  needs_review: NeedsReviewItem[];
}

interface Status {
  running: boolean;
  phase: string;
  log: string[];
  done: boolean;
  result: Result | null;
  error: string | null;
  started_by: string | null;
  stage: string;
  proposal: Proposal | null;
  confirmed_by: string | null;
  branch: string | null;
}

// The one shape used throughout the brand: a two-piece capsule. Doubles as
// the favicon, the wordmark, and (at larger scale) each pipeline stage.
function CapsuleIcon({ size = 22 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true" focusable="false">
      <g transform="rotate(-45 12 12)">
        <rect x="4" y="9" width="16" height="6" rx="3" fill="var(--rx-tint)" />
        <line x1="12" y1="9" x2="12" y2="15" stroke="var(--rx)" strokeWidth="1.5" />
      </g>
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg className="pipeline-check" viewBox="0 0 12 12" width="12" height="12" aria-hidden="true" focusable="false">
      <path d="M2.5 6.3l2.2 2.2L9.5 3.3" fill="none" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Wordmark({ hero = false, loading = false }: { hero?: boolean; loading?: boolean }) {
  return (
    <div className={`wordmark${loading ? " wordmark--loading" : ""}`}>
      <span className="wordmark-mark">
        <CapsuleIcon />
      </span>
      <div className="wordmark-text">
        <h1>Order Automation</h1>
        {hero && <span className="wordmark-tagline">Shubhada Pharma &middot; supplier reordering</span>}
      </div>
    </div>
  );
}

function PipelineTracker({ stages, phase, hasError }: { stages: StageDef[]; phase: string; hasError: boolean }) {
  const states = stageStates(stages, phase, hasError);
  return (
    <ol className="pipeline" role="list" aria-label="Pipeline progress">
      {stages.map((stage, i) => {
        const state = states[i];
        return (
          <li
            key={stage.key}
            className={`pipeline-stage is-${state}`}
            aria-current={state === "current" || state === "action" ? "step" : undefined}
          >
            <div className="pipeline-node">
              <span className="pipeline-capsule">
                <span className="pipeline-capsule-fill" />
                <span className="pipeline-capsule-seam" />
                {state === "complete" && <CheckIcon />}
              </span>
              <span className="pipeline-label">
                <span className="pipeline-index">{i + 1}</span>
                {stage.label}
              </span>
            </div>
            {i < stages.length - 1 && <span className="pipeline-track" />}
          </li>
        );
      })}
    </ol>
  );
}

function money(value: number | null): string {
  return value == null ? "—" : `₹${value.toFixed(2)}`;
}

function flattenCandidates(item: ProposalItem): { supplier: string; candidate: Candidate }[] {
  return Object.keys(item.candidates).flatMap((supplier) =>
    item.candidates[supplier].map((candidate) => ({ supplier, candidate }))
  );
}

function findCandidate(item: ProposalItem, supplier: string, matchedProductName: string): Candidate | undefined {
  return (item.candidates[supplier] ?? []).find((c) => c.matched_product_name === matchedProductName);
}

function lineKey(supplier: string, matchedProductName: string): string {
  return `${supplier}|||${matchedProductName}`;
}

function safeId(text: string): string {
  return text.replace(/[^a-zA-Z0-9]+/g, "-").toLowerCase();
}

function ReviewItem({
  item,
  selection,
  onChange,
}: {
  item: ProposalItem;
  selection: Selection;
  onChange: (next: Selection) => void;
}) {
  const flatCandidates = flattenCandidates(item);
  const totalQty = selection.allocations.reduce((sum, a) => sum + (a.qty || 0), 0);
  const coverage: "none" | "partial" | "full" =
    totalQty <= 0 ? "none" : totalQty >= item.required_qty ? "full" : "partial";

  const updateLine = (idx: number, patch: Partial<SelectionLine>) => {
    const lines = selection.allocations.slice();
    lines[idx] = { ...lines[idx], ...patch };
    onChange({ ...selection, allocations: lines });
  };

  const removeLine = (idx: number) => {
    onChange({ ...selection, allocations: selection.allocations.filter((_, i) => i !== idx) });
  };

  const addLine = () => {
    const used = new Set(selection.allocations.map((a) => lineKey(a.supplier, a.matched_product_name)));
    const next = flatCandidates.find((fc) => !used.has(lineKey(fc.supplier, fc.candidate.matched_product_name)));
    if (!next) return;
    const remaining = Math.max(item.required_qty - totalQty, 1);
    onChange({
      ...selection,
      allocations: [
        ...selection.allocations,
        {
          supplier: next.supplier,
          matched_product_name: next.candidate.matched_product_name,
          qty: Math.min(remaining, next.candidate.available_qty || remaining),
        },
      ],
    });
  };

  return (
    <section className={`result-card review-item review-item--${coverage}`}>
      <div className="result-head">
        <h2>{item.product_name}</h2>
        <span className="result-count">Required {item.required_qty}</span>
        <span className={`pill ${coverage === "full" ? "pill--yes" : "pill--no"}`}>
          {coverage === "full" ? "Fully covered" : coverage === "partial" ? `${totalQty} / ${item.required_qty}` : "No allocation"}
        </span>
      </div>

      {flatCandidates.length === 0 ? (
        <p className="result-empty">No match found on any supplier for this product.</p>
      ) : (
        <>
          {selection.allocations.map((line, idx) => {
            const candidate = findCandidate(item, line.supplier, line.matched_product_name);
            // A supplier+product already used by another row of this same
            // product is disabled here (greyed out, not hidden) - splitting
            // the same exact line across two rows would just double-order
            // it rather than mean anything, and this row's own current
            // choice must stay selectable regardless.
            const usedElsewhere = new Set(
              selection.allocations
                .filter((_, i) => i !== idx)
                .map((a) => lineKey(a.supplier, a.matched_product_name))
            );
            return (
              <div className="review-row" key={idx}>
                <select
                  aria-label={`Supplier and product for row ${idx + 1} of ${item.product_name}`}
                  value={lineKey(line.supplier, line.matched_product_name)}
                  onChange={(e) => {
                    const [supplier, matched_product_name] = e.target.value.split("|||");
                    updateLine(idx, { supplier, matched_product_name });
                  }}
                >
                  {flatCandidates.map((fc) => (
                    <option
                      key={lineKey(fc.supplier, fc.candidate.matched_product_name)}
                      value={lineKey(fc.supplier, fc.candidate.matched_product_name)}
                      disabled={usedElsewhere.has(lineKey(fc.supplier, fc.candidate.matched_product_name))}
                    >
                      {fc.supplier} &mdash; {fc.candidate.matched_product_name} (Qty {fc.candidate.available_qty}
                      {fc.candidate.ptr != null ? `, PTR ${money(fc.candidate.ptr)}` : ""}
                      {fc.candidate.has_scheme ? ", scheme" : ""}
                      {!fc.candidate.confident ? ", low-confidence match" : ""})
                    </option>
                  ))}
                </select>
                <div className="field review-qty-field">
                  <label htmlFor={`qty-${safeId(item.product_name)}-${idx}`}>Qty</label>
                  <input
                    id={`qty-${safeId(item.product_name)}-${idx}`}
                    type="number"
                    min={0}
                    value={line.qty}
                    onChange={(e) => updateLine(idx, { qty: Math.max(0, Number(e.target.value) || 0) })}
                  />
                </div>
                <span className="review-price">
                  <span className="review-ptr">PTR {money(candidate?.ptr ?? null)}</span>
                  <span className="review-mrp">MRP {money(candidate?.mrp ?? null)}</span>
                </span>
                <button type="button" className="logout-button review-remove" onClick={() => removeLine(idx)}>
                  Remove
                </button>
              </div>
            );
          })}
          <button
            type="button"
            className="logout-button review-add"
            onClick={addLine}
            disabled={flatCandidates.length <= selection.allocations.length}
          >
            + Add another supplier
          </button>
        </>
      )}

      {item.low_confidence_matches.length > 0 && (
        <p className="result-empty">
          {item.low_confidence_matches.map((r, j) => (
            <span className="mini-row" key={j}>
              No confident match at {r.supplier} (closest: &quot;{r.matched_product_name}&quot;, similarity {r.similarity})
            </span>
          ))}
        </p>
      )}
    </section>
  );
}

function ProposalReview({
  proposal,
  selections,
  onChangeSelections,
  onConfirm,
  onDiscard,
  confirming,
  discarding,
}: {
  proposal: Proposal;
  selections: Selection[];
  onChangeSelections: (next: Selection[]) => void;
  onConfirm: () => void;
  onDiscard: () => void;
  confirming: boolean;
  discarding: boolean;
}) {
  return (
    <div className="review">
      <div className="control-strip review-toolbar">
        <div>
          <p className="review-summary">
            <span className="result-count">{proposal.items.length}</span> product(s) proposed &mdash; review each one below,
            then confirm to place the real orders on Retailio.
          </p>
          <p className="review-hint">
            <strong>PTR</strong> = Price to Retailer, what the pharmacy actually pays &mdash; this is what differs
            between suppliers. <strong>MRP</strong> = the printed retail price, fixed regardless of supplier.
          </p>
        </div>
        <div className="review-actions">
          <button type="button" className="logout-button" onClick={onDiscard} disabled={discarding || confirming}>
            {discarding ? "Discarding..." : "Discard proposal"}
          </button>
          <button type="button" onClick={onConfirm} disabled={confirming || discarding}>
            {confirming ? "Placing orders..." : "Confirm & place orders"}
          </button>
        </div>
      </div>

      <div className="results">
        {proposal.items.map((item, i) => (
          <ReviewItem
            key={item.product_name}
            item={item}
            selection={selections[i]}
            onChange={(next) => {
              const copy = selections.slice();
              copy[i] = next;
              onChangeSelections(copy);
            }}
          />
        ))}
      </div>
    </div>
  );
}

function seedSelections(proposal: Proposal): Selection[] {
  return proposal.items.map((item) => ({
    product_name: item.product_name,
    required_qty: item.required_qty,
    allocations: item.proposed_allocations.map((a) => ({
      supplier: a.supplier,
      matched_product_name: a.matched_product_name,
      qty: a.qty,
    })),
  }));
}

function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [starting, setStarting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [branches, setBranches] = useState<string[]>([]);
  const [selectedBranch, setSelectedBranch] = useState<string>("");
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [currentUser, setCurrentUser] = useState<string | null>(null);
  const [loginUsername, setLoginUsername] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loggingIn, setLoggingIn] = useState(false);
  const [selections, setSelections] = useState<Selection[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);
  const logEndRef = useRef<HTMLDivElement | null>(null);
  const seededProposalId = useRef<string | null>(null);

  const poll = async () => {
    const res = await fetch(`${API_BASE}/status`);
    if (res.status === 401) {
      // Session died mid-use (logged out elsewhere, secret rotated, etc.) -
      // fall back to the login form instead of rendering stale/null status.
      setAuthenticated(false);
      setCurrentUser(null);
      return;
    }
    const data: Status = await res.json();
    setStatus(data);
  };

  const handleFetchOrder = async () => {
    setStarting(true);
    setActionError(null);
    const res = await fetch(`${API_BASE}/fetch-order`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ branch: selectedBranch }),
    }).then((r) => r.json());
    if (!res.started) setActionError(ACTION_REASON_LABELS[res.reason] ?? "Couldn't start - please try again.");
    setStarting(false);
    poll();
  };

  const handleConfirm = async () => {
    setConfirming(true);
    setActionError(null);
    const proposalItems = status?.proposal?.items ?? [];
    const res = await fetch(`${API_BASE}/confirm-order`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        selections: selections.map((s) => ({
          product_name: s.product_name,
          required_qty: s.required_qty,
          allocations: s.allocations.filter((a) => a.qty > 0),
          // Carried through unedited so the final report can still show
          // what Phase A flagged as low-confidence, even after confirming.
          low_confidence_matches: proposalItems.find((p) => p.product_name === s.product_name)?.low_confidence_matches ?? [],
        })),
      }),
    }).then((r) => r.json());
    if (!res.started) setActionError(ACTION_REASON_LABELS[res.reason] ?? "Couldn't start placing orders - please try again.");
    setConfirming(false);
    poll();
  };

  const handleDiscard = async () => {
    setDiscarding(true);
    setActionError(null);
    const res = await fetch(`${API_BASE}/discard-proposal`, { method: "POST" }).then((r) => r.json());
    if (!res.discarded) setActionError(ACTION_REASON_LABELS[res.reason] ?? "Couldn't discard - please try again.");
    setDiscarding(false);
    poll();
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoggingIn(true);
    setLoginError(null);
    try {
      const res = await fetch(`${API_BASE}/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: loginUsername, password: loginPassword }),
      });
      if (res.ok) {
        setCurrentUser(loginUsername);
        setLoginPassword("");
        setAuthenticated(true);
      } else if (res.status === 429) {
        setLoginError("Too many failed attempts. Try again in a few minutes.");
      } else {
        setLoginError("Invalid username or password.");
      }
    } finally {
      setLoggingIn(false);
    }
  };

  const handleLogout = async () => {
    await fetch(`${API_BASE}/logout`, { method: "POST" });
    setAuthenticated(false);
    setCurrentUser(null);
    setStatus(null);
  };

  // Checked once on mount, independent of the polling loop below - this is
  // what decides whether to show the login form or the dashboard.
  useEffect(() => {
    fetch(`${API_BASE}/me`)
      .then(async (res) => {
        if (!res.ok) {
          setAuthenticated(false);
          return;
        }
        const data: { username: string } = await res.json();
        setCurrentUser(data.username);
        setAuthenticated(true);
      })
      .catch(() => setAuthenticated(false));
  }, []);

  useEffect(() => {
    if (authenticated !== true) return;

    poll();
    fetch(`${API_BASE}/branches`)
      .then((res) => res.json())
      .then((data: { branches: string[]; default: string }) => {
        setBranches(data.branches);
        setSelectedBranch(data.default);
      });
    // Every open tab/device keeps polling the shared backend state
    // continuously, not just the one that triggered a run - so everyone
    // watching stays in sync regardless of who started it. This is also
    // what lets a reviewer reopen the dashboard hours or days later and see
    // the exact same pending proposal.
    const intervalId = window.setInterval(poll, 1500);

    // Browsers throttle setInterval in backgrounded tabs (down to ~1/min
    // after a few minutes) to save battery/CPU - that's platform policy,
    // not something JS can override. So also poll immediately the moment
    // a tab becomes visible/focused again, so it snaps to current state
    // instantly instead of showing whatever it was stuck on.
    const onVisible = () => {
      if (document.visibilityState === "visible") poll();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", poll);

    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", poll);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authenticated]);

  // Purely cosmetic: keeps the live log feed scrolled to its latest line.
  // Independent of the polling effect above - safe to change on its own.
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ block: "end" });
  }, [status?.log.length]);

  // Seeds the owner's editable selections from the server's proposed
  // defaults - but ONLY when a genuinely new proposal shows up (tracked by
  // proposal_id), never on every routine 1.5s poll of the *same* still-
  // pending proposal. Getting this wrong would silently wipe out an
  // in-progress review every second and a half.
  useEffect(() => {
    const proposal = status?.proposal;
    if (!proposal || seededProposalId.current === proposal.proposal_id) return;
    seededProposalId.current = proposal.proposal_id;
    setSelections(seedSelections(proposal));
  }, [status?.proposal]);

  const isRunning = status?.running ?? false;
  const stage = status?.stage ?? "idle";
  const phase = status?.phase ?? "idle";
  const phaseLabel = status ? PHASE_LABELS[status.phase] ?? status.phase : "";
  const hasError = Boolean(status?.error);
  const showTracker = stage === "building_proposal" || stage === "confirming";
  const trackerStages = stage === "confirming" ? PHASE_B_STAGES : PHASE_A_STAGES;
  const canFetch = stage === "idle" || stage === "confirmed";

  if (authenticated === null) {
    return (
      <div className="dashboard dashboard--centered">
        <Wordmark hero loading />
      </div>
    );
  }

  if (authenticated === false) {
    return (
      <div className="dashboard dashboard--centered">
        <div className="login-card">
          <Wordmark hero />
          <form className="login-form" onSubmit={handleLogin}>
            <div className="field">
              <label htmlFor="login-username">Username</label>
              <input
                id="login-username"
                type="text"
                placeholder="Your staff username"
                value={loginUsername}
                onChange={(e) => setLoginUsername(e.target.value)}
                autoFocus
              />
            </div>
            <div className="field">
              <label htmlFor="login-password">Password</label>
              <input
                id="login-password"
                type="password"
                placeholder="Your password"
                value={loginPassword}
                onChange={(e) => setLoginPassword(e.target.value)}
              />
            </div>
            <button type="submit" disabled={loggingIn || !loginUsername || !loginPassword}>
              {loggingIn ? "Logging in..." : "Log in"}
            </button>
          </form>
          {loginError && (
            <div className="alert alert--error" style={{ marginTop: 16, marginBottom: 0 }}>
              <p>{loginError}</p>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard">
      <div className="header-row">
        <Wordmark />
        <div className="session-chip">
          {currentUser && (
            <span>
              Signed in as <strong>{currentUser}</strong>
            </span>
          )}
          <button className="logout-button" onClick={handleLogout}>Log out</button>
        </div>
      </div>

      <div className="control-strip">
        <div className="field">
          <label htmlFor="branch-select">Branch</label>
          <select
            id="branch-select"
            value={selectedBranch}
            onChange={(e) => setSelectedBranch(e.target.value)}
            disabled={isRunning || starting || !canFetch}
          >
            {branches.map((branch) => (
              <option key={branch} value={branch}>{branch}</option>
            ))}
          </select>
        </div>

        <button onClick={handleFetchOrder} disabled={isRunning || starting || !selectedBranch || !canFetch}>
          {isRunning && stage === "building_proposal" ? "Building proposal..." : "Fetch order"}
        </button>

        {!canFetch && (
          <p className="review-summary" style={{ margin: 0 }}>
            A proposal is waiting for review below &mdash; confirm or discard it before starting a new fetch.
          </p>
        )}
      </div>

      {actionError && (
        <div className="alert alert--error" role="alert">
          <p>{actionError}</p>
        </div>
      )}

      {showTracker && (
        <div className="progress">
          <div className="progress-head">
            <span className="phase">{phaseLabel}</span>
            {stage === "building_proposal" && status?.started_by && (
              <span className="started-by">Started by {status.started_by}</span>
            )}
            {stage === "confirming" && status?.confirmed_by && (
              <span className="started-by">Confirmed by {status.confirmed_by}</span>
            )}
          </div>

          <PipelineTracker stages={trackerStages} phase={phase} hasError={hasError} />

          {phase === "waiting_for_manual_login" && (
            <div className="alert alert--action" role="status">
              <span className="alert-badge">Action needed</span>
              <p>{PHASE_LABELS.waiting_for_manual_login}</p>
            </div>
          )}
        </div>
      )}

      {status && status.log.length > 0 && (
        <div className="progress">
          <div className="log">
            {status.log.map((line, i) => (
              <div key={i} className="log-line">{line}</div>
            ))}
            <div ref={logEndRef} />
          </div>
        </div>
      )}

      {status?.branch && (
        <p className="branch-banner">
          Orders for the <strong>{status.branch}</strong> branch.
        </p>
      )}

      {status?.error && (
        <div className="alert alert--error">
          <span className="alert-badge">Error</span>
          <div>
            <h3>The pipeline stopped</h3>
            <pre>{status.error}</pre>
          </div>
        </div>
      )}

      {stage === "proposal_ready" && status?.proposal && selections.length === status.proposal.items.length && (
        <ProposalReview
          proposal={status.proposal}
          selections={selections}
          onChangeSelections={setSelections}
          onConfirm={handleConfirm}
          onDiscard={handleDiscard}
          confirming={confirming}
          discarding={discarding}
        />
      )}

      {stage === "confirmed" && status?.result && (
        <div className="results">
          <section className="result-card result-card--brick">
            <div className="result-head">
              <h2>Missed items</h2>
              <span className="result-count">{status.result.missed.length}</span>
            </div>
            {status.result.missed.length === 0 ? (
              <p className="result-empty">Nothing missed &mdash; every confirmed item got placed.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th scope="col">CRM product</th><th scope="col">Required qty</th><th scope="col">Unfulfilled qty</th></tr>
                  </thead>
                  <tbody>
                    {status.result.missed.map((m, i) => (
                      <tr key={i}>
                        <td className="wrap">{m.crm_product}</td>
                        <td className="num">{m.required_qty}</td>
                        <td className="num">{m.unfulfilled_qty}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="result-card result-card--amber">
            <div className="result-head">
              <h2>Needs review</h2>
              <span className="result-count">{status.result.needs_review.length}</span>
            </div>
            {status.result.needs_review.length === 0 ? (
              <p className="result-empty">Nothing flagged during placement.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th scope="col">CRM product</th><th scope="col">Required qty</th><th scope="col">Rejected Retailio matches</th></tr>
                  </thead>
                  <tbody>
                    {status.result.needs_review.map((n, i) => (
                      <tr key={i}>
                        <td className="wrap">{n.crm_product}</td>
                        <td className="num">{n.required_qty}</td>
                        <td>
                          {n.rejected_matches.map((r, j) => (
                            <div key={j} className="mini-row">
                              {r.supplier}: &quot;{r.matched_product_name}&quot; (similarity <span className="num">{r.similarity}</span>)
                            </div>
                          ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="result-card result-card--slate">
            <div className="result-head">
              <h2>Altered / split allocations</h2>
              <span className="result-count">{status.result.altered.length}</span>
            </div>
            {status.result.altered.length === 0 ? (
              <p className="result-empty">No splits or partial fills &mdash; every confirmed item was placed from a single supplier.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th scope="col">CRM product</th><th scope="col">Required qty</th><th scope="col">Allocations</th><th scope="col">Unfulfilled qty</th></tr>
                  </thead>
                  <tbody>
                    {status.result.altered.map((a, i) => (
                      <tr key={i}>
                        <td className="wrap">{a.crm_product}</td>
                        <td className="num">{a.required_qty}</td>
                        <td>
                          {a.allocations.map((al, j) => (
                            <div key={j} className="mini-row">{al.supplier}: <span className="num">{al.qty}</span></div>
                          ))}
                        </td>
                        <td className="num">{a.unfulfilled_qty}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="result-card result-card--rx">
            <div className="result-head">
              <h2>Product mapping</h2>
              <span className="result-count">{status.result.mappings.length}</span>
            </div>
            {status.result.mappings.length === 0 ? (
              <p className="result-empty">No products were placed this run.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">CRM product name</th>
                      <th scope="col">Retailio matched product</th>
                      <th scope="col">Supplier</th>
                      <th scope="col">Qty</th>
                      <th scope="col">Scheme</th>
                    </tr>
                  </thead>
                  <tbody>
                    {status.result.mappings.map((m, i) => (
                      <tr key={i}>
                        <td className="wrap">{m.crm_product}</td>
                        <td className="wrap">{m.retailio_product}</td>
                        <td>{m.supplier}</td>
                        <td className="num">{m.qty}</td>
                        <td>
                          <span className={`pill ${m.has_scheme ? "pill--yes" : "pill--no"}`}>
                            {m.has_scheme ? "Yes" : "No"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

export default App;
