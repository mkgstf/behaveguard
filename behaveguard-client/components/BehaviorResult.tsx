"use client";

import { useEffect, useState } from "react";
import { EnrollmentResult, VerificationResult } from "@/lib/api";
import { api } from "@/lib/api";
import { Profile } from "@/lib/types";

export default function BehaviorResult({ result, onHome }: { result: EnrollmentResult | VerificationResult; onHome: () => void }) {
  const enrollment = "training" in result;
  const verification = enrollment ? null : result;
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [trueProfileId, setTrueProfileId] = useState(verification?.best.profile_id || "");
  const [feedbackState, setFeedbackState] = useState<"idle" | "saving" | "saved" | "discarded">("idle");
  const [feedbackError, setFeedbackError] = useState("");
  useEffect(() => {
    if (verification) void api.profiles().then((rows) => setProfiles(rows.filter((profile) => !profile.blacklisted))).catch(() => undefined);
  }, [verification]);

  async function submitIdentity(profileId: string | null) {
    if (!verification || feedbackState !== "idle") return;
    setFeedbackState("saving");
    setFeedbackError("");
    try {
      const predictionCorrect = Boolean(profileId && verification.match && profileId === verification.best.profile_id);
      await api.submitFeedback(verification.review_sample_id, predictionCorrect, profileId);
      setFeedbackState(profileId ? "saved" : "discarded");
    } catch (error) {
      setFeedbackState("idle");
      setFeedbackError(error instanceof Error ? error.message : "Could not save feedback");
    }
  }
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
      <div className="grid sm:grid-cols-4 gap-3 mb-6">
        <Stat label="similarity" value={`${result.best.similarity}%`} />
        <Stat label="certainty" value={`${result.best.certainty}%`} />
        <Stat label="neural vote" value={result.best.neural_certainty == null ? "n/a" : `${result.best.neural_certainty}%`} />
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
                <span className="font-mono-tight text-sm text-cyan">{row.similarity}%</span><span className="font-mono-tight text-xs text-muted">SVM {row.svm_certainty}% · neural {row.neural_certainty == null ? "n/a" : `${row.neural_certainty}%`}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      <section className="mt-7 bg-surface border border-border rounded-xl p-5">
        <div className="font-mono-tight text-xs uppercase tracking-widest text-amber">testing feedback</div>
        <h3 className="text-lg font-semibold mt-2">Who produced this sample?</h3>
        <p className="text-sm text-muted mt-1">Your answer is saved for admin review. It will not affect the model until an admin approves it and retrains.</p>
        {feedbackState === "saved" || feedbackState === "discarded" ? (
          <div className="mt-4 rounded-lg bg-cyan/10 text-cyan px-4 py-3 text-sm">{feedbackState === "saved" ? "Identity saved in the review queue." : "Sample marked not to use for training."}</div>
        ) : (
          <div className="flex flex-wrap gap-3 mt-4">
            <select value={trueProfileId} onChange={(event) => setTrueProfileId(event.target.value)} className="min-w-52 bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm">
              {profiles.length === 0 && <option value={result.best.profile_id}>{result.best.label}</option>}
              {profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.label}</option>)}
            </select>
            <button disabled={!trueProfileId || feedbackState === "saving"} onClick={() => void submitIdentity(trueProfileId)} className="bg-cyan text-bg rounded-lg px-4 py-2 text-xs font-mono-tight uppercase disabled:opacity-50">{feedbackState === "saving" ? "saving…" : "save identity"}</button>
            <button disabled={feedbackState === "saving"} onClick={() => void submitIdentity(null)} className="border border-border text-muted rounded-lg px-4 py-2 text-xs font-mono-tight uppercase disabled:opacity-50">not listed / discard</button>
          </div>
        )}
        {feedbackError && <p className="text-xs text-danger mt-3">{feedbackError}</p>}
      </section>
      <p className="text-xs text-muted mt-5">Decision threshold {result.threshold}% · top-candidate margin {result.margin}% · model {result.model_version.slice(0, 19)}</p>
    </Shell>
  );
}

function Shell({ children, onHome, accent, eyebrow, title }: { children: React.ReactNode; onHome: () => void; accent: "amber" | "cyan"; eyebrow: string; title: string }) {
  return <div className="flex-1 px-6 py-10 overflow-y-auto"><div className="max-w-3xl mx-auto fade-up"><div className={`font-mono-tight text-xs uppercase tracking-[0.3em] mb-3 ${accent === "amber" ? "text-amber" : "text-cyan"}`}>{eyebrow}</div><h2 className="text-3xl font-semibold mb-8">{title}</h2>{children}<button onClick={onHome} className="mt-9 bg-text text-bg rounded-lg px-7 py-3 font-mono-tight text-xs uppercase tracking-widest">back home</button></div></div>;
}
function Stat({ label, value }: { label: string; value: string | number }) { return <div className="bg-surface-2 rounded-xl p-4"><div className="font-mono-tight text-xl">{value}</div><div className="text-xs text-muted mt-1">{label}</div></div>; }
function ScoreBar({ label, value }: { label: string; value: number }) { return <div><div className="flex justify-between text-xs mb-1"><span>{label}</span><span className="font-mono-tight text-muted">{value}%</span></div><div className="h-2 bg-surface-2 rounded-full overflow-hidden"><div className="h-full bg-cyan rounded-full" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div></div>; }
