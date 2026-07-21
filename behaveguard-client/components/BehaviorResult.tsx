"use client";

import { useState } from "react";
import { EnrollmentResult, VerificationResult, SessionBehaviorMetrics } from "@/lib/api";
import { SessionData } from "@/lib/types";
import { formatDateTime } from "@/lib/format";
import SessionCharts from "@/components/SessionCharts";

type RetrainState = "idle" | "loading" | "done" | "error";

export default function BehaviorResult({
  result,
  onHome,
  enrollmentStats,
  sessionData,
  onRetrain,
  retrainState,
}: {
  result: EnrollmentResult | VerificationResult;
  onHome: () => void;
  enrollmentStats?: SessionBehaviorMetrics | null;
  sessionData?: SessionData | null;
  onRetrain?: () => void;
  retrainState?: RetrainState;
}) {
  const enrollment = "training" in result;
  if (enrollment) {
    return (
      <Shell onHome={onHome} accent="amber" eyebrow="enrollment saved" title={`${result.profile.label} has been updated`}>
        <div className="grid sm:grid-cols-3 gap-3 mb-6">
          <Stat label="profile samples" value={result.profile.enrollment_count} />
          <Stat label="training sessions used" value={result.training.session_count} />
          <Stat label="model status" value={result.training.svm_trained ? "trained" : "warming up"} />
        </div>
        {enrollmentStats && (
          <div className="mb-6">
            <h3 className="font-mono-tight text-xs uppercase tracking-widest text-muted mb-3">this session, at a glance</h3>
            <div className="grid sm:grid-cols-2 gap-3">
              <QuickBar label="typing speed" value={enrollmentStats.wpm} unit="wpm" max={120} accent="amber" />
              <QuickBar label="key dwell" value={enrollmentStats.dwell_ms} unit="ms" max={250} accent="cyan" />
              <QuickBar label="mouse speed" value={enrollmentStats.mouse_speed_pxs} unit="px/s" max={2000} accent="amber" />
              <QuickBar label="click precision" value={enrollmentStats.click_error_px} unit="px error" max={60} accent="cyan" invert />
            </div>
          </div>
        )}
        {sessionData && (
          <div className="mt-8">
            <h3 className="font-mono-tight text-xs uppercase tracking-widest text-muted mb-4">full session breakdown</h3>
            <SessionCharts data={sessionData} />
          </div>
        )}
        <p className="text-sm text-muted bg-surface border border-border rounded-lg p-4">
          Your profile was updated right away. A deeper background retrain has also been queued — it&apos;ll be reflected the next time your stats refresh, usually within a minute or two.
        </p>
      </Shell>
    );
  }

  // A 1:1 self-check (verifying against your own profile) can only ever add
  // your own session as training data, whatever the outcome — so the
  // retrain opt-in is offered whenever this session wasn't already folded
  // in automatically, match or not, rather than only for borderline matches.
  const canOfferRetrain = result.candidates.length === 1 && !result.auto_enrolled;
  const neutral = !result.match;
  const confidence = result.best.certainty;

  return (
    <Shell
      onHome={onHome}
      accent={neutral ? "neutral" : "cyan"}
      eyebrow={result.candidates.length === 1 ? "1:1 verification" : "1:N identification"}
      title={result.match ? `${result.best.label} is the closest match` : "This session wasn't confidently recognized"}
    >
      <p className="text-sm text-muted mb-6 -mt-4">
        {neutral
          ? "That's a normal outcome, not a failure — behavioral rhythm shifts session to session. Nothing was recorded against you either way."
          : "Your typing and mouse rhythm this session closely resembled the enrolled profile below."}
      </p>

      {/* One clear headline number instead of five raw model fields side by
          side (similarity/certainty/neural-vote/personal-neural/decision) —
          those often disagreed or showed "n/a", which read as confusing
          rather than informative to someone who isn't building the model. */}
      <div className="flex items-center gap-5 bg-surface border border-border rounded-xl p-5 mb-6">
        <ConfidenceRing value={confidence} neutral={neutral} />
        <div>
          <div className="text-sm text-muted mb-1">confidence this was {result.best.label}</div>
          <div className={`font-mono-tight text-3xl ${neutral ? "text-muted" : "text-cyan"}`}>{confidence}%</div>
        </div>
      </div>

      {result.context && (
        <div className="bg-surface border border-border rounded-xl p-4 mb-6 text-sm">
          <h3 className="font-mono-tight text-xs uppercase tracking-widest text-muted mb-3">how this stacks up</h3>
          <div className="grid sm:grid-cols-3 gap-3">
            <Stat label="checked against" value={`${result.context.candidate_pool_size} enrolled profile${result.context.candidate_pool_size === 1 ? "" : "s"}`} />
            <Stat label="other close matches" value={result.context.close_matches} />
            <Stat label="sessions used to train model" value={result.context.total_training_sessions} />
          </div>
        </div>
      )}

      {result.candidates.length > 1 && (
        <div className="mb-6">
          <h3 className="font-mono-tight text-xs uppercase tracking-widest text-muted mb-3">ranked candidates</h3>
          <div className="space-y-2">
            {result.candidates.map((row, index) => (
              <div key={row.profile_id} className="bg-surface border border-border rounded-lg p-3 flex items-center gap-4">
                <span className="font-mono-tight text-muted">#{index + 1}</span><span className="flex-1">{row.label}</span>
                <span className="font-mono-tight text-sm text-cyan">{row.certainty}% confidence</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {result.auto_enrolled && (
        <div className="bg-cyan/10 border border-cyan/30 rounded-xl p-4 text-sm text-cyan mb-6">
          This confident match was automatically added as another training sample — your profile keeps improving every time you verify successfully.
        </div>
      )}
      {canOfferRetrain && onRetrain && (
        <div className="bg-amber/10 border border-amber/30 rounded-xl p-4 mb-6">
          <p className="text-sm text-amber mb-3">
            {result.match
              ? "This matched, but wasn't confident enough to add automatically. If this really was you, adding it as training data can help sharpen future checks."
              : "This wasn't added to your profile automatically. If this really was you typing, you can add it anyway — it can only ever help future checks recognize you."}
          </p>
          <button
            onClick={onRetrain}
            disabled={retrainState === "loading" || retrainState === "done"}
            className="cursor-pointer bg-amber text-bg rounded-lg px-6 py-3 font-mono-tight text-xs uppercase tracking-widest disabled:opacity-50"
          >
            {retrainState === "loading" ? "adding…" : retrainState === "done" ? "added ✓" : "add this session as training data"}
          </button>
          {retrainState === "error" && <p className="text-danger text-xs mt-2">Couldn&apos;t add this sample — try again from the home screen.</p>}
        </div>
      )}

      {sessionData && (
        <div className="mt-8 mb-6">
          <h3 className="font-mono-tight text-xs uppercase tracking-widest text-muted mb-4">full session breakdown</h3>
          <SessionCharts data={sessionData} />
        </div>
      )}

      <TechnicalDetails result={result} />
    </Shell>
  );
}

function ConfidenceRing({ value, neutral }: { value: number; neutral: boolean }) {
  const size = 72;
  const stroke = 6;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - Math.min(100, Math.max(0, value)) / 100);
  const color = neutral ? "var(--muted)" : "var(--cyan)";
  return (
    <svg width={size} height={size} className="shrink-0 -rotate-90">
      <circle cx={size / 2} cy={size / 2} r={radius} stroke="var(--surface-2)" strokeWidth={stroke} fill="none" />
      <circle
        cx={size / 2} cy={size / 2} r={radius} stroke={color} strokeWidth={stroke} fill="none"
        strokeDasharray={circumference} strokeDashoffset={offset} strokeLinecap="round"
      />
    </svg>
  );
}

function TechnicalDetails({ result }: { result: VerificationResult }) {
  const [open, setOpen] = useState(false);
  const rows: { label: string; value: string }[] = [
    { label: "similarity", value: `${result.best.similarity}%` },
    { label: "certainty", value: `${result.best.certainty}%` },
  ];
  if (result.best.neural_certainty != null) rows.push({ label: "neural vote", value: `${result.best.neural_certainty}%` });
  if (result.best.personal_neural_certainty != null) rows.push({ label: "personal neural", value: `${result.best.personal_neural_certainty}%` });
  rows.push({ label: "decision threshold", value: `${result.threshold}%` });
  rows.push({ label: "top-candidate margin", value: `${result.margin}%` });

  return (
    <div className="border border-border rounded-xl overflow-hidden">
      <button onClick={() => setOpen((v) => !v)} className="cursor-pointer w-full flex items-center justify-between px-4 py-3 text-xs font-mono-tight uppercase tracking-widest text-muted hover:text-text transition">
        technical details
        <span>{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="px-4 pb-4 pt-1 space-y-3">
          {result.detail && result.detail.map((row) => <ScoreBar key={row.category} label={row.category} value={row.similarity} />)}
          <div className="grid sm:grid-cols-3 gap-2 pt-2">
            {rows.map((row) => (
              <div key={row.label} className="bg-surface-2 rounded-lg px-3 py-2 text-xs flex justify-between">
                <span className="text-muted">{row.label}</span>
                <span className="font-mono-tight">{row.value}</span>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted pt-1">model trained {formatDateTime(result.model_version)}</p>
        </div>
      )}
    </div>
  );
}

function Shell({ children, onHome, accent, eyebrow, title }: { children: React.ReactNode; onHome: () => void; accent: "amber" | "cyan" | "neutral"; eyebrow: string; title: string }) {
  const accentClass = accent === "amber" ? "text-amber" : accent === "cyan" ? "text-cyan" : "text-muted";
  return (
    <div className="min-h-screen overflow-y-auto">
      {/* Back button pinned to the actual top-left, same treatment as the
          "cancel" button during tasks — not a full-width button sitting at
          the bottom after a long scroll of charts and stats. */}
      <div className="relative w-full pt-6 px-4">
        <button onClick={onHome} className="cursor-pointer absolute left-4 top-6 z-20 text-sm text-muted font-mono-tight py-2.5 px-3 hover:text-text transition inline-flex items-center gap-1.5">
          ← home
        </button>
      </div>
      <div className="max-w-3xl mx-auto px-6 pb-16 pt-10 fade-up">
        <div className={`font-mono-tight text-xs uppercase tracking-[0.3em] mb-3 ${accentClass}`}>{eyebrow}</div>
        <h2 className="text-3xl font-semibold mb-8">{title}</h2>
        {children}
      </div>
    </div>
  );
}
function Stat({ label, value }: { label: string; value: string | number }) { return <div className="bg-surface-2 rounded-xl p-4"><div className="font-mono-tight text-xl">{value}</div><div className="text-xs text-muted mt-1">{label}</div></div>; }
function ScoreBar({ label, value }: { label: string; value: number }) { return <div><div className="flex justify-between text-xs mb-1"><span>{label}</span><span className="font-mono-tight text-muted">{value}%</span></div><div className="h-2 bg-surface-2 rounded-full overflow-hidden"><div className="h-full bg-cyan rounded-full" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div></div>; }
function QuickBar({ label, value, unit, max, accent, invert }: { label: string; value: number | null; unit: string; max: number; accent: "amber" | "cyan"; invert?: boolean }) {
  const pct = value == null ? 0 : Math.max(4, Math.min(100, (value / max) * 100));
  return (
    <div className="bg-surface-2 rounded-lg p-3">
      <div className="flex justify-between text-xs mb-2"><span className="text-muted">{label}</span><span className="font-mono-tight">{value == null ? "n/a" : `${Math.round(value * 10) / 10} ${unit}`}</span></div>
      <div className="h-2 bg-bg rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${accent === "amber" ? "bg-amber" : "bg-cyan"}`} style={{ width: `${invert ? 100 - pct + 4 : pct}%` }} />
      </div>
    </div>
  );
}
