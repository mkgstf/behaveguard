"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Profile } from "@/lib/types";
import { useToast } from "@/lib/toast";

export default function ClaimProfile({ onClaimed, onBack }: { onClaimed: (profile: Profile) => void; onBack: () => void }) {
  const { showToast } = useToast();
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      const profile = await api.claimProfile(token.trim());
      showToast(`Profile "${profile.label}" claimed successfully`, "success");
      onClaimed(profile);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not claim this profile");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-6">
      <div className="max-w-sm w-full fade-up">
        <button onClick={onBack} className="text-sm text-muted font-mono-tight mb-8 py-2 -ml-1 pl-1 pr-3 hover:text-text inline-flex items-center gap-1.5">← home</button>
        <div className="font-mono-tight text-xs uppercase tracking-[0.3em] text-amber mb-3">link existing profile</div>
        <h2 className="text-2xl font-semibold mb-3">Claim your profile</h2>
        <p className="text-sm text-muted mb-7">
          If someone gave you a one-time activation link or token for a profile that already exists, paste it below to link it to your account.
        </p>

        <form onSubmit={submit} className="space-y-3">
          <input
            required
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="claim token"
            className="w-full bg-surface border border-border rounded-lg px-4 py-3 outline-none focus:border-amber font-mono-tight text-sm"
          />
          {error && <p className="text-danger text-sm">{error}</p>}
          <button
            type="submit"
            disabled={loading || !token.trim()}
            className="w-full bg-amber text-bg rounded-lg py-3 font-mono-tight text-sm uppercase tracking-wider disabled:opacity-40"
          >
            {loading ? "linking…" : "link profile"}
          </button>
        </form>
      </div>
    </div>
  );
}
