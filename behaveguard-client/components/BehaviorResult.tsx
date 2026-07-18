"use client";

import { EnrollmentResult, VerificationResult } from "@/lib/api";

export default function BehaviorResult({ result, onHome }: { result: EnrollmentResult | VerificationResult; onHome: () => void }) {
  const enrollment = "training" in result;
  if (enrollment) {
    return (
      <Shell onHome={onHome} accent="amber" eyebrow="enrollment saved" title={`${result.profile.label} has been updated`}>
        <div className="grid sm:grid-cols-3 gap-3 mb-6">
          <Stat label="profile samples" value={result.profile.enrollment_count} />
          <Stat label="model sessions" value={result.training.session_count} />
          <Stat label="SVM" value={result.training.svm_trained ? "trained" : "waiting"} />
        </div>
        <p className="text-sm text-muted bg-surface border border-border rounded-lg p-4">
          The profile centroid and saved model were retrained. {result.neural.trained ? `The BiLSTM + TCN model also trained (loss ${result.neural.loss}).` : result.neural.reason}
        </p>
      </Shell>
    );
  }
  return (
    <Shell onHome={onHome} accent="cyan" eyebrow={result.candidates.length === 1 ? "1:1 verification" : "1:N identification"} title={result.match ? `${result.best.label} is the closest verified match` : "No confident match"}>
      <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3 mb-6">
        <Stat label="similarity" value={`${result.best.similarity}%`} />
        <Stat label="certainty" value={`${result.best.certainty}%`} />
        <Stat label="neural vote" value={result.best.neural_certainty == null ? "n/a" : `${result.best.neural_certainty}%`} />
        <Stat label="personal neural" value={result.best.personal_neural_certainty == null ? "n/a" : `${result.best.personal_neural_certainty}%`} />
        <Stat label="decision" value={result.match ? "match" : "no match"} />
      </div>
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
      <p className="text-xs text-muted mt-5">Decision threshold {result.threshold}% · top-candidate margin {result.margin}% · model {result.model_version.slice(0, 19)}</p>
    </Shell>
  );
}

function Shell({ children, onHome, accent, eyebrow, title }: { children: React.ReactNode; onHome: () => void; accent: "amber" | "cyan"; eyebrow: string; title: string }) {
  return <div className="flex-1 px-6 py-10 overflow-y-auto"><div className="max-w-3xl mx-auto fade-up"><div className={`font-mono-tight text-xs uppercase tracking-[0.3em] mb-3 ${accent === "amber" ? "text-amber" : "text-cyan"}`}>{eyebrow}</div><h2 className="text-3xl font-semibold mb-8">{title}</h2>{children}<button onClick={onHome} className="mt-9 bg-text text-bg rounded-lg px-7 py-3 font-mono-tight text-xs uppercase tracking-widest">back home</button></div></div>;
}
function Stat({ label, value }: { label: string; value: string | number }) { return <div className="bg-surface-2 rounded-xl p-4"><div className="font-mono-tight text-xl">{value}</div><div className="text-xs text-muted mt-1">{label}</div></div>; }
function ScoreBar({ label, value }: { label: string; value: number }) { return <div><div className="flex justify-between text-xs mb-1"><span>{label}</span><span className="font-mono-tight text-muted">{value}%</span></div><div className="h-2 bg-surface-2 rounded-full overflow-hidden"><div className="h-full bg-cyan rounded-full" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div></div>; }
