"use client";

import { useState } from "react";
import { useAuth, googleLoginUrl } from "@/lib/auth";
import { useToast } from "@/lib/toast";

export default function Register({ onSwitchToLogin, onBack }: { onSwitchToLogin: () => void; onBack: () => void }) {
  const { registerWithPassword } = useAuth();
  const { showToast } = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setLoading(true);
    try {
      await registerWithPassword(email.trim(), password);
      showToast("Account created — welcome!", "success");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Registration failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-6">
      <div className="max-w-sm w-full fade-up">
        <button onClick={onBack} className="text-sm text-muted font-mono-tight mb-8 py-2 -ml-1 pl-1 pr-3 hover:text-text inline-flex items-center gap-1.5">← home</button>
        <div className="font-mono-tight text-xs uppercase tracking-[0.3em] text-amber mb-3">get started</div>
        <h2 className="text-2xl font-semibold mb-7">Create an account</h2>

        <form onSubmit={submit} className="space-y-3">
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="email"
            className="w-full bg-surface border border-border rounded-lg px-4 py-3 outline-none focus:border-amber"
          />
          <input
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="password (min. 8 characters)"
            className="w-full bg-surface border border-border rounded-lg px-4 py-3 outline-none focus:border-amber"
          />
          {error && <p className="text-danger text-sm">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-amber text-bg rounded-lg py-3 font-mono-tight text-sm uppercase tracking-wider disabled:opacity-40"
          >
            {loading ? "creating account…" : "create account"}
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
          Continue with Google
        </a>

        <button onClick={onSwitchToLogin} className="w-full text-center text-xs text-muted font-mono-tight mt-6 hover:text-text">
          already have an account? log in →
        </button>
      </div>
    </div>
  );
}
