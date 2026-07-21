"use client";

import { EnrollmentResult, VerificationResult, SessionBehaviorMetrics } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

type RetrainState = "idle" | "loading" | "done" | "error";

export default function BehaviorResult({
  result,
  onHome,
  enrollmentStats,
  onRetrain,
  retrainState,
}: {
  result: EnrollmentResult | VerificationResult;
  onHome: () => void;
  enrollmentStats?: SessionBehaviorMetrics | null;
  onRetrain?: () => void;
  retrainState?: RetrainState;
}) {
  const enrollment = "training" in result;
  if (enrollment) {
    return (
      <Shell onHome={onHome} accent="amber" eyebrow="enrollment saved" title={`${result.profile.label} has been updated`}>
        <div className="grid sm:grid-cols-3 gap-3 mb-6">
          <Stat label="profile samples" value={result.profile.enrollment_count} />
          <Stat label="model sessions" value={result.training.session_count} />
          <Stat label="SVM" value={result.training.svm_trained ? "trained" : "waiting"} />
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
        <p className="text-sm text-muted bg-surface border border-border rounded-lg p-4">
          The profile centroid and saved model were retrained right away. The deeper neural fusion retrain has been queued and runs in the background — it&apos;ll be reflected the next time your stats refresh.
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

  return (
    <Shell
      onHome={onHome}
      accent={neutral ? "neutral" : "cyan"}
      eyebrow={result.candidates.length === 1 ? "1:1 verification" : "1:N identification"}
      title={result.match ? `${result.best.label} is the closest verified match` : "This session didn't confidently match"}
    >
      {neutral && (
        <p className="text-sm text-muted mb-6 -mt-4">
          That&apos;s a normal outcome, not a failure — behavioral rhythm shifts session to session. Nothing was recorded against you either way.
        </p>
      )}
      <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3 mb-6">
        <Stat label="similarity" value={`${result.best.similarity}%`} />
        <Stat label="certainty" value={`${result.best.certainty}%`} />
        <Stat label="neural vote" value={result.best.neural_certainty == null ? "n/a" : `${result.best.neural_certainty}%`} />
        <Stat label="personal neural" value={result.best.personal_neural_certainty == null ? "n/a" : `${result.best.personal_neural_certainty}%`} />
        <Stat label="decision" value={result.match ? "match" : "no match"} />
      </div>

      {result.context && (
        <div className="bg-surface border border-border rounded-xl p-4 mb-7 text-sm">
          <h3 className="font-mono-tight text-xs uppercase tracking-widest text-muted mb-3">how this stacks up</h3>
          <div className="grid sm:grid-cols-3 gap-3">
            <Stat label="tested among" value={`${result.context.candidate_pool_size} profile${result.context.candidate_pool_size === 1 ? "" : "s"}`} />
            <Stat label="also significantly close" value={result.context.close_matches} />
            <Stat label="total training sessions" value={result.context.total_training_sessions} />
          </div>
        </div>
      )}

      {result.detail && (
        <div className="space-y-3 mb-7">
          <h3 className="font-mono-tight text-xs uppercase tracking-widest text-muted">detailed behavioral comparison</h3>
          {result.detail.map((row) => <ScoreBar key={row.category} label={row.category} value={row.similarity} />)}
        </div>
      )}
      {result.candidates.length > 1 && (
        <div>
          <h3 className="font-mono-tight text-xs uppercase tracking-widest text-muted mb-3">ranked candidates</h3>
          <div className="space-y-2">
            {result.candidates.map((row, index) => (
              <div key={row.profile_id} className="bg-surface border border-border rounded-lg p-3 flex items-center gap-4">
                <span className="font-mono-tight text-muted">#{index + 1}</span><span className="flex-1">{row.label}</span>
                <span className="font-mono-tight text-sm text-cyan">{row.similarity}%</span><span className="font-mono-tight text-xs text-muted">SVM {row.svm_certainty}% · neural {row.neural_certainty == null ? "n/a" : `${row.neural_certainty}%`} · personal {row.personal_neural_certainty == null ? "n/a" : `${row.personal_neural_certainty}%`}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {result.auto_enrolled && (
        <div className="mt-7 bg-cyan/10 border border-cyan/30 rounded-xl p-4 text-sm text-cyan">
          This confident match was automatically folded in as an additional enrollment sample — your profile keeps improving every time you verify successfully.
        </div>
      )}
      {canOfferRetrain && onRetrain && (
        <div className="mt-7 bg-amber/10 border border-amber/30 rounded-xl p-4">
          <p className="text-sm text-amber mb-3">
            {result.match
              ? "This matched, but wasn't confident enough to fold in automatically. If this really was you, adding it as training data can help sharpen future verifications."
              : "This wasn't added to your profile automatically. If this really was you typing, you can add it anyway — it can only ever help future checks recognize you."}
          </p>
          <button
            onClick={onRetrain}
            disabled={retrainState === "loading" || retrainState === "done"}
            className="cursor-pointer bg-amber text-bg rounded-lg px-6 py-3 font-mono-tight text-xs uppercase tracking-widest disabled:opacity-50"
          >
            {retrainState === "loading" ? "adding…" : retrainState === "done" ? "added ✓" : "use this session to help retrain my profile"}
          </button>
          {retrainState === "error" && <p className="text-danger text-xs mt-2">Couldn&apos;t add this sample — try again from the home screen.</p>}
        </div>
      )}
      <p className="text-xs text-muted mt-5">Decision threshold {result.threshold}% · top-candidate margin {result.margin}% · model trained {formatDateTime(result.model_version)}</p>
    </Shell>
  );
}

function Shell({ children, onHome, accent, eyebrow, title }: { children: React.ReactNode; onHome: () => void; accent: "amber" | "cyan" | "neutral"; eyebrow: string; title: string }) {
  const accentClass = accent === "amber" ? "text-amber" : accent === "cyan" ? "text-cyan" : "text-muted";
  return (
    <div className="min-h-screen px-6 py-10 overflow-y-auto">
      <div className="max-w-3xl mx-auto fade-up">
        <div className={`font-mono-tight text-xs uppercase tracking-[0.3em] mb-3 ${accentClass}`}>{eyebrow}</div>
        <h2 className="text-3xl font-semibold mb-8">{title}</h2>
        {children}
        <button onClick={onHome} className="cursor-pointer mt-9 bg-text text-bg rounded-lg px-7 py-3.5 font-mono-tight text-xs uppercase tracking-widest">back home</button>
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
