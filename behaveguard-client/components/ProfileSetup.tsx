"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Profile } from "@/lib/types";

export default function ProfileSetup({ kind, onReady, onBack }: {
  kind: "enroll" | "identify";
  onReady: (profiles: Profile[]) => void;
  onBack: () => void;
}) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => { api.profiles().then((rows) => setProfiles(rows.filter((p) => !p.blacklisted))).catch((e) => setError(e.message)).finally(() => setLoading(false)); }, []);

  async function create() {
    if (!name.trim()) return;
    try {
      const profile = await api.createProfile(name.trim());
      onReady([profile]);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not create profile"); }
  }

  function toggle(id: string) {
    if (kind === "enroll") setSelected([id]);
    else setSelected((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]);
  }

  return (
    <div className="flex-1 px-6 py-10 overflow-y-auto">
      <div className="max-w-2xl mx-auto fade-up">
        <button onClick={onBack} className="text-xs text-muted font-mono-tight mb-8 hover:text-text">← home</button>
        <div className={`font-mono-tight text-xs uppercase tracking-[0.3em] mb-3 ${kind === "enroll" ? "text-amber" : "text-cyan"}`}>
          {kind === "enroll" ? "profile enrollment" : "candidate selection"}
        </div>
        <h2 className="text-2xl font-semibold mb-2">{kind === "enroll" ? "Who are we enrolling?" : "Who should this session be tested against?"}</h2>
        <p className="text-sm text-muted mb-7">
          {kind === "enroll" ? "Select an existing profile to strengthen it, or create a new one." : "Select one profile for a detailed 1:1 comparison. Select multiple profiles to identify the closest person."}
        </p>

        {kind === "enroll" && (
          <div className="flex gap-2 mb-6">
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="new profile name" className="flex-1 bg-surface border border-border rounded-lg px-4 py-3 outline-none focus:border-amber" />
            <button onClick={create} disabled={!name.trim()} className="bg-amber text-bg px-5 rounded-lg disabled:opacity-30 font-mono-tight text-xs uppercase">create</button>
          </div>
        )}

        {error && <div className="text-danger text-sm mb-4">{error}. Make sure the backend is running.</div>}
        {loading ? <p className="text-muted">loading profiles…</p> : (
          <div className="grid sm:grid-cols-2 gap-3 mb-7">
            {profiles.map((profile) => {
              const active = selected.includes(profile.id);
              return (
                <button key={profile.id} onClick={() => toggle(profile.id)} className={`text-left rounded-xl border p-4 transition ${active ? "border-cyan bg-cyan/10" : "border-border bg-surface hover:border-muted"}`}>
                  <div className="flex justify-between gap-3">
                    <span className="font-medium">{profile.label}</span>
                    <span className="font-mono-tight text-xs text-muted">{profile.enrollment_count} sample{profile.enrollment_count === 1 ? "" : "s"}</span>
                  </div>
                  <div className="text-xs text-muted mt-2">{profile.enrollment_count >= 3 ? "ready" : `${3 - profile.enrollment_count} more recommended`}</div>
                </button>
              );
            })}
            {!profiles.length && <p className="text-sm text-muted col-span-2">No active profiles yet.</p>}
          </div>
        )}
        <button disabled={!selected.length} onClick={() => onReady(profiles.filter((p) => selected.includes(p.id)))} className={`w-full py-3 rounded-lg text-bg font-mono-tight text-sm uppercase tracking-wider disabled:opacity-30 ${kind === "enroll" ? "bg-amber" : "bg-cyan"}`}>
          continue with {selected.length || 0} selected →
        </button>
      </div>
    </div>
  );
}
