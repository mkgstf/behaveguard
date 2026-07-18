"use client";

import { useAuth } from "@/lib/auth";

export default function Landing({
  onEnroll,
  onVerifySelf,
  onIdentify,
  onAdmin,
  onLogin,
  onRegister,
  onClaim,
  hasOwnProfile,
}: {
  onEnroll: () => void;
  onVerifySelf: () => void;
  onIdentify: () => void;
  onAdmin: () => void;
  onLogin: () => void;
  onRegister: () => void;
  onClaim: () => void;
  hasOwnProfile: boolean;
}) {
  const { user, loading, signOut } = useAuth();
  const isAdmin = user?.role === "org_admin" || user?.role === "platform_admin";

  return (
    <div className="flex-1 flex items-center justify-center px-6">
      <div className="max-w-xl text-center fade-up">
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
        <p className="text-muted leading-relaxed mb-10">
          A 5-minute test of how you type and how you move a cursor. Used to study
          behavioral biometrics — the rhythm that&apos;s unique to you, not what you type.
        </p>

        {loading ? (
          <p className="text-muted text-sm">loading…</p>
        ) : !user ? (
          <div className="grid sm:grid-cols-2 gap-3 text-left">
            <button onClick={onLogin} className="bg-cyan text-bg rounded-xl p-5 hover:brightness-110 transition active:scale-[0.99]">
              <span className="block font-mono-tight text-xs uppercase tracking-widest mb-2">log in</span>
              <span className="block text-sm">Already have an account? Sign back in to verify or keep enrolling.</span>
            </button>
            <button onClick={onRegister} className="bg-amber text-bg rounded-xl p-5 hover:brightness-110 transition active:scale-[0.99]">
              <span className="block font-mono-tight text-xs uppercase tracking-widest mb-2">register</span>
              <span className="block text-sm">Create an account to start your own behavioral profile.</span>
            </button>
          </div>
        ) : (
          <>
            <div className="grid sm:grid-cols-2 gap-3 text-left">
              <button onClick={hasOwnProfile ? onVerifySelf : onEnroll} className="bg-cyan text-bg rounded-xl p-5 hover:brightness-110 transition active:scale-[0.99]">
                <span className="block font-mono-tight text-xs uppercase tracking-widest mb-2">
                  {hasOwnProfile ? "verify myself" : "enroll"}
                </span>
                <span className="block text-sm">
                  {hasOwnProfile
                    ? "Run a 1:1 check against your own enrolled profile."
                    : "Create your profile with an initial behavioral sample."}
                </span>
              </button>
              <button onClick={onEnroll} className="bg-amber text-bg rounded-xl p-5 hover:brightness-110 transition active:scale-[0.99]">
                <span className="block font-mono-tight text-xs uppercase tracking-widest mb-2">add sample</span>
                <span className="block text-sm">
                  {hasOwnProfile ? "Strengthen your profile with another enrollment session." : "Same as above — create your profile."}
                </span>
              </button>
            </div>
            {isAdmin && (
              <button onClick={onIdentify} className="w-full mt-3 border border-border rounded-xl p-4 text-left hover:border-muted transition">
                <span className="block font-mono-tight text-xs uppercase tracking-widest mb-1 text-muted">identify (admin)</span>
                <span className="block text-sm">Test a session against several candidate profiles at once.</span>
              </button>
            )}
            <div className="flex items-center justify-center gap-4 mt-6 text-xs font-mono-tight text-muted">
              <span>{user.email}</span>
              <button onClick={onClaim} className="hover:text-text transition">claim a profile</button>
              {isAdmin && <button onClick={onAdmin} className="hover:text-text transition">admin dashboard →</button>}
              <button onClick={() => void signOut()} className="hover:text-danger transition">log out</button>
            </div>
          </>
        )}

        <div className="mt-5 text-xs text-muted font-mono-tight">
          keyboard rhythm · cursor dynamics · calibrated matching
        </div>
      </div>
    </div>
  );
}
