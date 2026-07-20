"use client";

import { useEffect, useRef, useState } from "react";
import { AuthMode, Screen, SessionData, KeyEvent, DotTrial, DragTrial, TrackTrial, Profile } from "@/lib/types";
import { usePassiveMouseCollector } from "@/lib/usePassiveMouse";
import { api, EnrollmentResult, VerificationResult, MyStats, SessionBehaviorMetrics } from "@/lib/api";
import { computeKeyboardExtras } from "@/lib/kinematics";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import StageRail from "@/components/StageRail";
import Landing from "@/components/Landing";
import Login from "@/components/Login";
import Register from "@/components/Register";
import ClaimProfile from "@/components/ClaimProfile";
import CreateProfile from "@/components/CreateProfile";
import Consent from "@/components/Consent";
import KeyboardTest from "@/components/KeyboardTest";
import MouseDotTask from "@/components/MouseDotTask";
import MouseTrackTask from "@/components/MouseTrackTask";
import MouseDragTask from "@/components/MouseDragTask";
import ProfileSetup from "@/components/ProfileSetup";
import BehaviorResult from "@/components/BehaviorResult";
import AdminDashboard from "@/components/AdminDashboard";
import MyStatsPage from "@/components/MyStatsPage";

// Screens not present in lib/types.ts's Screen union yet — extending inline
// keeps this additive rather than requiring every existing screen name to
// be touched.
type ExtendedScreen = Screen | "login" | "register" | "claim" | "create-profile" | "stats";

