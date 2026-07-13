"use client";

import { useRef, useState } from "react";
import { AuthMode, Screen, SessionData, KeyEvent, DotTrial, DragTrial, TrackTrial, Profile } from "@/lib/types";
import { usePassiveMouseCollector } from "@/lib/usePassiveMouse";
import { api, EnrollmentResult, VerificationResult } from "@/lib/api";
import { computeKeyboardExtras } from "@/lib/kinematics";
import StageRail from "@/components/StageRail";
import Landing from "@/components/Landing";
import Consent from "@/components/Consent";
import KeyboardTest from "@/components/KeyboardTest";
import MouseDotTask from "@/components/MouseDotTask";
import MouseTrackTask from "@/components/MouseTrackTask";
import MouseDragTask from "@/components/MouseDragTask";
import ProfileSetup from "@/components/ProfileSetup";
import BehaviorResult from "@/components/BehaviorResult";
import AdminDashboard from "@/components/AdminDashboard";

export default function Home() {
  const [screen, setScreen] = useState<Screen>("landing");
  const [mode, setMode] = useState<AuthMode>("identify");
  const [selected, setSelected] = useState<Profile[]>([]);
  const [result, setResult] = useState<EnrollmentResult | VerificationResult | null>(null);
  const [submitError, setSubmitError] = useState("");
  const passivePointsRef = usePassiveMouseCollector();
  const sessionStart = useRef(0);
  const keyboardData = useRef<{ events: KeyEvent[]; pangramLen: number; freeLen: number }>({ events: [], pangramLen: 0, freeLen: 0 });
  const dotTrials = useRef<DotTrial[]>([]);
  const trackTrials = useRef<TrackTrial[]>([]);
  const dragTrials = useRef<DragTrial[]>([]);

  function reset() { setScreen("landing"); setResult(null); setSelected([]); setSubmitError(""); passivePointsRef.current = []; }
  function begin(kind: "enroll" | "identify") { setMode(kind); setScreen("setup"); }
  function ready(profiles: Profile[]) { setSelected(profiles); setMode(mode === "enroll" ? "enroll" : profiles.length === 1 ? "verify" : "identify"); sessionStart.current = performance.now(); setScreen("consent"); }

  function buildSession(): SessionData {
    const events = keyboardData.current.events;
    return {
      subject_id: selected.map((profile) => profile.label).join(","), collected_at: new Date().toISOString(), duration_ms: performance.now() - sessionStart.current,
      keyboard: { events, pangram_text_length: keyboardData.current.pangramLen, free_text_length: keyboardData.current.freeLen, extras: computeKeyboardExtras(events) },
      mouse: { passive_points: passivePointsRef.current, dot_trials: dotTrials.current, drag_trials: dragTrials.current, track_trials: trackTrials.current },
      context: { viewport_width: window.innerWidth, viewport_height: window.innerHeight, device_pixel_ratio: window.devicePixelRatio, pointer_type: window.matchMedia("(pointer: coarse)").matches ? "coarse" : "fine", app_version: "2.0.0" },
    };
  }

  async function submit(data: SessionData) {
    try {
      const response = mode === "enroll" ? await api.enroll(selected[0].id, data) : mode === "verify" ? await api.verify(selected[0].id, data) : await api.identify(selected.map((profile) => profile.id), data);
      setResult(response); setScreen("result");
    } catch (error) { setSubmitError(error instanceof Error ? error.message : "Submission failed"); }
  }

  if (screen === "admin") return <AdminDashboard onBack={reset} />;
  if (screen === "setup") return <ProfileSetup kind={mode === "enroll" ? "enroll" : "identify"} onReady={ready} onBack={reset} />;
  if (screen === "result" && result) return <BehaviorResult result={result} onHome={reset} />;
  const showRail = !["landing", "done", "setup", "admin", "result"].includes(screen);
  const quickVerification = mode !== "enroll";
  return <div className="flex flex-col min-h-screen">
    {showRail && <StageRail current={screen} />}
    {screen === "landing" && <Landing onEnroll={() => begin("enroll")} onIdentify={() => begin("identify")} onAdmin={() => setScreen("admin")} />}
    {screen === "consent" && <Consent onAgree={() => setScreen("keyboard")} />}
    {screen === "keyboard" && <KeyboardTest segmentSeconds={quickVerification ? 30 : 90} onComplete={(events, pangramLen, freeLen) => { keyboardData.current = { events, pangramLen, freeLen }; setScreen("mouse-dot"); }} />}
    {screen === "mouse-dot" && <MouseDotTask targetCount={quickVerification ? 10 : 25} onComplete={(trials) => { dotTrials.current = trials; setScreen("mouse-track"); }} />}
    {screen === "mouse-track" && <MouseTrackTask trialDurationMs={quickVerification ? 8000 : 20000} onComplete={(trials) => { trackTrials.current = trials; setScreen("mouse-drag"); }} />}
    {screen === "mouse-drag" && <MouseDragTask dragCount={quickVerification ? 5 : 10} onComplete={(trials) => { dragTrials.current = trials; void submit(buildSession()); }} />}
    {submitError && <div className="fixed bottom-5 left-1/2 -translate-x-1/2 bg-danger text-white rounded-lg px-5 py-3 text-sm shadow-xl">{submitError} <button onClick={() => void submit(buildSession())} className="underline ml-3">retry</button></div>}
  </div>;
}
