"use client";

import { useEffect, useRef } from "react";
import { MousePoint } from "./types";

export function usePassiveMouseCollector() {
  const pointsRef = useRef<MousePoint[]>([]);
  const last = useRef<{ x: number; y: number; ts: number } | null>(null);

  useEffect(() => {
    function onMove(e: PointerEvent) {
      const ts = performance.now();
      const x = e.clientX;
      const y = e.clientY;
      const prev = last.current;
      if (prev) {
        const dx = x - prev.x;
        const dy = y - prev.y;
        const dt = ts - prev.ts;
        if (Math.hypot(dx, dy) < 5 && dt < 16) return;
        pointsRef.current.push({ x, y, ts, dx, dy, pressure: e.pressure ?? 0.5 });
      } else {
        pointsRef.current.push({ x, y, ts, dx: 0, dy: 0, pressure: e.pressure ?? 0.5 });
      }
      last.current = { x, y, ts };
      if (pointsRef.current.length > 3000) pointsRef.current.shift();
    }
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => window.removeEventListener("pointermove", onMove);
  }, []);

  return pointsRef;
}
