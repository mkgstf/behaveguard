"use client";

import { useAuth } from "@/lib/auth";
import { MyStats } from "@/lib/api";
import { formatRelative } from "@/lib/format";

type ProfileCheckStatus = "idle" | "loading" | "found" | "none" | "error";

// A commonly-cited average adult typing speed, used only to give the WPM
// number a friendly point of comparison for people who don't otherwise know
// what a "good" WPM looks like. Clearly labeled as a rough benchmark, not a
// precise population statistic.
const AVERAGE_TYPIST_WPM = 40;

export default function Landing({
  onEnroll,
  onVerifySelf,
  onIdentify,
  onLogin,
  onRegister,
  onClaim,
  hasOwnProfile,
  isTrained,
  profileCheck,
  onRetryProfileCheck,
  stats,
  onOpenStats,
}: {
  onEnroll: () => void;
  onVerifySelf: () => void;
  onIdentify: () => void;
  onLogin: () => void;
  onRegister: () => void;
  onClaim: () => void;
  hasOwnProfile: boolean;
  isTrained: boolean;
  profileCheck: ProfileCheckStatus;
  onRetryProfileCheck: () => void;
  myProfileId: string | null;
  stats: MyStats | null;
  onOpenStats: () => void;
}) {
  const { user, loading } = useAuth();
  const isAdmin = user?.role === "org_admin" || user?.role === "platform_admin";

  return (
    <div className="flex-1 flex items-center justify-center px-6 py-16">
      <div className="max-w-3xl w-full text-center fade-up">
        <div className="font-mono-tight text-sm uppercase tracking-[0.3em] text-muted mb-6">
          behaveguard
        </div>
        <h1 className="font-mono-tight text-4xl sm:text-5xl leading-tight mb-4">
          <span className="text-amber">type</span>
          <span className="text-muted">.</span>{" "}
          <span className="text-cyan">move</span>
          <span className="text-muted">.</span>{" "}
          <span className="text-text">be measured</span>
          <span className="caret text-text">|</span>
        </h1>
        <p className="text-muted text-base leading-relaxed mb-10 max-w-xl mx-auto">
          A 5-minute test of how you type and how you move a cursor. Used to study
          behavioral biometrics — the rhythm that&apos;s unique to you, not what you type.
        </p>

        {loading ? (
          <p className="text-muted text-sm">loading…</p>
        ) : !user ? (
          <div className="grid sm:grid-cols-2 gap-3 text-left max-w-xl mx-auto">
            <button onClick={onLogin} className="cursor-pointer bg-cyan text-bg rounded-xl p-5 hover:brightness-110 transition active:scale-[0.99]">
              <span className="block font-mono-tight text-xs uppercase tracking-widest mb-2">log in</span>
              <span className="block text-sm">Already have an account? Sign back in to verify or keep enrolling.</span>
            </button>
            <button onClick={onRegister} className="cursor-pointer bg-amber text-bg rounded-xl p-5 hover:brightness-110 transition active:scale-[0.99]">
              <span className="block font-mono-tight text-xs uppercase tracking-widest mb-2">register</span>
              <span className="block text-sm">Create an account to start your own behavioral profile.</span>
            </button>
          </div>
        ) : profileCheck === "error" ? (
          <div className="bg-danger/10 border border-danger/30 rounded-xl p-5 text-left max-w-xl mx-auto">
            <div className="font-mono-tight text-xs uppercase tracking-widest text-danger mb-2">couldn&apos;t check your profile</div>
            <p className="text-sm text-muted mb-4">
              Something went wrong while checking whether you already have a profile. We won&apos;t guess — retry the check before enrolling or verifying.
            </p>
            <button onClick={onRetryProfileCheck} className="cursor-pointer bg-text text-bg rounded-lg px-5 py-2.5 font-mono-tight text-xs uppercase tracking-widest">
              retry
            </button>
          </div>
        ) : profileCheck === "loading" || profileCheck === "idle" ? (
          <p className="text-muted text-sm">checking your profile status…</p>
        ) : (
          <>
            {isTrained && stats?.latest && (
              <HighlightsBoard stats={stats} onOpenStats={onOpenStats} />
            )}

            {/* First-enrollment vs. add-sample distinction: only offer
                "enroll" (narrow, single button) until a profile actually has
                trained data; "verify" + "add sample" only appear once
                there's real data to work with. */}
            {isTrained ? (
              <div className="grid sm:grid-cols-2 gap-3 text-left max-w-xl mx-auto">
                <button onClick={onVerifySelf} className="cursor-pointer bg-cyan text-bg rounded-xl p-5 hover:brightness-110 transition active:scale-[0.99]">
                  <span className="block font-mono-tight text-xs uppercase tracking-widest mb-2">verify myself</span>
                  <span className="block text-sm">Run a 1:1 check against your own enrolled profile.</span>
                </button>
                <button onClick={onEnroll} className="cursor-pointer bg-amber text-bg rounded-xl p-5 hover:brightness-110 transition active:scale-[0.99]">
                  <span className="block font-mono-tight text-xs uppercase tracking-widest mb-2">add sample</span>
                  <span className="block text-sm">Strengthen your profile with another enrollment session.</span>
                </button>
              </div>
            ) : (
              <div className="max-w-xs mx-auto">
                <button onClick={onEnroll} className="cursor-pointer w-full bg-cyan text-bg rounded-xl p-5 hover:brightness-110 transition active:scale-[0.99] text-left">
                  <span className="block font-mono-tight text-xs uppercase tracking-widest mb-2">
                    {hasOwnProfile ? "continue enrolling" : "enroll"}
                  </span>
                  <span className="block text-sm">
                    {hasOwnProfile
                      ? "Finish your first behavioral sample to activate your profile."
                      : "Create your profile with an initial behavioral sample."}
                  </span>
                </button>
                <button onClick={onClaim} className="cursor-pointer w-full mt-3 text-xs text-muted font-mono-tight hover:text-text transition py-2">
                  or claim an existing profile →
                </button>
              </div>
            )}

            {isAdmin && (
              <button onClick={onIdentify} className="cursor-pointer w-full max-w-xl mx-auto mt-3 border border-border rounded-xl p-4 text-left hover:border-muted transition block">
                <span className="block font-mono-tight text-xs uppercase tracking-widest mb-1 text-muted">compare against candidates</span>
                <span className="block text-sm">Test a session against several candidate profiles at once — for verified team members.</span>
              </button>
            )}
          </>
        )}

        <div className="mt-10 text-xs text-muted font-mono-tight">
          keyboard rhythm · cursor dynamics · calibrated matching
        </div>
      </div>
    </div>
  );
}

