"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Profile } from "@/lib/types";

export default function CreateProfile({ onCreated, onBack }: { onCreated: (profile: Profile) => void; onBack: () => void }) {
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    setError("");
    setLoading(true);
    try {
      const profile = await api.createProfile(name.trim());
      onCreated(profile);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create your profile");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex-1 flex items-center justify-center px-6">
      <div className="max-w-sm w-full fade-up">
        <button onClick={onBack} className="text-xs text-muted font-mono-tight mb-8 hover:text-text">← home</button>
        <div className="font-mono-tight text-xs uppercase tracking-[0.3em] text-amber mb-3">first enrollment</div>
        <h2 className="text-2xl font-semibold mb-3">Name your profile</h2>
        <p className="text-sm text-muted mb-7">
          This is tied to your account — you can only ever enroll one profile per login.
        </p>

        <form onSubmit={submit} className="space-y-3">
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="profile name"
            className="w-full bg-surface border border-border rounded-lg px-4 py-3 outline-none focus:border-amber"
          />
          {error && <p className="text-danger text-sm">{error}</p>}
          <button
            type="submit"
            disabled={loading || !name.trim()}
            className="w-full bg-amber text-bg rounded-lg py-3 font-mono-tight text-sm uppercase tracking-wider disabled:opacity-40"
          >
            {loading ? "creating…" : "create & continue →"}
          </button>
        </form>
      </div>
    </div>
  );
}
