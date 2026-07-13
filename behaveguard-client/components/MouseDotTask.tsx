"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { DotTrial, PathPoint } from "@/lib/types";
import { computePathKinematics } from "@/lib/kinematics";

const DOT_RADIUS = 22;

function randomPoint(w: number, h: number) {
  const pad = DOT_RADIUS + 20;
  return {
    x: pad + Math.random() * (w - pad * 2),
    y: pad + Math.random() * (h - pad * 2) + 60,
  };
}

export default function MouseDotTask({ onComplete, targetCount = 25 }: { onComplete: (trials: DotTrial[]) => void; targetCount?: number }) {
  const areaRef = useRef<HTMLDivElement>(null);
  const [dot, setDot] = useState({ x: 200, y: 200 });
  const [trialIdx, setTrialIdx] = useState(0);
  const [hit, setHit] = useState(false);
  const trialsRef = useRef<DotTrial[]>([]);
  const appearedAt = useRef(0);
  const pathRef = useRef<PathPoint[]>([]);
  const lastSample = useRef(0);
  const dotRef = useRef({ x: 200, y: 200 }); // mirror dot state for handlers

  const placeDot = useCallback(() => {
    const area = areaRef.current;
    if (!area) return;
    const { width, height } = area.getBoundingClientRect();
    const pt = randomPoint(width, height - 60);
    setDot(pt);
    dotRef.current = pt;
    appearedAt.current = performance.now();
    pathRef.current = [];
  }, []);

  useEffect(() => { placeDot(); }, [placeDot]);

  function handlePointerMove(e: React.PointerEvent<HTMLDivElement>) {
    const now = performance.now();
    if (now - lastSample.current < 16) return;
    lastSample.current = now;
    const rect = areaRef.current!.getBoundingClientRect();
    pathRef.current.push({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
      ts: now,
      pressure: e.pressure ?? 0.5,
    });
  }

  function handleDotClick(e: React.MouseEvent) {
    e.stopPropagation();
    const rect = areaRef.current!.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const clickY = e.clientY - rect.top;
    const clickedAt = performance.now();
    const target = dotRef.current;

    const trial: DotTrial = {
      // existing fields — unchanged
      target_x: target.x,
      target_y: target.y,
      click_x: clickX,
      click_y: clickY,
      appeared_at: appearedAt.current,
      clicked_at: clickedAt,
      travel_time_ms: clickedAt - appearedAt.current,
      error_px: Math.hypot(clickX - target.x, clickY - target.y),
      path: pathRef.current,
      // new
      kinematics: computePathKinematics(pathRef.current, target.x, target.y, DOT_RADIUS),
    };
    trialsRef.current.push(trial);
    setHit(true);
    setTimeout(() => {
      setHit(false);
      if (trialIdx + 1 >= targetCount) {
        onComplete(trialsRef.current);
      } else {
        setTrialIdx((i) => i + 1);
        placeDot();
      }
    }, 90);
  }

  const progressPct = (trialIdx / targetCount) * 100;

  return (
    <div className="flex-1 flex flex-col px-6 pb-6">
      <div className="max-w-3xl w-full mx-auto fade-up flex-1 flex flex-col">
        <div className="flex items-center justify-between mb-3 pt-2">
          <span className="font-mono-tight text-xs uppercase tracking-[0.3em] text-cyan">
            task 1 · follow the target
          </span>
          <span className="font-mono-tight text-sm text-muted tabular-nums">
            {trialIdx}/{targetCount}
          </span>
        </div>
        <div className="h-1 w-full bg-border rounded-full mb-4 overflow-hidden">
          <div
            className="h-full bg-cyan transition-all duration-200"
            style={{ width: `${progressPct}%` }}
          />
        </div>

        <div
          ref={areaRef}
          onPointerMove={handlePointerMove}
          className="relative flex-1 min-h-[420px] bg-surface border border-border rounded-xl overflow-hidden cursor-crosshair"
        >
          <p className="absolute top-3 left-1/2 -translate-x-1/2 text-xs text-muted font-mono-tight">
            click each dot as it appears
          </p>
          <button
            onClick={handleDotClick}
            style={{ left: dot.x - DOT_RADIUS, top: dot.y - DOT_RADIUS, width: DOT_RADIUS * 2, height: DOT_RADIUS * 2 }}
            className="absolute rounded-full flex items-center justify-center"
            aria-label="target"
          >
            <span className="absolute inset-0 rounded-full border-2 border-cyan pulse-ring" />
            <span
              className={`relative w-full h-full rounded-full transition-transform ${
                hit ? "scale-75 bg-text" : "bg-cyan"
              }`}
            />
          </button>
        </div>
      </div>
    </div>
  );
}
