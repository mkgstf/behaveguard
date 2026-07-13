"use client";

import { useMemo } from "react";
import {
  LineChart, Line, BarChart, Bar, ScatterChart, Scatter,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ZAxis,
} from "recharts";
import { SessionData } from "@/lib/types";
import {
  dwellTimes, flightTimes, topDigraphs, wpmSeries, histogram, dotMetrics, dragMetrics, mean,
} from "@/lib/analytics";

const axisStyle = { fontSize: 11, fontFamily: "var(--font-mono)", fill: "var(--muted)" };

export default function Analytics({ data, onFinish }: { data: SessionData; onFinish: () => void }) {

  const kb = data.keyboard.events;
  const dwell = useMemo(() => histogram(dwellTimes(kb)), [kb]);
  const flight = useMemo(() => histogram(flightTimes(kb)), [kb]);
  const digraphs = useMemo(() => topDigraphs(kb), [kb]);
  const startTs = kb[0]?.press_ts ?? 0;
  const endTs = kb[kb.length - 1]?.press_ts ?? 1;
  const wpm = useMemo(() => wpmSeries(kb, startTs, endTs), [kb, startTs, endTs]);
  const avgWpm = useMemo(() => Math.round(mean(wpm.map((w) => w.wpm))), [wpm]);
  const avgDwell = useMemo(() => Math.round(mean(dwellTimes(kb))), [kb]);
  const avgFlight = useMemo(() => Math.round(mean(flightTimes(kb))), [kb]);

  const dot = useMemo(() => dotMetrics(data.mouse.dot_trials), [data.mouse.dot_trials]);
  const drag = useMemo(() => dragMetrics(data.mouse.drag_trials), [data.mouse.drag_trials]);

  const scatterData = data.mouse.dot_trials.map((t, i) => ({
    error: Math.round(t.error_px),
    travel: Math.round(t.travel_time_ms),
    idx: i,
  }));
  const travelBars = data.mouse.dot_trials.map((t, i) => ({ trial: i + 1, ms: Math.round(t.travel_time_ms) }));
  const velocitySeries = dot.velocities.map((v, i) => ({ trial: i + 1, v: Math.round(v) }));

  const maxDigraphMs = Math.max(...digraphs.map((d) => d.avg_ms), 1);

  return (
    <div className="flex-1 px-6 py-8 overflow-y-auto">
      <div className="max-w-4xl mx-auto fade-up">
        <div className="font-mono-tight text-xs uppercase tracking-[0.3em] text-muted mb-2">results</div>
        <h2 className="text-2xl font-semibold mb-8">Here&apos;s how you type and move</h2>

        {/* KEYBOARD PANEL */}
        <Panel title="keyboard" accent="amber">
          <StatRow
            stats={[
              { label: "avg wpm", value: avgWpm },
              { label: "avg dwell", value: `${avgDwell}ms` },
              { label: "avg flight", value: `${avgFlight}ms` },
              { label: "keystrokes", value: kb.length },
            ]}
          />

          <ChartBlock title="wpm over time">
            <ResponsiveContainer width="100%" height={160}>
              <LineChart data={wpm}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="t" tick={axisStyle} unit="s" />
                <YAxis tick={axisStyle} width={32} />
                <Tooltip contentStyle={tooltipStyle} />
                <Line type="monotone" dataKey="wpm" stroke="var(--amber)" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </ChartBlock>

          <div className="grid sm:grid-cols-2 gap-4">
            <ChartBlock title="dwell time distribution">
              <ResponsiveContainer width="100%" height={140}>
                <BarChart data={dwell}>
                  <XAxis dataKey="bin" tick={axisStyle} />
                  <YAxis tick={axisStyle} width={28} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Bar dataKey="count" fill="var(--amber)" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartBlock>
            <ChartBlock title="flight time distribution">
              <ResponsiveContainer width="100%" height={140}>
                <BarChart data={flight}>
                  <XAxis dataKey="bin" tick={axisStyle} />
                  <YAxis tick={axisStyle} width={28} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Bar dataKey="count" fill="var(--amber-dim)" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartBlock>
          </div>

          <ChartBlock title="top 10 digraphs · avg ms between keys">
            <div className="space-y-1.5">
              {digraphs.map((d) => (
                <div key={d.pair} className="flex items-center gap-3">
                  <span className="font-mono-tight text-xs text-muted w-10 shrink-0">{d.pair}</span>
                  <div className="flex-1 h-3 bg-surface-2 rounded-sm overflow-hidden">
                    <div
                      className="h-full bg-amber rounded-sm"
                      style={{ width: `${(d.avg_ms / maxDigraphMs) * 100}%` }}
                    />
                  </div>
                  <span className="font-mono-tight text-xs text-muted w-12 text-right shrink-0">
                    {Math.round(d.avg_ms)}ms
                  </span>
                </div>
              ))}
              {digraphs.length === 0 && <p className="text-xs text-muted">not enough data</p>}
            </div>
          </ChartBlock>
        </Panel>

        {/* MOUSE PANEL */}
        <Panel title="mouse" accent="cyan">
          <StatRow
            stats={[
              { label: "avg error", value: `${Math.round(dot.avg_error_px)}px` },
              { label: "avg travel", value: `${Math.round(dot.avg_travel_ms)}ms` },
              { label: "avg velocity", value: `${Math.round(dot.avg_velocity_pxs)}px/s` },
              { label: "drag success", value: `${Math.round(drag.success_rate * 100)}%` },
            ]}
          />

          <div className="grid sm:grid-cols-2 gap-4">
            <ChartBlock title="click accuracy (error vs. travel time)">
              <ResponsiveContainer width="100%" height={180}>
                <ScatterChart>
                  <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
                  <XAxis dataKey="travel" name="travel ms" tick={axisStyle} unit="ms" />
                  <YAxis dataKey="error" name="error px" tick={axisStyle} unit="px" width={36} />
                  <ZAxis range={[40, 40]} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Scatter data={scatterData} fill="var(--cyan)" />
                </ScatterChart>
              </ResponsiveContainer>
            </ChartBlock>

            <ChartBlock title="travel time per target">
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={travelBars}>
                  <XAxis dataKey="trial" tick={axisStyle} />
                  <YAxis tick={axisStyle} width={32} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Bar dataKey="ms" fill="var(--cyan)" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartBlock>
          </div>

          <ChartBlock title="velocity profile across targets">
            <ResponsiveContainer width="100%" height={150}>
              <LineChart data={velocitySeries}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="trial" tick={axisStyle} />
                <YAxis tick={axisStyle} width={36} unit="px/s" />
                <Tooltip contentStyle={tooltipStyle} />
                <Line type="monotone" dataKey="v" stroke="var(--cyan)" strokeWidth={2} dot={{ r: 2 }} />
              </LineChart>
            </ResponsiveContainer>
          </ChartBlock>
        </Panel>

        <div className="flex flex-col items-center gap-3 mt-10 pb-6">
          <span className="text-xs text-muted font-mono-tight">session recorded</span>
          <button
            onClick={onFinish}
            className="font-mono-tight text-sm uppercase tracking-wider bg-text text-bg px-8 py-3 rounded-md hover:brightness-90 transition active:scale-[0.98]"
          >
            finish →
          </button>
        </div>
      </div>
    </div>
  );
}

const tooltipStyle = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  fontSize: 12,
  fontFamily: "var(--font-mono)",
  color: "var(--text)",
};

function Panel({ title, accent, children }: { title: string; accent: "amber" | "cyan"; children: React.ReactNode }) {
  return (
    <div className="mb-10">
      <div className="flex items-center gap-2 mb-4">
        <div className={`w-2 h-2 rounded-full ${accent === "amber" ? "bg-amber" : "bg-cyan"}`} />
        <h3 className="font-mono-tight text-sm uppercase tracking-widest text-text">{title}</h3>
      </div>
      <div className="bg-surface/60 border border-border rounded-xl p-5 space-y-5">{children}</div>
    </div>
  );
}

function ChartBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs text-muted font-mono-tight mb-2">{title}</div>
      {children}
    </div>
  );
}

function StatRow({ stats }: { stats: { label: string; value: string | number }[] }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {stats.map((s) => (
        <div key={s.label} className="bg-surface-2 rounded-lg px-3 py-2.5 text-center">
          <div className="font-mono-tight text-lg text-text">{s.value}</div>
          <div className="text-[10px] uppercase tracking-wider text-muted mt-0.5">{s.label}</div>
        </div>
      ))}
    </div>
  );
}