export default function Home() {
  const { user, loading: authLoading } = useAuth();
  const isAdmin = user?.role === "org_admin" || user?.role === "platform_admin";

  const [screen, rawSetScreen] = useState<ExtendedScreen>("landing");
  const [mode, setMode] = useState<AuthMode>("identify");
  const [selected, setSelected] = useState<Profile[]>([]);
  const [myProfile, setMyProfile] = useState<Profile | null>(null);
  // Bug #16 fix: "haven't checked yet / still checking", "checked — found
  // one", "checked — genuinely none", and "the check itself failed" are four
  // different situations. The old code collapsed all failures into the same
  // null as "never enrolled", which silently routed people into
  // create-profile and tripped the backend's real 409 (their profile was
  // never actually gone). Only "none" may ever be treated as "go enroll".
  const [profileCheck, setProfileCheck] = useState<"idle" | "loading" | "found" | "none" | "error">("idle");
  const [profileCheckTick, setProfileCheckTick] = useState(0);
  const [myStats, setMyStats] = useState<MyStats | null>(null);
  const [result, setResult] = useState<EnrollmentResult | VerificationResult | null>(null);
  const [enrollmentStats, setEnrollmentStats] = useState<SessionBehaviorMetrics | null>(null);
  const [submitError, setSubmitError] = useState("");
  const [retrainState, setRetrainState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const passivePointsRef = usePassiveMouseCollector();
  const sessionStart = useRef(0);
  const keyboardData = useRef<{ events: KeyEvent[]; pangramLen: number; freeLen: number }>({ events: [], pangramLen: 0, freeLen: 0 });
  const dotTrials = useRef<DotTrial[]>([]);
  const trackTrials = useRef<TrackTrial[]>([]);
  const dragTrials = useRef<DragTrial[]>([]);
  const lastSessionData = useRef<SessionData | null>(null);
  const verifiedProfileId = useRef<string | null>(null);
  const screenRef = useRef<ExtendedScreen>("landing");
  const { showToast } = useToast();

  // Navigation & state integrity: every screen change is also pushed onto
  // real browser history, so the back button moves between screens instead
  // of exiting/reloading the app. `setScreen` is the one function every
  // call site already used — wrapping it here means no call site elsewhere
  // needs to change.
  const isPopping = useRef(false);
  function setScreen(next: ExtendedScreen) {
    rawSetScreen(next);
    screenRef.current = next;
    if (!isPopping.current && typeof window !== "undefined") {
      window.history.pushState({ screen: next }, "");
    }
  }

  function discardInProgress() {
    keyboardData.current = { events: [], pangramLen: 0, freeLen: 0 };
    dotTrials.current = [];
    trackTrials.current = [];
    dragTrials.current = [];
    passivePointsRef.current = [];
  }

  const IN_PROGRESS_SCREENS: ExtendedScreen[] = ["consent", "keyboard", "mouse-dot", "mouse-track", "mouse-drag"];

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.history.replaceState({ screen: "landing" }, "");
    function onPopState(event: PopStateEvent) {
      const prevScreen = screenRef.current;
      const nextScreen = ((event.state as { screen?: ExtendedScreen } | null)?.screen) || "landing";
      // Leaving an in-progress data-collection screen via the browser's own
      // back button must discard collected refs cleanly, never let a
      // half-finished session get submitted later.
      if (IN_PROGRESS_SCREENS.includes(prevScreen)) discardInProgress();
      isPopping.current = true;
      rawSetScreen(nextScreen);
      screenRef.current = nextScreen;
      isPopping.current = false;
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // An explicit in-app "back"/cancel affordance mid-flow (spec item 4): same
  // discard-cleanly guarantee as the browser back button above, reachable
  // without touching the browser's own back button at all.
  function cancelTask() {
    discardInProgress();
    setSubmitError("");
    setScreen("landing");
  }

  // Resolve the caller's own profile (if any) whenever they're logged in —
  // this drives whether Landing offers "enroll" (first time) or "verify
  // myself" (already enrolled), matching the one-profile-per-account model.
  useEffect(() => {
    if (!user) { Promise.resolve().then(() => { setMyProfile(null); setProfileCheck("idle"); }); return; }
    let cancelled = false;
    Promise.resolve().then(() => { if (!cancelled) setProfileCheck("loading"); });
    api.profiles()
      .then((rows) => {
        if (cancelled) return;
        const mine = rows.find((p) => p.user_id === user.id) || null;
        setMyProfile(mine);
        setProfileCheck(mine ? "found" : "none");
      })
      .catch(() => {
        if (cancelled) return;
        setProfileCheck("error");
      });
    return () => { cancelled = true; };
  }, [user, profileCheckTick]);

  // Landing highlights strip / My Stats page: fetched once a profile is
  // confirmed to exist, and refreshed after every successful enrollment.
  useEffect(() => {
    if (profileCheck !== "found") { Promise.resolve().then(() => setMyStats(null)); return; }
    let cancelled = false;
    api.myStats().then((stats) => { if (!cancelled) setMyStats(stats); }).catch(() => {});
    return () => { cancelled = true; };
  }, [profileCheck]);

  // Once login/registration succeeds, drop back to the landing screen
  // rather than leaving the person stranded on the login/register form.
  useEffect(() => {
    if (!(user && (screen === "login" || screen === "register"))) return;
    Promise.resolve().then(() => setScreen("landing"));
  }, [user, screen]);

  function reset() { setScreen("landing"); setResult(null); setSelected([]); setSubmitError(""); discardInProgress(); }

  function retryProfileCheck() { setProfileCheckTick((n) => n + 1); }

  function beginEnroll() {
    // Never route into profile creation off an unresolved/failed check —
    // that's bug #16. Only a confirmed "none" may open create-profile.
    if (profileCheck === "error" || profileCheck === "loading") { retryProfileCheck(); return; }
    if (myProfile) { setMode("enroll"); setSelected([myProfile]); sessionStart.current = performance.now(); setScreen("consent"); }
    else setScreen("create-profile");
  }
  function beginVerifySelf() {
    if (profileCheck === "error" || profileCheck === "loading") { retryProfileCheck(); return; }
    if (!myProfile) { setScreen("create-profile"); return; }
    setMode("verify"); setSelected([myProfile]); sessionStart.current = performance.now(); setScreen("consent");
  }
  function beginIdentify() { setMode("identify"); setScreen("setup"); }

  function onProfileCreated(profile: Profile) {
    setMyProfile(profile);
    setMode("enroll");
    setSelected([profile]);
    sessionStart.current = performance.now();
    setScreen("consent");
  }

  function ready(profiles: Profile[]) {
    setSelected(profiles);
    setMode(profiles.length === 1 ? "verify" : "identify");
    sessionStart.current = performance.now();
    setScreen("consent");
  }

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
    lastSessionData.current = data;
    verifiedProfileId.current = mode === "verify" ? selected[0].id : null;
    setRetrainState("idle");
    try {
      const response = mode === "enroll" ? await api.enroll(selected[0].id, data) : mode === "verify" ? await api.verify(selected[0].id, data) : await api.identify(selected.map((profile) => profile.id), data);
      if ("profile" in response) setMyProfile(response.profile);
      setResult(response);
      setScreen("result");
      if (mode === "enroll") {
        // Enrollment stats (spec item 7): computed via the new self-service
        // stats endpoint immediately after the submission that just happened.
        setEnrollmentStats(null);
        api.myStats().then((stats) => { setEnrollmentStats(stats.latest); setMyStats(stats); }).catch(() => {});
      }
    } catch (error) { setSubmitError(error instanceof Error ? error.message : "Submission failed"); }
  }

  async function retrainFromLastVerification() {
    if (!lastSessionData.current || !verifiedProfileId.current) return;
    setRetrainState("loading");
    try {
      const response = await api.enroll(verifiedProfileId.current, lastSessionData.current);
      setMyProfile(response.profile);
      setRetrainState("done");
      showToast("Session added to your profile's training data", "success");
      api.myStats().then(setMyStats).catch(() => {});
    } catch {
      setRetrainState("error");
    }
  }

  if (authLoading) {
    return <div className="min-h-screen flex items-center justify-center text-muted text-sm">loading…</div>;
  }
  if (screen === "login") return <Login onSwitchToRegister={() => setScreen("register")} onBack={reset} />;
  if (screen === "register") return <Register onSwitchToLogin={() => setScreen("login")} onBack={reset} />;
  if (screen === "claim" && user) return <ClaimProfile onClaimed={(profile) => { setMyProfile(profile); setScreen("landing"); }} onBack={reset} />;
  if (screen === "create-profile" && user) return <CreateProfile onCreated={onProfileCreated} onBack={reset} />;
  if (screen === "admin") {
    if (!isAdmin) return <AccessDenied onBack={reset} />;
    return <AdminDashboard onBack={reset} />;
  }
  if (screen === "stats") {
    if (!user) return <Login onSwitchToRegister={() => setScreen("register")} onBack={reset} />;
    return <MyStatsPage stats={myStats} onBack={reset} />;
  }
  if (screen === "setup") {
    if (!user) return <Login onSwitchToRegister={() => setScreen("register")} onBack={reset} />;
    if (mode === "identify" && !isAdmin) return <AccessDenied onBack={reset} />;
    return <ProfileSetup kind={mode === "enroll" ? "enroll" : "identify"} onReady={ready} onBack={reset} />;
  }
  if (screen === "result" && result) {
    return (
      <BehaviorResult
        result={result}
        onHome={reset}
        enrollmentStats={enrollmentStats}
        onRetrain={retrainFromLastVerification}
        retrainState={retrainState}
      />
    );
  }

  const showRail = !["landing", "done", "setup", "admin", "result"].includes(screen);
  const quickVerification = mode !== "enroll";
  return <div className="flex flex-col min-h-screen">
    {showRail && (
      <div className="w-full max-w-2xl mx-auto px-6 pt-6 flex items-center gap-4">
        <button
          onClick={cancelTask}
          className="shrink-0 text-sm text-muted font-mono-tight py-2.5 px-3 -ml-3 hover:text-danger transition inline-flex items-center gap-1.5"
        >
          ← cancel
        </button>
        <div className="flex-1"><StageRail current={screen as Screen} /></div>
      </div>
    )}
    {screen === "landing" && (
      <Landing
        onEnroll={beginEnroll}
        onVerifySelf={beginVerifySelf}
        onIdentify={beginIdentify}
        onAdmin={() => setScreen("admin")}
        onLogin={() => setScreen("login")}
        onRegister={() => setScreen("register")}
        onClaim={() => setScreen("claim")}
        hasOwnProfile={Boolean(myProfile)}
        profileCheck={profileCheck}
        onRetryProfileCheck={retryProfileCheck}
        myProfileId={myProfile?.id ?? null}
        stats={myStats}
        onOpenStats={() => setScreen("stats")}
      />
    )}
    {screen === "consent" && <Consent onAgree={() => setScreen("keyboard")} />}
    {screen === "keyboard" && <KeyboardTest segmentSeconds={quickVerification ? 20 : 90} onComplete={(events, pangramLen, freeLen) => { keyboardData.current = { events, pangramLen, freeLen }; setScreen("mouse-dot"); }} />}
    {screen === "mouse-dot" && <MouseDotTask targetCount={quickVerification ? 8 : 25} onComplete={(trials) => { dotTrials.current = trials; setScreen("mouse-track"); }} />}
    {screen === "mouse-track" && <MouseTrackTask trialDurationMs={quickVerification ? 6000 : 20000} onComplete={(trials) => { trackTrials.current = trials; setScreen("mouse-drag"); }} />}
    {screen === "mouse-drag" && <MouseDragTask dragCount={quickVerification ? 4 : 10} onComplete={(trials) => { dragTrials.current = trials; void submit(buildSession()); }} />}
    {submitError && <div className="fixed bottom-5 left-1/2 -translate-x-1/2 bg-danger text-white rounded-lg px-5 py-3 text-sm shadow-xl">{submitError} <button onClick={() => void submit(buildSession())} className="underline ml-3">retry</button></div>}
  </div>;
}

function AccessDenied({ onBack }: { onBack: () => void }) {
  return (
    <div className="min-h-screen flex items-center justify-center px-6">
      <div className="max-w-sm text-center fade-up">
        <div className="font-mono-tight text-xs uppercase tracking-[0.3em] text-danger mb-3">access denied</div>
        <p className="text-sm text-muted mb-6">This area requires elevated (staff) access.</p>
        <button onClick={onBack} className="bg-text text-bg rounded-lg px-7 py-3.5 font-mono-tight text-xs uppercase tracking-widest">back home</button>
      </div>
    </div>
  );
}