function HighlightsBoard({ stats, onOpenStats }: { stats: MyStats; onOpenStats: () => void }) {
  const latest = stats.latest;
  if (!latest) return null;
  const wpm = latest.wpm;
  const vsAverage = wpm != null ? Math.round(((wpm - AVERAGE_TYPIST_WPM) / AVERAGE_TYPIST_WPM) * 100) : null;
  const card = stats.card;

  return (
    <div className="mb-8 text-left">
      <div className="flex items-center justify-between mb-4 max-w-xl mx-auto">
        <span className="font-mono-tight text-xs uppercase tracking-widest text-muted">your highlights</span>
        <span className="text-xs text-muted font-mono-tight">{stats.history.length} sample{stats.history.length === 1 ? "" : "s"} · updated {formatRelative(latest.collected_at)}</span>
      </div>
      {/* Two vertical columns of 2-3 cards each, rather than one flat
          horizontal strip — easier to scan and gives each number room to
          breathe. */}
      <div className="grid sm:grid-cols-2 gap-4 max-w-xl mx-auto">
        <div className="space-y-3">
          <HighlightCard
            label="typing speed"
            value={wpm == null ? "—" : `${Math.round(wpm)} wpm`}
            sub={vsAverage == null ? "no comparison yet" : vsAverage >= 0 ? `${vsAverage}% faster than average` : `${Math.abs(vsAverage)}% slower than average`}
            accent="amber"
          />
          <HighlightCard
            label="rhythm consistency"
            value={latest.rhythm_cv == null ? "—" : `${Math.round((1 - Math.min(latest.rhythm_cv, 1)) * 100)}%`}
            sub="how steady your pace stays"
            accent="cyan"
          />
        </div>
        <div className="space-y-3">
          <HighlightCard
            label="profile rank"
            value={card ? card.rank : "—"}
            sub={card ? `top ${Math.max(1, 100 - Math.round(card.overall))}% of ${card.population_size} enrolled` : "keep enrolling to unlock"}
            accent="amber"
          />
          <HighlightCard
            label="click precision"
            value={latest.click_error_px == null ? "—" : `${Math.round(latest.click_error_px)}px`}
            sub="average distance from target"
            accent="cyan"
          />
        </div>
      </div>
      <div className="max-w-xl mx-auto mt-4 text-center">
        <button onClick={onOpenStats} className="cursor-pointer font-mono-tight text-xs uppercase tracking-widest text-cyan hover:brightness-110 transition border border-cyan/30 rounded-full px-5 py-2.5">
          view full stats →
        </button>
      </div>
    </div>
  );
}

function HighlightCard({ label, value, sub, accent }: { label: string; value: string; sub: string; accent: "amber" | "cyan" }) {
  return (
    <div className="bg-surface border border-border rounded-xl p-4">
      <div className="text-[10px] uppercase tracking-wider text-muted mb-1.5">{label}</div>
      <div className={`font-mono-tight text-2xl tabular-nums ${accent === "amber" ? "text-amber" : "text-cyan"}`}>{value}</div>
      <div className="text-xs text-muted mt-1">{sub}</div>
    </div>
  );
}
