"use client";

import { useState } from "react";
import { useAuth, googleLoginUrl } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import GoogleIcon from "@/components/GoogleIcon";

export default function Login({ onSwitchToRegister, onBack }: { onSwitchToRegister: () => void; onBack: () => void }) {
  const { loginWithPassword } = useAuth();
  const { showToast } = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await loginWithPassword(email.trim(), password);
      showToast("Logged in successfully", "success");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-dvh flex justify-center px-6 pt-[12vh] pb-16 overflow-y-auto">
      <div className="max-w-sm w-full fade-up">
        <button onClick={onBack} className="text-sm text-muted font-mono-tight mb-8 py-2 -ml-1 pl-1 pr-3 hover:text-text inline-flex items-center gap-1.5">← home</button>
        <div className="font-mono-tight text-xs uppercase tracking-[0.3em] text-cyan mb-3">welcome back</div>
        <h2 className="text-2xl font-semibold mb-7">Log in</h2>

        <form onSubmit={submit} className="space-y-3">
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="email"
            className="w-full bg-surface border border-border rounded-lg px-4 py-3 outline-none focus:border-cyan"
          />
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="password"
            className="w-full bg-surface border border-border rounded-lg px-4 py-3 outline-none focus:border-cyan"
          />
          {error && <p className="text-danger text-sm">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-cyan text-bg rounded-lg py-3 font-mono-tight text-sm uppercase tracking-wider disabled:opacity-40"
          >
            {loading ? "logging in…" : "log in"}
          </button>
        </form>

        <div className="flex items-center gap-3 my-6">
          <div className="flex-1 h-px bg-border" />
          <span className="text-xs text-muted font-mono-tight">or</span>
          <div className="flex-1 h-px bg-border" />
        </div>

        <a
          href={googleLoginUrl()}
          className="w-full flex items-center justify-center gap-2 border border-border rounded-lg py-3 text-sm hover:border-muted transition"
        >
          <GoogleIcon />
          Sign in with Google
        </a>

        <button onClick={onSwitchToRegister} className="w-full text-center text-xs text-muted font-mono-tight mt-6 hover:text-text">
          don&apos;t have an account? register →
        </button>
      </div>
    </div>
  );
}
