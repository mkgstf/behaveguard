"use client";

import { useState } from "react";

export default function NameEntry({ onSubmit }: { onSubmit: (name: string) => void }) {
  const [name, setName] = useState("");

  return (
    <div className="flex-1 flex items-center justify-center px-6">
      <form
        className="max-w-md w-full fade-up"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) onSubmit(name.trim());
        }}
      >
        <div className="font-mono-tight text-xs uppercase tracking-[0.3em] text-muted mb-3">
          session label
        </div>
        <h2 className="text-2xl font-semibold mb-5">What should we call this session?</h2>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="your name or a nickname"
          className="w-full bg-surface border border-border rounded-md px-4 py-3 text-text font-mono-tight outline-none focus:border-amber transition mb-6"
        />
        <button
          type="submit"
          disabled={!name.trim()}
          className="w-full font-mono-tight text-sm uppercase tracking-wider bg-amber text-bg px-8 py-3 rounded-md disabled:opacity-30 disabled:cursor-not-allowed hover:brightness-110 transition active:scale-[0.98]"
        >
          begin keyboard test →
        </button>
      </form>
    </div>
  );
}
