"use client";

import { useCallback, useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AdminAnalytics, api, ReviewComparison } from "@/lib/api";
import { formatDate, formatDateTime } from "@/lib/format";
import JobsAndAlerts from "@/components/JobsAndAlerts";
import AdminJobsAndAlerts from "@/components/AdminJobsAndAlerts";

export default function AdminDashboard({ onBack }: { onBack: () => void }) {
  const [data, setData] = useState<AdminAnalytics | null>(null);
  const [error, setError] = useState("");
  const [comparison, setComparison] = useState<string[]>([]);
  const [assignments, setAssignments] = useState<Record<string, string>>({});
  const [reviewComparisons, setReviewComparisons] = useState<Record<string, ReviewComparison>>({});
  const [comparisonBusy, setComparisonBusy] = useState("");
  const [reviewBusy, setReviewBusy] = useState("");
  const [trainingMessage, setTrainingMessage] = useState("");
  const [claimTokens, setClaimTokens] = useState<Record<string, string>>({});
  const [claimTokenBusy, setClaimTokenBusy] = useState("");
  const [claimTokenError, setClaimTokenError] = useState<Record<string, string>>({});
  const load = useCallback(() => api.analytics().then(setData).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);
  async function blacklist(id: string, value: boolean) { await api.blacklist(id, value); await load(); }
  async function remove(id: string, label: string) { if (window.confirm(`Delete ${label} and all enrollment sessions?`)) { await api.deleteProfile(id); await load(); } }
  async function generateClaimToken(id: string) {
    setClaimTokenBusy(id);
    setClaimTokenError((current) => ({ ...current, [id]: "" }));
    try {
      const result = await api.adminClaimToken(id);
      setClaimTokens((current) => ({ ...current, [id]: result.token }));
    } catch (reason) {
      // Most common cause: this profile already has an owner — claim
      // tokens are only for pre-existing/legacy (e.g. xlsx-imported)
      // profiles with no account linked yet, not self-enrolled ones.
      setClaimTokenError((current) => ({ ...current, [id]: reason instanceof Error ? reason.message : "Could not generate a claim token" }));
    } finally {
      setClaimTokenBusy("");
    }
  }
  async function review(id: string, action: "approve" | "reject", fallbackProfileId?: string | null) {
    setReviewBusy(id);
    setError("");
    try { await api.reviewSample(id, action, assignments[id] || fallbackProfileId || undefined); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Review action failed"); }
    finally { setReviewBusy(""); }
  }
  async function retrain() {
    setReviewBusy("retrain"); setTrainingMessage(""); setError("");
    try {
      const trained = await api.retrain();
      setTrainingMessage(`Model rebuilt with ${trained.classical.session_count} sessions across ${trained.classical.profile_count} profiles; ${trained.included_review_samples} approved test sample${trained.included_review_samples === 1 ? "" : "s"} marked trained. Neural fusion retrain queued (job ${trained.neural_retrain_job_id.slice(0, 8)}…) — check Jobs below for its outcome.`);
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Retraining failed"); }
    finally { setReviewBusy(""); }
  }
  async function selectReviewProfile(reviewId: string, profileId: string) {
    setAssignments((current) => ({ ...current, [reviewId]: profileId }));
    if (!profileId) return;
    setComparisonBusy(reviewId); setError("");
    try {
      const comparisonResult = await api.reviewComparison(reviewId, profileId);
      setReviewComparisons((current) => ({ ...current, [reviewId]: comparisonResult }));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Comparison failed"); }
    finally { setComparisonBusy(""); }
  }
  if (!data) return <div className="p-10 text-muted">{error || "loading admin analytics…"}</div>;
  const bars = data.profiles.map((profile) => ({ name: profile.label, samples: profile.enrollment_count }));
  const ablationBars = data.experiment ? Object.entries(data.experiment.ablations).map(([name, metrics]) => ({ name: name.replaceAll("_", " "), accuracy: Math.round(metrics.accuracy * 100), auc: Math.round(metrics.verification_auc * 100) })) : [];
  const personalScores = data.personal_neural ? [
    ...data.personal_neural.genuine_scores.map((score, index) => ({ name: `genuine ${index + 1}`, score: Math.round(score * 100), kind: "genuine" })),
    ...data.personal_neural.folds.flatMap((fold) => fold.impostors.map((row) => ({ name: row.label, score: Math.round(row.score * 100), kind: "impostor" }))),
  ] : [];
  const effectiveComparison = comparison.length ? comparison : data.profile_cards.slice(0, 2).map((card) => card.id);
  const selectedCards = data.profile_cards.filter((card) => effectiveComparison.includes(card.id));
  const ratingNames = ["Typing speed", "Rhythm", "Precision", "Cursor control", "Agility", "Steadiness"];
  const radarData = ratingNames.map((attribute) => ({ attribute, ...Object.fromEntries(selectedCards.map((card) => [card.label, card.ratings[attribute]])) }));
  const colors = ["var(--cyan)", "var(--amber)", "var(--danger)", "#9f8cff"];
  const historyLength = Math.max(0, ...selectedCards.map((card) => card.history.length));
  const wpmTrend = Array.from({ length: historyLength }, (_, index) => ({ session: index + 1, ...Object.fromEntries(selectedCards.map((card) => [card.label, card.history[index]?.wpm ?? null])) }));
  const clickTrend = Array.from({ length: historyLength }, (_, index) => ({ session: index + 1, ...Object.fromEntries(selectedCards.map((card) => [card.label, card.history[index]?.click_error_px ?? null])) }));
  function toggleComparison(id: string) {
    const current = effectiveComparison;
    if (current.includes(id)) setComparison(current.filter((value) => value !== id));
    else if (current.length < 4) setComparison([...current, id]);
  }
  return (
    <div className="flex-1 px-6 py-8 overflow-y-auto"><div className="max-w-6xl mx-auto fade-up">
      <button onClick={onBack} className="text-xs text-muted font-mono-tight mb-6 hover:text-text">← home</button>
      <div className="flex flex-wrap justify-between gap-4 items-end mb-8"><div><div className="font-mono-tight text-xs uppercase tracking-[0.3em] text-danger mb-2">admin</div><h1 className="text-3xl font-semibold">Behavior intelligence</h1></div><div className="text-xs text-muted max-w-md">{data.model.strategy}</div></div>
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 mb-8">{Object.entries(data.summary).map(([label, value]) => <div key={label} className="bg-surface border border-border rounded-xl p-4"><div className="text-2xl font-mono-tight">{value}</div><div className="text-xs text-muted mt-1">{label.replaceAll("_", " ")}</div></div>)}</div>
      <section className="bg-surface border border-border rounded-xl overflow-hidden mb-8">
        <div className="p-5 border-b border-border flex flex-wrap items-center justify-between gap-4">
          <div><div className="font-mono-tight text-xs uppercase tracking-widest text-amber">identification review queue</div><h2 className="text-xl font-semibold mt-2">{data.review_counts.available} captured sample{data.review_counts.available === 1 ? "" : "s"} available</h2><p className="text-xs text-muted mt-1">Assign the real person, approve the sample, then retrain when the queue is ready.</p></div>
          <button disabled={reviewBusy === "retrain" || data.review_counts.ready_for_retrain === 0} onClick={() => void retrain()} className="bg-amber text-bg px-4 py-3 rounded-lg font-mono-tight text-xs uppercase disabled:opacity-40">{reviewBusy === "retrain" ? "retraining…" : `retrain model · ${data.review_counts.ready_for_retrain} new approved`}</button>
        </div>
        {trainingMessage && <div className="mx-5 mt-4 bg-cyan/10 text-cyan rounded-lg px-4 py-3 text-sm">{trainingMessage}</div>}
        {error && <div className="mx-5 mt-4 bg-danger/10 text-danger rounded-lg px-4 py-3 text-sm">{error}</div>}
        {data.review_queue.length === 0 ? <div className="p-8 text-sm text-muted text-center">No test samples are waiting for review.</div> : <div className="divide-y divide-border">{data.review_queue.map((sample) => {
          const defaultProfile = sample.true_profile_id || sample.predicted_profile_id || "";
          const best = sample.result.best;
          const runComparison = reviewComparisons[sample.id] || sample.comparison;
          return <div key={sample.id} className="p-5">
            <div className="grid lg:grid-cols-[1fr_220px_auto] gap-4 items-center">
              <div><div className="flex flex-wrap items-center gap-2"><span className="font-mono-tight text-[10px] uppercase px-2 py-1 rounded bg-cyan/10 text-cyan">{sample.mode === "1to1" ? "1:1" : "1:N"}</span><span className="text-sm">Predicted <strong>{sample.predicted_label || "no profile"}</strong></span><span className="text-xs text-muted">{best.similarity}% model similarity · {best.certainty}% certainty</span></div><div className="text-xs text-muted mt-2">{sample.true_label ? `User identified as ${sample.true_label}` : "Identity feedback still missing"} · {formatDateTime(sample.created_at)}</div></div>
              <select value={assignments[sample.id] ?? defaultProfile} onChange={(event) => void selectReviewProfile(sample.id, event.target.value)} className="bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm"><option value="">compare with identity…</option>{data.profiles.filter((profile) => !profile.blacklisted).map((profile) => <option key={profile.id} value={profile.id}>{profile.label}</option>)}</select>
              <div className="flex gap-2"><button disabled={reviewBusy === sample.id || !(assignments[sample.id] || defaultProfile)} onClick={() => void review(sample.id, "approve", defaultProfile)} className="bg-cyan/15 text-cyan px-3 py-2 rounded text-xs font-mono-tight disabled:opacity-40">approve</button><button disabled={reviewBusy === sample.id} onClick={() => void review(sample.id, "reject")} className="bg-danger/15 text-danger px-3 py-2 rounded text-xs font-mono-tight disabled:opacity-40">reject</button></div>
            </div>
            {comparisonBusy === sample.id ? <div className="mt-5 text-xs text-muted">recalculating profile coincidence…</div> : runComparison && <div className="mt-5 bg-surface-2 border border-border rounded-xl p-4">
              <div className="flex flex-wrap justify-between items-end gap-3"><div><div className="text-xs text-muted">Identification run compared with original {runComparison.profile_label} profile</div><div className="font-mono-tight text-3xl text-cyan mt-1">{runComparison.overall_coincidence}% <span className="text-xs text-muted">feature coincidence</span></div></div><div className="text-xs text-muted">based on {runComparison.enrollment_sessions} trained session{runComparison.enrollment_sessions === 1 ? "" : "s"}</div></div>
              <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3 mt-5">{runComparison.categories.map((category) => <div key={category.category}><div className="flex justify-between gap-2 text-[10px] mb-1"><span>{category.category}</span><span className="font-mono-tight text-muted">{category.similarity}%</span></div><div className="h-1.5 bg-bg rounded-full overflow-hidden"><div className="h-full bg-cyan rounded-full" style={{width:`${category.similarity}%`}}/></div></div>)}</div>
              <div className="overflow-auto mt-5"><table className="w-full min-w-[700px] text-xs"><thead><tr className="text-left text-muted border-b border-border"><th className="py-2">measurement</th><th>identification run</th><th>trained profile average</th><th>difference</th></tr></thead><tbody>{runComparison.metrics.map((metric) => <tr key={metric.label} className="border-b border-border/50"><td className="py-2">{metric.label}</td><td className="font-mono-tight">{metric.probe == null ? "n/a" : `${metric.probe} ${metric.unit}`}</td><td className="font-mono-tight">{metric.profile == null ? "n/a" : `${metric.profile} ${metric.unit}`}</td><td className={`font-mono-tight ${metric.delta_percent != null && Math.abs(metric.delta_percent) <= 15 ? "text-cyan" : "text-muted"}`}>{metric.delta_percent == null ? "n/a" : `${metric.delta_percent > 0 ? "+" : ""}${metric.delta_percent}%`}</td></tr>)}</tbody></table></div>
            </div>}
          </div>;
        })}</div>}
      </section>
      <div className="grid lg:grid-cols-2 gap-5 mb-8">
        <section className="bg-surface border border-border rounded-xl p-5"><h2 className="font-mono-tight text-xs uppercase tracking-widest mb-4">enrollment depth</h2><ResponsiveContainer width="100%" height={260}><BarChart data={bars}><CartesianGrid stroke="var(--border)" vertical={false}/><XAxis dataKey="name" tick={{fill:"var(--muted)",fontSize:10}}/><YAxis tick={{fill:"var(--muted)",fontSize:10}} allowDecimals={false}/><Tooltip/><Bar dataKey="samples" fill="var(--amber)" radius={[4,4,0,0]}/></BarChart></ResponsiveContainer></section>
        <section className="bg-surface border border-border rounded-xl p-5"><h2 className="font-mono-tight text-xs uppercase tracking-widest mb-4">profile similarity matrix</h2><div className="overflow-auto"><table className="text-[10px] font-mono-tight border-separate border-spacing-1"><thead><tr><th></th>{data.similarity_labels.map((label) => <th key={label} className="px-1 text-muted max-w-14 truncate">{label}</th>)}</tr></thead><tbody>{data.similarity_matrix.map((row, i) => <tr key={data.similarity_labels[i]}><th className="pr-2 text-right text-muted">{data.similarity_labels[i]}</th>{row.map((value, j) => <td key={j} title={`${value ?? "n/a"}%`} className="w-9 h-9 text-center rounded" style={{background:value == null ? "var(--surface-2)" : `rgba(94,224,196,${Math.max(0.08,value/100)})`,color:value && value > 65 ? "var(--bg)" : "var(--text)"}}>{value == null ? "–" : Math.round(value)}</td>)}</tr>)}</tbody></table></div></section>
      </div>
      <section className="bg-surface border border-border rounded-xl p-5 mb-8">
        <div className="flex flex-wrap justify-between items-start gap-4 mb-5"><div><div className="font-mono-tight text-xs uppercase tracking-widest text-cyan">versus mode</div><h2 className="text-2xl font-semibold mt-2">Profile character comparison</h2><p className="text-sm text-muted mt-1">Select up to four profiles. Ratings are percentiles among the current roster; raw measurements are shown below.</p></div><div className="flex flex-wrap gap-2 max-w-xl">{data.profile_cards.map((card) => <button key={card.id} onClick={() => toggleComparison(card.id)} disabled={!effectiveComparison.includes(card.id) && effectiveComparison.length >= 4} className={`px-3 py-2 rounded-lg border text-xs transition disabled:opacity-30 ${effectiveComparison.includes(card.id) ? "border-cyan bg-cyan/10 text-cyan" : "border-border text-muted hover:text-text"}`}>{card.label}</button>)}</div></div>
        {selectedCards.length ? <>
          <div className="grid lg:grid-cols-[1.1fr_1fr] gap-6 items-center">
            <ResponsiveContainer width="100%" height={390}><RadarChart data={radarData} outerRadius="72%"><PolarGrid stroke="var(--border)"/><PolarAngleAxis dataKey="attribute" tick={{fill:"var(--muted)",fontSize:11}}/><PolarRadiusAxis angle={30} domain={[0,100]} tick={{fill:"var(--muted)",fontSize:9}}/>{selectedCards.map((card, index) => <Radar key={card.id} name={card.label} dataKey={card.label} stroke={colors[index]} fill={colors[index]} fillOpacity={0.12} strokeWidth={2}/>) }<Legend/></RadarChart></ResponsiveContainer>
            <div className="grid sm:grid-cols-2 gap-3">{selectedCards.map((card, index) => <div key={card.id} className="bg-surface-2 border border-border rounded-xl p-4 relative overflow-hidden"><div className="absolute -right-1 -top-5 font-mono-tight text-8xl opacity-[0.06]" style={{color:colors[index]}}>{card.rank}</div><div className="flex justify-between items-start"><div><div className="font-semibold text-lg">{card.label}</div><div className="text-xs text-muted">{card.enrollment_count} session{card.enrollment_count === 1 ? "" : "s"}</div></div><div className="w-11 h-11 rounded-lg flex items-center justify-center font-mono-tight text-xl text-bg" style={{background:colors[index]}}>{card.rank}</div></div><div className="font-mono-tight text-3xl mt-5">{card.overall}<span className="text-xs text-muted"> / 100</span></div><div className="text-xs text-muted">overall roster rating</div>{card.missing_ratings.length > 0 && <div className="text-[10px] text-amber mt-3">Neutral rating used for missing: {card.missing_ratings.join(", ")}</div>}</div>)}</div>
          </div>
          <div className="overflow-auto mt-6"><table className="w-full min-w-[900px] text-sm"><thead><tr className="text-left text-xs text-muted border-b border-border"><th className="py-3 pr-4">real measurement</th>{selectedCards.map((card) => <th key={card.id} className="py-3 px-3">{card.label}</th>)}</tr></thead><tbody>{[
            ["Typing speed", "wpm", " WPM"], ["Key dwell", "dwell_ms", " ms"], ["Key flight", "flight_ms", " ms"], ["Inter-key interval", "iki_ms", " ms"], ["Backspace rate", "backspace_rate", "%", 100], ["Mouse speed", "mouse_speed_pxs", " px/s"], ["Click error", "click_error_px", " px"], ["Target travel", "target_time_ms", " ms"], ["Tracking error", "tracking_error_px", " px"], ["Tremor", "tremor_px", " px"], ["Drag duration", "drag_duration_ms", " ms"], ["Drag success", "drag_success_rate", "%", 100],
          ].map(([label, key, suffix, multiplier]) => <tr key={String(key)} className="border-b border-border/60"><td className="py-3 pr-4 text-muted">{label}</td>{selectedCards.map((card) => { const value = card.metrics[String(key)]; return <td key={card.id} className="py-3 px-3 font-mono-tight">{value == null ? <span className="text-muted">not available</span> : `${(Number(value) * Number(multiplier || 1)).toFixed(1)}${suffix}`}</td>; })}</tr>)}</tbody></table></div>
          <div className="grid lg:grid-cols-2 gap-5 mt-7"><div><h3 className="font-mono-tight text-xs uppercase tracking-widest text-muted mb-3">WPM across enrollments</h3><ResponsiveContainer width="100%" height={220}><LineChart data={wpmTrend}><CartesianGrid stroke="var(--border)" vertical={false}/><XAxis dataKey="session" tick={{fill:"var(--muted)",fontSize:10}}/><YAxis tick={{fill:"var(--muted)",fontSize:10}}/><Tooltip/>{selectedCards.map((card,index) => <Line key={card.id} type="monotone" dataKey={card.label} stroke={colors[index]} strokeWidth={2} connectNulls dot={{r:4}}/>)}</LineChart></ResponsiveContainer></div><div><h3 className="font-mono-tight text-xs uppercase tracking-widest text-muted mb-3">Click error across enrollments</h3><ResponsiveContainer width="100%" height={220}><LineChart data={clickTrend}><CartesianGrid stroke="var(--border)" vertical={false}/><XAxis dataKey="session" tick={{fill:"var(--muted)",fontSize:10}}/><YAxis tick={{fill:"var(--muted)",fontSize:10}} unit="px"/><Tooltip/>{selectedCards.map((card,index) => <Line key={card.id} type="monotone" dataKey={card.label} stroke={colors[index]} strokeWidth={2} connectNulls dot={{r:4}}/>)}</LineChart></ResponsiveContainer></div></div>
        </> : <div className="text-muted text-sm py-10 text-center">Select at least one profile to compare.</div>}
      </section>
      {data.personal_neural && <section className="bg-surface border border-border rounded-xl p-5 mb-8">
        <div className="flex flex-wrap justify-between gap-4 mb-5"><div><div className="font-mono-tight text-xs uppercase tracking-widest text-cyan">personal neural verifier</div><h2 className="text-2xl font-semibold mt-2">{data.personal_neural.target_label} · session-disjoint test</h2><p className="text-sm text-muted mt-1">BiLSTM keyboard + TCN mouse fusion. Held-out parent sessions and impostor identities never enter their fold’s training windows.</p></div><div className="text-right"><div className="font-mono-tight text-3xl text-cyan">{Math.round(data.personal_neural.metrics.balanced_accuracy * 100)}%</div><div className="text-xs text-muted">balanced accuracy</div></div></div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-6"><div className="bg-surface-2 rounded-lg p-4"><div className="font-mono-tight text-xl">{Math.round(data.personal_neural.metrics.genuine_acceptance_rate * 100)}%</div><div className="text-xs text-muted">genuine accepted · {data.personal_neural.metrics.genuine_trials} trials</div></div><div className="bg-surface-2 rounded-lg p-4"><div className="font-mono-tight text-xl">{Math.round(data.personal_neural.metrics.false_acceptance_rate * 100)}%</div><div className="text-xs text-muted">false acceptance · {data.personal_neural.metrics.impostor_trials} trials</div></div><div className="bg-surface-2 rounded-lg p-4"><div className="font-mono-tight text-xl">{data.personal_neural.metrics.roc_auc.toFixed(3)}</div><div className="text-xs text-muted">pooled ROC-AUC</div></div><div className="bg-surface-2 rounded-lg p-4"><div className="font-mono-tight text-xl">{(data.personal_neural.operating_threshold * 100).toFixed(1)}%</div><div className="text-xs text-muted">deployment threshold</div></div></div>
        <div className="grid lg:grid-cols-[1.1fr_1fr] gap-6"><div><h3 className="font-mono-tight text-xs uppercase tracking-widest text-muted mb-3">held-out neural scores</h3><ResponsiveContainer width="100%" height={270}><BarChart data={personalScores}><CartesianGrid stroke="var(--border)" vertical={false}/><XAxis dataKey="name" tick={{fill:"var(--muted)",fontSize:9}} angle={-30} textAnchor="end" height={70}/><YAxis domain={[0,100]} tick={{fill:"var(--muted)",fontSize:10}}/><Tooltip/><Bar dataKey="score" fill="var(--cyan)" radius={[4,4,0,0]}/></BarChart></ResponsiveContainer></div><div className="overflow-auto"><h3 className="font-mono-tight text-xs uppercase tracking-widest text-muted mb-3">leave-one-session-out folds</h3><table className="w-full text-xs"><thead><tr className="text-left text-muted border-b border-border"><th className="py-2">fold</th><th>genuine score</th><th>threshold</th><th>result</th><th>held impostors</th></tr></thead><tbody>{data.personal_neural.folds.map((fold) => <tr key={fold.fold} className="border-b border-border/50"><td className="py-3">#{fold.fold}</td><td className="font-mono-tight">{(fold.genuine_score * 100).toFixed(1)}%</td><td className="font-mono-tight">{(fold.threshold * 100).toFixed(1)}%</td><td className={fold.genuine_accepted ? "text-cyan" : "text-danger"}>{fold.genuine_accepted ? "accepted" : "rejected"}</td><td className="text-muted">{fold.impostors.map((row) => row.label).join(", ")}</td></tr>)}</tbody></table></div></div>
        <p className="text-xs text-danger/90 mt-5">{data.personal_neural.warning} The personal score is advisory and does not override the primary authentication decision.</p>
      </section>}
      {data.experiment && <section className="bg-surface border border-border rounded-xl p-5 mb-8">
        <div className="flex flex-wrap justify-between gap-4 mb-5"><div><h2 className="font-mono-tight text-xs uppercase tracking-widest">training benchmark</h2><p className="text-xl mt-2">{data.experiment.best_model.replaceAll("_", " ")} · {Math.round(data.experiment.best_metrics.accuracy * 100)}% held-window accuracy</p></div><div className="text-xs text-muted">SVM C={data.experiment.tuned_svm.C}, gamma={data.experiment.tuned_svm.gamma}<br/>Neural validation {Math.round(data.experiment.neural.best_validation_accuracy * 100)}%</div></div>
        <div className="grid lg:grid-cols-[1fr_1.2fr] gap-5 items-center"><div className="grid grid-cols-2 gap-3"><div className="bg-surface-2 rounded-lg p-4"><div className="font-mono-tight text-xl">{data.experiment.best_metrics.verification_auc.toFixed(4)}</div><div className="text-xs text-muted">verification AUC</div></div><div className="bg-surface-2 rounded-lg p-4"><div className="font-mono-tight text-xl">{(data.experiment.best_metrics.eer * 100).toFixed(2)}%</div><div className="text-xs text-muted">equal-error rate</div></div><p className="col-span-2 text-xs text-danger/90">{data.experiment.warning}</p></div><ResponsiveContainer width="100%" height={220}><BarChart data={ablationBars}><CartesianGrid stroke="var(--border)" vertical={false}/><XAxis dataKey="name" tick={{fill:"var(--muted)",fontSize:10}}/><YAxis domain={[0,100]} tick={{fill:"var(--muted)",fontSize:10}}/><Tooltip/><Bar dataKey="accuracy" fill="var(--cyan)" radius={[4,4,0,0]}/><Bar dataKey="auc" fill="var(--amber)" radius={[4,4,0,0]}/></BarChart></ResponsiveContainer></div>
      </section>}
      <AdminJobsAndAlerts />
      <JobsAndAlerts />
      <section className="bg-surface border border-border rounded-xl overflow-hidden"><div className="p-5 border-b border-border"><h2 className="font-mono-tight text-xs uppercase tracking-widest">profiles</h2></div><div className="divide-y divide-border">{data.profiles.map((profile) => <div key={profile.id} className="p-4"><div className="flex flex-wrap items-center gap-4"><div className="flex-1 min-w-40"><div className={profile.blacklisted ? "line-through text-muted" : ""}>{profile.label}</div><div className="text-xs text-muted mt-1">{profile.enrollment_count} enrollment{profile.enrollment_count === 1 ? "" : "s"} · {profile.last_enrollment ? formatDate(profile.last_enrollment) : "never"} · {profile.user_id ? "linked to an account" : "unclaimed"}</div></div>
        <button
          disabled={Boolean(profile.user_id) || claimTokenBusy === profile.id}
          onClick={() => void generateClaimToken(profile.id)}
          title={profile.user_id ? "Already linked to an account — claim tokens are only for unclaimed profiles" : "Generate a one-time link for someone to claim this profile"}
          className="px-3 py-2 rounded text-xs font-mono-tight bg-cyan/15 text-cyan disabled:opacity-30 disabled:cursor-not-allowed"
        >
          {claimTokenBusy === profile.id ? "generating…" : "claim token"}
        </button>
        <button onClick={() => blacklist(profile.id, !profile.blacklisted)} className={`px-3 py-2 rounded text-xs font-mono-tight ${profile.blacklisted ? "bg-cyan/15 text-cyan" : "bg-amber/15 text-amber"}`}>{profile.blacklisted ? "restore" : "blacklist"}</button><button onClick={() => remove(profile.id, profile.label)} className="px-3 py-2 rounded text-xs font-mono-tight bg-danger/15 text-danger">delete</button></div>
        {claimTokens[profile.id] && <div className="mt-3 bg-surface-2 border border-border rounded-lg p-3 flex flex-wrap items-center gap-3"><code className="text-xs font-mono-tight break-all flex-1">{claimTokens[profile.id]}</code><button onClick={() => navigator.clipboard.writeText(claimTokens[profile.id])} className="px-3 py-1.5 rounded text-xs font-mono-tight bg-cyan text-bg shrink-0">copy</button></div>}
        {claimTokenError[profile.id] && <div className="mt-3 text-xs text-danger">{claimTokenError[profile.id]}</div>}
      </div>)}</div></section>
      <div className="mt-6 text-xs text-muted">Model {data.model.version.slice(0,19)} · {data.model.svm_trained ? "SVM active" : "centroid mode"} · neural {data.model.neural_ready ? "ready" : "waiting for repeated sessions"}</div>
    </div></div>
  );
}
