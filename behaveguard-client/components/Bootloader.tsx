"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

// A few hardcoded facts about typing/behavioral biometrics, shown while the
// backend is cold-starting. Randomized order per mount so it doesn't feel
// scripted on repeat visits.
const FACTS = [
  "No two people type the same sentence with the same rhythm — even copying the exact same words.",
  "The gaps between your keystrokes carry more identity than the keys themselves.",
  "Cursor movement has a signature \"jerk\" profile — how acceleration itself changes over time.",
];

const MAX_WAIT_MS = 30_000;
const POLL_INTERVAL_MS = 1500;
// If the very first ping resolves faster than this, skip the loader
// entirely — graceful entry with no visible delay when already warm.
const GRACE_MS = 350;

type BootState = "checking" | "waking" | "warm" | "error";

// This app's whole premise is measuring real keyboard/mouse behavior — it
// fundamentally can't work on a touchscreen with no physical keyboard.
// Checked once on mount: actual mobile devices (UA) OR a narrow viewport
// combined with a coarse (touch) primary pointer — a real desktop window
// just resized narrow still has a fine pointer and isn't blocked.
function isUnsupportedDevice(): boolean {
  if (typeof window === "undefined") return false;
  const mobileUA = /Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  const coarsePointer = window.matchMedia("(pointer: coarse)").matches;
  const narrow = window.innerWidth < 768;
  return mobileUA || (coarsePointer && narrow);
}

export default function Bootloader({ children }: { children: React.ReactNode }) {
  const [unsupported, setUnsupported] = useState(false);
  const [state, setState] = useState<BootState>("checking");
  const [secondsLeft, setSecondsLeft] = useState(30);
  const [factIdx, setFactIdx] = useState(() => Math.floor(Math.random() * FACTS.length));
  const [attempt, setAttempt] = useState(0);
  const cancelled = useRef(false);

  useEffect(() => {
    Promise.resolve().then(() => setUnsupported(isUnsupportedDevice()));
  }, []);

  useEffect(() => {
    cancelled.current = false;
    const startedAt = Date.now();
    const revealLoaderTimer = setTimeout(() => {
      if (!cancelled.current) setState((current) => (current === "checking" ? "waking" : current));
    }, GRACE_MS);

    async function poll() {
      for (;;) {
        if (cancelled.current) return;
        try {
          await api.ping();
          if (!cancelled.current) setState("warm");
          return;
        } catch {
          if (Date.now() - startedAt > MAX_WAIT_MS) {
            if (!cancelled.current) setState("error");
            return;
          }
          await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
        }
      }
    }
    void poll();

    return () => {
      cancelled.current = true;
      clearTimeout(revealLoaderTimer);
    };
  }, [attempt]);

  useEffect(() => {
    if (state !== "waking") return;
    Promise.resolve().then(() => setSecondsLeft(30));
    const tick = setInterval(() => setSecondsLeft((s) => Math.max(0, s - 1)), 1000);
    const fact = setInterval(() => setFactIdx((i) => (i + 1) % FACTS.length), 5500);
    return () => { clearInterval(tick); clearInterval(fact); };
  }, [state]);

  if (unsupported) {
    return (
      <div className="min-h-dvh flex items-center justify-center px-6">
        <div className="max-w-sm text-center fade-up">
          <div className="font-mono-tight text-xs uppercase tracking-[0.3em] text-amber mb-4">desktop only</div>
          <h2 className="text-xl font-semibold mb-3">BehaveGuard needs a real keyboard and mouse</h2>
          <p className="text-sm text-muted leading-relaxed">
            This is a behavioral biometrics test built around actual typing rhythm and cursor movement — it isn&apos;t meaningful on a touchscreen. Please open this on a PC or laptop instead.
          </p>
        </div>
      </div>
    );
  }

  if (state === "warm" || state === "checking") return <>{children}</>;

  if (state === "error") {
    return (
      <div className="min-h-screen flex items-center justify-center px-6">
        <div className="max-w-sm text-center fade-up">
          <div className="font-mono-tight text-xs uppercase tracking-[0.3em] text-danger mb-4">connection failed</div>
          <h2 className="text-xl font-semibold mb-3">Couldn&apos;t reach the server</h2>
          <p className="text-sm text-muted mb-7 leading-relaxed">
            The backend didn&apos;t respond after 30 seconds. It may be waking up from a cold start, or it may genuinely be down — check your connection and try again.
          </p>
          <button
            onClick={() => setAttempt((n) => n + 1)}
            className="bg-text text-bg rounded-lg px-7 py-3 font-mono-tight text-xs uppercase tracking-widest hover:brightness-110 transition"
          >
            retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-6">
      <div className="max-w-sm text-center fade-up">
        <div className="relative w-16 h-16 mx-auto mb-8 flex items-center justify-center">
          <span className="absolute inset-0 rounded-full border border-cyan/30 pulse-ring" />
          <span className="absolute inset-0 rounded-full border border-amber/20 pulse-ring" style={{ animationDelay: "0.4s" }} />
          <span className="font-mono-tight text-2xl text-cyan caret">|</span>
        </div>
        <div className="font-mono-tight text-xs uppercase tracking-[0.3em] text-muted mb-3">waking the server</div>
        <h2 className="text-lg font-semibold mb-2 tabular-nums">
          ~{secondsLeft}s left
        </h2>
        <p className="text-sm text-muted leading-relaxed min-h-[3.5rem] transition-opacity">
          {FACTS[factIdx]}
        </p>
      </div>
    </div>
  );
}
