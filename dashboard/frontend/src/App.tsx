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
}

function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [starting, setStarting] = useState(false);
  const [branches, setBranches] = useState<string[]>([]);
  const [selectedBranch, setSelectedBranch] = useState<string>("");
  const intervalRef = useRef<number | null>(null);

  const poll = async () => {
    const res = await fetch(`${API_BASE}/status`);
    const data: Status = await res.json();
    setStatus(data);
    if (data.done && intervalRef.current) {
      window.clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
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
    intervalRef.current = window.setInterval(poll, 1500);
  };

  useEffect(() => {
    poll();
    fetch(`${API_BASE}/branches`)
      .then((res) => res.json())
      .then((data: { branches: string[]; default: string }) => {
        setBranches(data.branches);
        setSelectedBranch(data.default);
      });
    return () => {
      if (intervalRef.current) window.clearInterval(intervalRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const isRunning = status?.running ?? false;
  const phaseLabel = status ? PHASE_LABELS[status.phase] ?? status.phase : "";

  return (
    <div className="dashboard">
      <h1>Order Automation</h1>

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
          <div className="phase">{phaseLabel}</div>
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
