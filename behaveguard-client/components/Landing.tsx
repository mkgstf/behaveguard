"use client";

import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import { MyStats } from "@/lib/api";

type ProfileCheckStatus = "idle" | "loading" | "found" | "none" | "error";

export default function Landing({
  onEnroll,
  onVerifySelf,
  onIdentify,
  onAdmin,
  onLogin,
  onRegister,
  onClaim,
  hasOwnProfile,
  profileCheck,
  onRetryProfileCheck,
  stats,
  onOpenStats,
}: {
  onEnroll: () => void;
  onVerifySelf: () => void;
  onIdentify: () => void;
  onAdmin: () => void;
  onLogin: () => void;
  onRegister: () => void;
  onClaim: () => void;
  hasOwnProfile: boolean;
  profileCheck: ProfileCheckStatus;
  onRetryProfileCheck: () => void;
  myProfileId: string | null;
  stats: MyStats | null;
  onOpenStats: () => void;
}) {
  const { user, loading, signOut } = useAuth();
  const { showToast } = useToast();
  const isAdmin = user?.role === "org_admin" || user?.role === "platform_admin";

  async function handleSignOut() {
    await signOut();
    showToast("Logged out", "success");
  }

  return (
    <div className="flex-1 flex items-center justify-center px-6 py-12">
      <div className="max-w-xl w-full text-center fade-up">
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
        <p className="text-muted text-base leading-relaxed mb-10">
          A 5-minute test of how you type and how you move a cursor. Used to study
          behavioral biometrics — the rhythm that&apos;s unique to you, not what you type.
        </p>

        {loading ? (
          <p className="text-muted text-sm">loading…</p>
        ) : !user ? (
          <div className="grid sm:grid-cols-2 gap-3 text-left">
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
          <div className="bg-danger/10 border border-danger/30 rounded-xl p-5 text-left">
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
            {hasOwnProfile && stats?.latest && (
              <HighlightsStrip stats={stats} onOpenStats={onOpenStats} />
            )}
            {/* First-enrollment vs. add-sample distinction (bug/spec item 5):
                only offer "enroll" until a profile actually exists; "add
                sample" only appears once there's a profile to add to. */}
            <div className={`grid gap-3 text-left ${hasOwnProfile ? "sm:grid-cols-2" : ""}`}>
              <button onClick={hasOwnProfile ? onVerifySelf : onEnroll} className="cursor-pointer bg-cyan text-bg rounded-xl p-5 hover:brightness-110 transition active:scale-[0.99]">
                <span className="block font-mono-tight text-xs uppercase tracking-widest mb-2">
                  {hasOwnProfile ? "verify myself" : "enroll"}
                </span>
                <span className="block text-sm">
                  {hasOwnProfile
                    ? "Run a 1:1 check against your own enrolled profile."
                    : "Create your profile with an initial behavioral sample."}
                </span>
              </button>
              {hasOwnProfile && (
                <button onClick={onEnroll} className="cursor-pointer bg-amber text-bg rounded-xl p-5 hover:brightness-110 transition active:scale-[0.99]">
                  <span className="block font-mono-tight text-xs uppercase tracking-widest mb-2">add sample</span>
                  <span className="block text-sm">Strengthen your profile with another enrollment session.</span>
                </button>
              )}
            </div>
            {isAdmin && (
              <button onClick={onIdentify} className="cursor-pointer w-full mt-3 border border-border rounded-xl p-4 text-left hover:border-muted transition">
                <span className="block font-mono-tight text-xs uppercase tracking-widest mb-1 text-muted">compare against candidates</span>
                <span className="block text-sm">Test a session against several candidate profiles at once — for verified team members.</span>
              </button>
            )}
            <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-3 mt-8 pt-6 border-t border-border text-xs font-mono-tight text-muted">
              <span className="text-text">{user.email}</span>
              <span className="text-border">·</span>
              <button onClick={onClaim} className="cursor-pointer hover:text-text transition py-1">claim a profile</button>
              {isAdmin && <button onClick={onAdmin} className="cursor-pointer hover:text-text transition py-1">admin dashboard →</button>}
              <button onClick={() => void handleSignOut()} className="cursor-pointer hover:text-danger transition py-1">log out</button>
            </div>
          </>
        )}

        <div className="mt-6 text-xs text-muted font-mono-tight">
          keyboard rhythm · cursor dynamics · calibrated matching
        </div>
      </div>
    </div>
  );
}

function HighlightsStrip({ stats, onOpenStats }: { stats: MyStats; onOpenStats: () => void }) {
  const latest = stats.latest;
  if (!latest) return null;
  return (
    <div className="mb-6 bg-surface border border-border rounded-xl p-4 text-left">
      <div className="flex items-center justify-between mb-3">
        <span className="font-mono-tight text-xs uppercase tracking-widest text-muted">your highlights</span>
        <button onClick={onOpenStats} className="cursor-pointer font-mono-tight text-xs uppercase tracking-widest text-cyan hover:brightness-110 transition">
          my stats →
        </button>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <MiniStat label="wpm" value={latest.wpm} />
        <MiniStat label="rhythm cv" value={latest.rhythm_cv} />
        <MiniStat label="samples" value={stats.history.length} />
      </div>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="bg-surface-2 rounded-lg p-3 text-center">
      <div className="font-mono-tight text-lg tabular-nums">{value == null ? "—" : Math.round(value * 10) / 10}</div>
      <div className="text-[10px] text-muted mt-1 uppercase tracking-wider">{label}</div>
    </div>
  );
}
