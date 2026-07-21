"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";

export default function NavBar({
  isAdmin,
  isTrained,
  onClaim,
  onAdmin,
  onStats,
}: {
  isAdmin: boolean;
  isTrained: boolean;
  onClaim: () => void;
  onAdmin: () => void;
  onStats: () => void;
}) {
  const { user, signOut } = useAuth();
  const { showToast } = useToast();
  const [open, setOpen] = useState(false);

  if (!user) return null;

  async function handleSignOut() {
    await signOut();
    showToast("Logged out", "success");
  }

  return (
    <div className="fixed top-4 right-4 z-30">
      <button
        onClick={() => setOpen((v) => !v)}
        className="cursor-pointer flex items-center gap-2 bg-surface/90 backdrop-blur border border-border rounded-full pl-3 pr-2 py-1.5 text-xs font-mono-tight hover:border-muted transition"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-cyan" />
        <span className="max-w-[140px] truncate text-muted">{user.email}</span>
        <span className="text-muted">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="mt-2 w-56 bg-surface border border-border rounded-xl shadow-xl overflow-hidden fade-up text-sm">
          {isTrained && (
            <button onClick={() => { setOpen(false); onStats(); }} className="cursor-pointer w-full text-left px-4 py-3 hover:bg-surface-2 transition">
              my stats
            </button>
          )}
          {!isTrained && (
            <button onClick={() => { setOpen(false); onClaim(); }} className="cursor-pointer w-full text-left px-4 py-3 hover:bg-surface-2 transition">
              claim a profile
            </button>
          )}
          {isAdmin && (
            <button onClick={() => { setOpen(false); onAdmin(); }} className="cursor-pointer w-full text-left px-4 py-3 hover:bg-surface-2 transition border-t border-border">
              admin dashboard
            </button>
          )}
          <button onClick={() => { setOpen(false); void handleSignOut(); }} className="cursor-pointer w-full text-left px-4 py-3 hover:bg-danger/10 hover:text-danger transition border-t border-border">
            log out
          </button>
        </div>
      )}
    </div>
  );
}
