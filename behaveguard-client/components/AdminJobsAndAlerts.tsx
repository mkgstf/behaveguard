"use client";

import { useCallback, useEffect, useState } from "react";
import { api, JobStatus, SecurityAlert } from "@/lib/api";

const JOB_STATUS_COLOR: Record<JobStatus["status"], string> = {
  queued: "text-muted",
  running: "text-amber",
  done: "text-cyan",
  failed: "text-danger",
};

const ALERT_SEVERITY_COLOR: Record<string, string> = {
  low: "text-muted",
  medium: "text-amber",
  high: "text-danger",
};

export default function AdminJobsAndAlerts() {
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
    // Neural retrains run in the background — poll so a queued job's
    // outcome shows up without the admin needing to manually refresh.
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, [load]);

  async function updateAlert(id: string, status: "ack" | "dismissed") {
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
      <div className="grid lg:grid-cols-2 gap-6">
        <div>
          <h2 className="font-mono-tight text-xs uppercase tracking-widest text-cyan mb-4">
            background retrain jobs
          </h2>
          {jobs.length === 0 ? (
            <p className="text-sm text-muted">No retrain jobs yet.</p>
          ) : (
            <div className="space-y-2 max-h-72 overflow-auto">
              {jobs.map((job) => (
                <div key={job.job_id} className="bg-surface-2 border border-border rounded-lg p-3 text-xs">
                  <div className="flex justify-between items-center">
                    <span className="font-mono-tight">{job.reason}</span>
                    <span className={`font-mono-tight uppercase ${JOB_STATUS_COLOR[job.status]}`}>{job.status}</span>
                  </div>
                  {job.status === "done" && job.result && (
                    <div className="text-muted mt-1">
                      {job.result.trained
                        ? `promoted: ${job.result.promoted ? "yes" : "no"}${
                            job.result.holdout_accuracy != null
                              ? ` · held-out accuracy ${Math.round(job.result.holdout_accuracy * 100)}%`
                              : ""
                          }`
                        : job.result.reason}
                    </div>
                  )}
                  {job.status === "failed" && job.error && <div className="text-danger mt-1">{job.error}</div>}
                </div>
              ))}
            </div>
          )}
        </div>

        <div>
          <h2 className="font-mono-tight text-xs uppercase tracking-widest text-amber mb-4">
            security alerts
          </h2>
          {alerts.length === 0 ? (
            <p className="text-sm text-muted">No open alerts.</p>
          ) : (
            <div className="space-y-2 max-h-72 overflow-auto">
              {alerts.map((alert) => (
                <div key={alert.id} className="bg-surface-2 border border-border rounded-lg p-3 text-xs">
                  <div className="flex justify-between items-center">
                    <span className={`font-mono-tight uppercase ${ALERT_SEVERITY_COLOR[alert.severity] || "text-muted"}`}>
                      {alert.kind.replaceAll("_", " ")}
                    </span>
                    <span className="text-muted">{new Date(alert.created_at).toLocaleString()}</span>
                  </div>
                  <div className="text-muted mt-1 font-mono-tight truncate">{JSON.stringify(alert.details)}</div>
                  <div className="flex gap-2 mt-2">
                    <button
                      disabled={busy === alert.id}
                      onClick={() => void updateAlert(alert.id, "ack")}
                      className="px-2 py-1 rounded bg-cyan/15 text-cyan disabled:opacity-40"
                    >
                      acknowledge
                    </button>
                    <button
                      disabled={busy === alert.id}
                      onClick={() => void updateAlert(alert.id, "dismissed")}
                      className="px-2 py-1 rounded bg-border text-muted disabled:opacity-40"
                    >
                      dismiss
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      {error && <p className="text-xs text-danger mt-4">{error}</p>}
    </section>
  );
}
