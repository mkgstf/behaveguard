"use client";

import { Screen } from "@/lib/types";

const STAGES: { key: Screen; label: string; color: "amber" | "cyan" | "neutral" }[] = [
  { key: "consent", label: "consent", color: "neutral" },
  { key: "keyboard", label: "keyboard", color: "amber" },
  { key: "mouse-dot", label: "mouse · target", color: "cyan" },
  { key: "mouse-track", label: "mouse · pursuit", color: "cyan" },
  { key: "mouse-drag", label: "mouse · drag", color: "cyan" },
  { key: "analytics", label: "results", color: "neutral" },
];

export default function StageRail({ current }: { current: Screen }) {
  const idx = STAGES.findIndex((s) => s.key === current);

  return (
    <div className="w-full max-w-2xl mx-auto px-6 pt-6">
      <div className="flex items-center gap-1">
        {STAGES.map((s, i) => {
          const active = i === idx;
          const done = i < idx;
          const color =
            s.color === "amber" ? "bg-amber" : s.color === "cyan" ? "bg-cyan" : "bg-text";
          return (
            <div key={s.key} className="flex-1 group relative">
              <div
                className={`h-[3px] rounded-full transition-all duration-300 ${
                  done ? color : active ? color : "bg-border"
                } ${active ? "opacity-100" : done ? "opacity-60" : "opacity-100"}`}
              />
              {active && (
                <span className="absolute left-1/2 -translate-x-1/2 top-2 text-[10px] font-mono-tight uppercase tracking-widest text-muted whitespace-nowrap">
                  {s.label}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
