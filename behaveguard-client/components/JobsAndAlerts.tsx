"use client";

import { useCallback, useEffect, useState } from "react";
import { api, JobStatus, SecurityAlert } from "@/lib/api";

const ALERT_LABELS: Record<SecurityAlert["kind"], string> = {
  replay_suspected: "exact-payload replay",
  far_spike: "near-threshold clustering",
  brute_force: "repeated blocked attempts",
};

export default function JobsAndAlerts() {
  const [jobs, setJobs] = useState<JobStatus[]>([]);
  const [alerts, setAlerts] = useState<SecurityAlert[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(() => {
    void api.jobs().then(setJobs).catch(() => undefined);
    void api.securityAlerts("open").then(setAlerts).catch(() => undefined);
  }, []);

  useEffect(() => {
    load();
    // Retrain jobs run in the background — poll rather than requiring a
    // manual refresh to see a "queued" job move to "done".
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, [load]);

  async function resolveAlert(id: string, status: "ack" | "dismissed") {
    setBusy(id);
    setError("");
    try {
      await api.updateSecurityAlert(id, status);
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update alert");
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="bg-surface border border-border rounded-xl p-5 mb-8">
      <div className="font-mono-tight text-xs uppercase tracking-widest text-cyan mb-4">jobs &amp; security</div>

      <h3 className="font-mono-tight text-xs uppercase tracking-widest text-muted mb-2">background retrain jobs</h3>
      {jobs.length === 0 ? (
        <p className="text-sm text-muted mb-6">No retrain jobs yet.</p>
      ) : (
        <div className="space-y-2 mb-6">
          {jobs.slice(0, 8).map((job) => (
            <div key={job.job_id} className="bg-surface-2 border border-border rounded-lg p-3 flex items-center gap-4 text-xs">
              <span
                className={`px-2 py-1 rounded font-mono-tight uppercase ${
                  job.status === "done"
                    ? "bg-cyan/15 text-cyan"
                    : job.status === "failed"
                      ? "bg-danger/15 text-danger"
                      : "bg-amber/15 text-amber"
                }`}
              >
                {job.status}
              </span>
              <span className="flex-1 text-muted">{job.reason}</span>
              {job.result && (
                <span className="font-mono-tight text-muted">
                  {job.result.trained
                    ? `${job.result.promoted ? "promoted" : "not promoted"}${job.result.holdout_accuracy != null ? ` · ${Math.round(job.result.holdout_accuracy * 100)}% held-out` : ""}`
                    : job.result.reason || "not trained"}
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      <h3 className="font-mono-tight text-xs uppercase tracking-widest text-muted mb-2">open security alerts</h3>
      {alerts.length === 0 ? (
        <p className="text-sm text-muted">No open alerts. This checks for exact-payload replay, scores clustered just under the accept threshold, and repeated rate-limit blocks.</p>
      ) : (
        <div className="space-y-2">
          {alerts.map((alert) => (
            <div key={alert.id} className="bg-surface-2 border border-border rounded-lg p-3 flex flex-wrap items-center gap-3 text-xs">
              <span className={`px-2 py-1 rounded font-mono-tight uppercase ${alert.severity === "high" ? "bg-danger/15 text-danger" : "bg-amber/15 text-amber"}`}>
                {alert.severity}
              </span>
              <span className="flex-1 min-w-40">{ALERT_LABELS[alert.kind]}</span>
              <span className="text-muted">{new Date(alert.created_at).toLocaleString()}</span>
              <button
                disabled={busy === alert.id}
                onClick={() => void resolveAlert(alert.id, "ack")}
                className="px-3 py-1.5 rounded bg-cyan/15 text-cyan font-mono-tight disabled:opacity-40"
              >
                ack
              </button>
              <button
                disabled={busy === alert.id}
                onClick={() => void resolveAlert(alert.id, "dismissed")}
                className="px-3 py-1.5 rounded bg-border text-muted font-mono-tight disabled:opacity-40"
              >
                dismiss
              </button>
            </div>
          ))}
        </div>
      )}
      {error && <p className="text-xs text-danger mt-3">{error}</p>}
    </section>
  );
}
