"use client";

import { MyStats, SessionBehaviorMetrics } from "@/lib/api";

// Which metrics to show, in what order, with a rough "good" direction used
// only for the bar's fill length (not for any pass/fail judgement) — purely
// a normalization display, computed against this profile's own history.
const METRICS: { key: keyof SessionBehaviorMetrics; label: string; unit: string }[] = [
  { key: "wpm", label: "typing speed", unit: "wpm" },
  { key: "dwell_ms", label: "key dwell", unit: "ms" },
  { key: "flight_ms", label: "key flight", unit: "ms" },
  { key: "rhythm_cv", label: "rhythm variability", unit: "" },
  { key: "mouse_speed_pxs", label: "mouse speed", unit: "px/s" },
  { key: "click_error_px", label: "click precision", unit: "px error" },
  { key: "tracking_error_px", label: "tracking error", unit: "px" },
  { key: "tremor_px", label: "hand steadiness", unit: "px tremor" },
];

export default function MyStatsPage({ stats, onBack }: { stats: MyStats | null; onBack: () => void }) {
  if (!stats || !stats.latest) {
    return (
      <div className="min-h-screen px-6 py-10">
        <div className="max-w-3xl mx-auto fade-up">
          <BackLink onBack={onBack} />
          <p className="text-sm text-muted mt-8">No stats yet — enroll or add a sample to see your behavioral highlights here.</p>
        </div>
      </div>
    );
  }

  const history = stats.history;
  const latest = stats.latest;
  const values = (key: keyof SessionBehaviorMetrics) => history.map((row) => row[key] as number | null);

  return (
    <div className="min-h-screen px-6 py-10 overflow-y-auto">
      <div className="max-w-3xl mx-auto fade-up">
        <BackLink onBack={onBack} />
        <div className="font-mono-tight text-xs uppercase tracking-[0.3em] text-cyan mb-3 mt-8">my stats</div>
        <h2 className="text-3xl font-semibold mb-2">{stats.profile.label}</h2>
        <p className="text-sm text-muted mb-8">
          {history.length} enrolled session{history.length === 1 ? "" : "s"} · latest sample {new Date(latest.collected_at).toLocaleString()}
        </p>

        <div className="space-y-5 mb-10">
          {METRICS.map((metric) => (
            <MetricRow key={metric.key} label={metric.label} unit={metric.unit} history={values(metric.key)} />
          ))}
        </div>
      </div>
    </div>
  );
}

function BackLink({ onBack }: { onBack: () => void }) {
  return (
    <button onClick={onBack} className="text-sm text-muted font-mono-tight py-2 -ml-1 pl-1 pr-3 hover:text-text inline-flex items-center gap-1.5">
      ← home
    </button>
  );
}

function MetricRow({ label, unit, history }: { label: string; unit: string; history: (number | null)[] }) {
  const clean = history.filter((v): v is number => v != null && Number.isFinite(v));
  if (clean.length === 0) return null;
  const latest = clean[clean.length - 1];
  const max = Math.max(...clean);
  const min = Math.min(...clean);
  const range = max - min || 1;

  return (
    <div>
      <div className="flex justify-between items-baseline mb-2">
        <span className="text-sm">{label}</span>
        <span className="font-mono-tight text-sm text-cyan tabular-nums">
          {Math.round(latest * 100) / 100}{unit ? ` ${unit}` : ""}
        </span>
      </div>
      {/* Simple sparkline bar chart across enrolled sessions — no chart
          library needed, keeps this consistent with the rest of the app's
          hand-built bars/score meters. */}
      <div className="flex items-end gap-1 h-12 bg-surface-2 rounded-lg px-2 py-2">
        {clean.map((value, i) => {
          const pct = Math.max(6, ((value - min) / range) * 100);
          const isLast = i === clean.length - 1;
          return (
            <div
              key={i}
              title={`${Math.round(value * 100) / 100}${unit ? ` ${unit}` : ""}`}
              className={`flex-1 rounded-sm transition-all ${isLast ? "bg-cyan" : "bg-cyan/30"}`}
              style={{ height: `${pct}%` }}
            />
          );
        })}
      </div>
    </div>
  );
}
