"use client";

export default function Landing({ onEnroll, onIdentify, onAdmin }: { onEnroll: () => void; onIdentify: () => void; onAdmin: () => void }) {
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
        <div className="grid sm:grid-cols-2 gap-3 text-left">
          <button onClick={onIdentify} className="bg-cyan text-bg rounded-xl p-5 hover:brightness-110 transition active:scale-[0.99]">
            <span className="block font-mono-tight text-xs uppercase tracking-widest mb-2">identify</span>
            <span className="block text-sm">Test against one profile or ask BehaveGuard to choose from several.</span>
          </button>
          <button onClick={onEnroll} className="bg-amber text-bg rounded-xl p-5 hover:brightness-110 transition active:scale-[0.99]">
            <span className="block font-mono-tight text-xs uppercase tracking-widest mb-2">enroll</span>
            <span className="block text-sm">Create a profile or add a fresh behavioral sample to an existing one.</span>
          </button>
        </div>
        <button onClick={onAdmin} className="mt-4 font-mono-tight text-xs uppercase tracking-widest text-muted hover:text-text transition">
          open admin dashboard →
        </button>
        <div className="mt-5 text-xs text-muted font-mono-tight">
          keyboard rhythm · cursor dynamics · calibrated matching
        </div>
      </div>
    </div>
  );
}
