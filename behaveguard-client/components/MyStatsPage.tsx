"use client";

import { MyStats, SessionBehaviorMetrics } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { AVERAGE_TYPIST_WPM, globalTypingPercentile } from "@/lib/benchmarks";

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
      <div className="min-h-screen">
        <div className="relative w-full pt-6 px-4">
          <BackLink onBack={onBack} />
        </div>
        <div className="max-w-3xl mx-auto px-6 fade-up">
          <p className="text-sm text-muted mt-8">No stats yet — enroll or add a sample to see your behavioral highlights here.</p>
        </div>
      </div>
    );
  }

  const history = stats.history;
  const latest = stats.latest;
  const card = stats.card;
  const values = (key: keyof SessionBehaviorMetrics) => history.map((row) => row[key] as number | null);
  const wpm = latest.wpm;
  const vsAverage = wpm != null ? Math.round(((wpm - AVERAGE_TYPIST_WPM) / AVERAGE_TYPIST_WPM) * 100) : null;
  const percentile = wpm != null ? globalTypingPercentile(wpm) : null;

  return (
    <div className="min-h-screen overflow-y-auto">
      <div className="relative w-full pt-6 px-4">
        <BackLink onBack={onBack} />
      </div>
      <div className="max-w-3xl mx-auto px-6 pb-16 fade-up">
        <div className="font-mono-tight text-xs uppercase tracking-[0.3em] text-cyan mb-3 mt-4">my stats</div>
        <h2 className="text-3xl font-semibold mb-2">{stats.profile.label}</h2>
        <p className="text-sm text-muted mb-8">
          {history.length} enrolled session{history.length === 1 ? "" : "s"} · latest sample {formatDateTime(latest.collected_at)}
        </p>

        {/* Headline row: the numbers a normal person actually cares about,
            with plain-language context rather than raw units alone. */}
        <div className="grid sm:grid-cols-3 gap-4 mb-10">
          <BigStat
            label="typing speed"
            value={wpm == null ? "—" : `${Math.round(wpm)}`}
            unit="wpm"
            sub={vsAverage == null ? "—" : vsAverage >= 0 ? `${vsAverage}% faster than the average typist (~${AVERAGE_TYPIST_WPM} wpm)` : `${Math.abs(vsAverage)}% slower than the average typist (~${AVERAGE_TYPIST_WPM} wpm)`}
            accent="amber"
          />
          <BigStat
            label="vs. global typists"
            value={percentile == null ? "—" : `top ${Math.max(1, Math.round(100 - percentile))}%`}
            unit=""
            sub="based on published typing-test benchmarks, not this app's own users"
            accent="cyan"
          />
          <BigStat
            label="click precision"
            value={latest.click_error_px == null ? "—" : `${Math.round(latest.click_error_px)}`}
            unit="px off-target"
            sub="lower is more precise"
            accent="amber"
          />
        </div>

        {card && (
          <p className="text-xs text-muted mb-6 -mt-6">
            Also ranked <span className="text-text font-mono-tight">{card.rank}</span> among {card.population_size} profile{card.population_size === 1 ? "" : "s"} enrolled on this instance.
          </p>
        )}

        <h3 className="font-mono-tight text-xs uppercase tracking-widest text-muted mb-4">session history</h3>
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
    <button onClick={onBack} className="cursor-pointer absolute left-4 top-6 z-20 text-sm text-muted font-mono-tight py-2.5 px-3 hover:text-text transition inline-flex items-center gap-1.5">
      ← home
    </button>
  );
}

function BigStat({ label, value, unit, sub, accent }: { label: string; value: string; unit: string; sub: string; accent: "amber" | "cyan" }) {
  return (
    <div className="bg-surface border border-border rounded-xl p-5">
      <div className="text-[10px] uppercase tracking-wider text-muted mb-2">{label}</div>
      <div className={`font-mono-tight text-3xl tabular-nums ${accent === "amber" ? "text-amber" : "text-cyan"}`}>
        {value}
        {unit && <span className="text-sm text-muted ml-1.5">{unit}</span>}
      </div>
      <div className="text-xs text-muted mt-2 leading-relaxed">{sub}</div>
    </div>
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
