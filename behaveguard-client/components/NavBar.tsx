"use client";

import { useEffect, useRef, useState } from "react";
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
  const rootRef = useRef<HTMLDivElement>(null);

  // Close on any click outside the whole nav (trigger + dropdown).
  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  if (!user) return null;

  async function handleSignOut() {
    await signOut();
    showToast("Logged out", "success");
  }

  return (
    // `relative` here (not on the fixed wrapper) is what keeps the dropdown
    // from stretching the fixed box's own width — it used to grow to fit
    // the 224px dropdown and, anchored via right-4, dragged the trigger
    // button leftward every time it opened.
    <div ref={rootRef} className="fixed top-4 right-4 z-30">
      <div className="relative">
        <button
          onClick={() => setOpen((v) => !v)}
          className="cursor-pointer flex items-center gap-2 bg-surface/90 backdrop-blur border border-border rounded-full pl-3 pr-2.5 py-1.5 text-xs font-mono-tight hover:border-muted transition max-w-[70vw]"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-cyan shrink-0" />
          <span className="max-w-[220px] truncate text-muted">{user.email}</span>
          <span className="text-muted shrink-0">{open ? "▲" : "▼"}</span>
        </button>
        {open && (
          <div className="absolute top-full right-0 mt-2 w-64 max-w-[80vw] bg-surface border border-border rounded-xl shadow-xl overflow-hidden fade-up">
            <div className="px-4 py-3 border-b border-border text-xs font-mono-tight text-muted break-all">{user.email}</div>
            {isTrained && (
              <button onClick={() => { setOpen(false); onStats(); }} className="cursor-pointer w-full text-left px-4 py-3 font-mono-tight text-sm hover:bg-surface-2 transition flex items-center justify-between">
                my stats <span className="text-muted text-xs">→</span>
              </button>
            )}
            {!isTrained && (
              <button onClick={() => { setOpen(false); onClaim(); }} className="cursor-pointer w-full text-left px-4 py-3 font-mono-tight text-sm hover:bg-surface-2 transition flex items-center justify-between">
                claim a profile <span className="text-muted text-xs">→</span>
              </button>
            )}
            {isAdmin && (
              <button onClick={() => { setOpen(false); onAdmin(); }} className="cursor-pointer w-full text-left px-4 py-3 font-mono-tight text-sm hover:bg-surface-2 transition border-t border-border flex items-center justify-between">
                admin dashboard <span className="text-muted text-xs">→</span>
              </button>
            )}
            <button onClick={() => { setOpen(false); void handleSignOut(); }} className="cursor-pointer w-full text-left px-4 py-3 font-mono-tight text-sm hover:bg-danger/10 hover:text-danger transition border-t border-border">
              log out
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
