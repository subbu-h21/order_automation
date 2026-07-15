import { useEffect, useState } from "react";
import "./App.css";

const API_BASE = "";

const PHASE_LABELS: Record<string, string> = {
  idle: "Idle",
  starting: "Starting...",
  checking_retailio_login: "Checking Retailio login...",
  waiting_for_manual_login: "Waiting for you to complete login/OTP in the opened browser window...",
  fetching_crm: "Fetching orders from CRM...",
  building_curated_list: "Building curated product list...",
  ordering: "Searching and allocating products on Retailio...",
  done: "Done",
};

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
}

function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [starting, setStarting] = useState(false);
  const [branches, setBranches] = useState<string[]>([]);
  const [selectedBranch, setSelectedBranch] = useState<string>("");
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [loginUsername, setLoginUsername] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loggingIn, setLoggingIn] = useState(false);

  const poll = async () => {
    const res = await fetch(`${API_BASE}/status`);
    if (res.status === 401) {
      // Session died mid-use (logged out elsewhere, secret rotated, etc.) -
      // fall back to the login form instead of rendering stale/null status.
      setAuthenticated(false);
      return;
    }
    const data: Status = await res.json();
    setStatus(data);
  };

  const handleFetchOrder = async () => {
    setStarting(true);
    await fetch(`${API_BASE}/fetch-order`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ branch: selectedBranch }),
    });
    setStarting(false);
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
    setStatus(null);
  };

  // Checked once on mount, independent of the polling loop below - this is
  // what decides whether to show the login form or the dashboard.
  useEffect(() => {
    fetch(`${API_BASE}/me`)
      .then((res) => setAuthenticated(res.ok))
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
    // continuously, not just the one that clicked "Fetch Order" - so
    // everyone watching stays in sync regardless of who started the run.
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

  const isRunning = status?.running ?? false;
  const phaseLabel = status ? PHASE_LABELS[status.phase] ?? status.phase : "";

  if (authenticated === null) {
    return (
      <div className="dashboard">
        <h1>Order Automation</h1>
      </div>
    );
  }

  if (authenticated === false) {
    return (
      <div className="dashboard">
        <h1>Order Automation</h1>
        <form className="controls" onSubmit={handleLogin}>
          <input
            type="text"
            placeholder="Username"
            value={loginUsername}
            onChange={(e) => setLoginUsername(e.target.value)}
            autoFocus
          />
          <input
            type="password"
            placeholder="Password"
            value={loginPassword}
            onChange={(e) => setLoginPassword(e.target.value)}
          />
          <button type="submit" disabled={loggingIn || !loginUsername || !loginPassword}>
            {loggingIn ? "Logging in..." : "Log in"}
          </button>
        </form>
        {loginError && (
          <div className="error">
            <pre>{loginError}</pre>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="dashboard">
      <div className="header-row">
        <h1>Order Automation</h1>
        <button className="logout-button" onClick={handleLogout}>Log out</button>
      </div>

      <div className="controls">
        <select
          value={selectedBranch}
          onChange={(e) => setSelectedBranch(e.target.value)}
          disabled={isRunning || starting}
        >
          {branches.map((branch) => (
            <option key={branch} value={branch}>{branch}</option>
          ))}
        </select>

        <button onClick={handleFetchOrder} disabled={isRunning || starting || !selectedBranch}>
          {isRunning ? "Running..." : "Fetch Order"}
        </button>
      </div>

      {status && (status.running || status.phase !== "idle") && (
        <div className="progress">
          <div className="phase">
            {phaseLabel}
            {status.started_by && <span className="started-by"> — started by {status.started_by}</span>}
          </div>
          <div className="log">
            {status.log.map((line, i) => (
              <div key={i} className="log-line">{line}</div>
            ))}
          </div>
        </div>
      )}

      {status?.error && (
        <div className="error">
          <h3>Error</h3>
          <pre>{status.error}</pre>
        </div>
      )}

      {status?.done && status.result && (
        <div className="results">
          <section>
            <h2>Missed Items ({status.result.missed.length})</h2>
            <table>
              <thead>
                <tr><th>CRM Product</th><th>Required Qty</th><th>Unfulfilled Qty</th></tr>
              </thead>
              <tbody>
                {status.result.missed.map((m, i) => (
                  <tr key={i}>
                    <td>{m.crm_product}</td>
                    <td>{m.required_qty}</td>
                    <td>{m.unfulfilled_qty}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section>
            <h2>Needs Review — rejected low-confidence matches ({status.result.needs_review.length})</h2>
            <table>
              <thead>
                <tr><th>CRM Product</th><th>Required Qty</th><th>Rejected Retailio Matches</th></tr>
              </thead>
              <tbody>
                {status.result.needs_review.map((n, i) => (
                  <tr key={i}>
                    <td>{n.crm_product}</td>
                    <td>{n.required_qty}</td>
                    <td>
                      {n.rejected_matches.map((r, j) => (
                        <div key={j}>{r.supplier}: "{r.matched_product_name}" (similarity {r.similarity})</div>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section>
            <h2>Altered / Split Allocations ({status.result.altered.length})</h2>
            <table>
              <thead>
                <tr><th>CRM Product</th><th>Required Qty</th><th>Allocations</th><th>Unfulfilled Qty</th></tr>
              </thead>
              <tbody>
                {status.result.altered.map((a, i) => (
                  <tr key={i}>
                    <td>{a.crm_product}</td>
                    <td>{a.required_qty}</td>
                    <td>
                      {a.allocations.map((al, j) => (
                        <div key={j}>{al.supplier}: {al.qty}</div>
                      ))}
                    </td>
                    <td>{a.unfulfilled_qty}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section>
            <h2>Product Mapping ({status.result.mappings.length})</h2>
            <table>
              <thead>
                <tr>
                  <th>CRM Product Name</th>
                  <th>Retailio Matched Product</th>
                  <th>Supplier</th>
                  <th>Qty</th>
                  <th>Scheme</th>
                </tr>
              </thead>
              <tbody>
                {status.result.mappings.map((m, i) => (
                  <tr key={i}>
                    <td>{m.crm_product}</td>
                    <td>{m.retailio_product}</td>
                    <td>{m.supplier}</td>
                    <td>{m.qty}</td>
                    <td>{m.has_scheme ? "Yes" : "No"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      )}
    </div>
  );
}

export default App;
