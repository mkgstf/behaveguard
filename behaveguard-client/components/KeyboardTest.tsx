"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { KeyEvent } from "@/lib/types";
import { normaliseKey } from "@/lib/keyUtils";
import rawDialogues from "@public/dialogues.json";

const PANGRAMS = [
  "the quick brown fox jumps over the lazy dog",
  "pack my box with five dozen liquor jugs",
  "how vexingly quick daft zebras jump",
  "the five boxing wizards jump quickly",
  "sphinx of black quartz judge my vow",
];

interface DialogueOption {
  movie: string;
  lang: "english" | "hinglish";
  line: string;
}

const DIALOGUES = rawDialogues as DialogueOption[];
const CONSECUTIVE_ERROR_THRESHOLD = 5;
const SYNC_PAUSE_MS = 1000;

export default function KeyboardTest({
  onComplete,
  segmentSeconds = 90,
}: {
  onComplete: (events: KeyEvent[], pangramLen: number, dialogueLen: number) => void;
  segmentSeconds?: number;
}) {
  const [segment, setSegment] = useState<"pangram" | "picker" | "dialogue">("pangram");
  const [secondsLeft, setSecondsLeft] = useState(segmentSeconds);
  const [typed, setTyped] = useState("");
  const [target, setTarget] = useState(PANGRAMS[0]);
  const [pangramIdx, setPangramIdx] = useState(0);
  const [dialogue, setDialogue] = useState<DialogueOption | null>(null);
  const [outOfSync, setOutOfSync] = useState(false);
  const eventsRef = useRef<KeyEvent[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const pangramCharsTyped = useRef(0);
  const dialogueCharsTyped = useRef(0);
  const pendingFinish = useRef(false);
  const shiftPressedAt = useRef<number | null>(null);

  const finishSegment = useCallback(() => {
    if (segment === "pangram") {
      setSegment("picker");
    } else if (segment === "dialogue") {
      onComplete(eventsRef.current, pangramCharsTyped.current, dialogueCharsTyped.current);
    }
  }, [segment, onComplete]);

  // run side effects (segment transitions) outside of the setState updater
  useEffect(() => {
    if (pendingFinish.current) {
      pendingFinish.current = false;
      finishSegment();
    }
  }, [secondsLeft, finishSegment]);

  useEffect(() => {
    inputRef.current?.focus();
  }, [segment]);

  // refocus only after the input is actually re-enabled in the DOM (disabled inputs ignore .focus())
  useEffect(() => {
    if (!outOfSync) inputRef.current?.focus();
  }, [outOfSync]);

  useEffect(() => {
    if (segment === "picker" || outOfSync) return; // timer paused while choosing a dialogue or re-syncing
    const t = setInterval(() => {
      setSecondsLeft((s) => {
        if (s <= 1) {
          clearInterval(t);
          pendingFinish.current = true;
          return 0;
        }
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(t);
  }, [segment, outOfSync]);

  function pickDialogue(d: DialogueOption) {
    setDialogue(d);
    setTarget(d.line);
    setTyped("");
    setSecondsLeft(segmentSeconds);
    setSegment("dialogue");
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    const ts = performance.now();
    if (e.key === "Shift") { shiftPressedAt.current = ts; return; }
    if (["Control", "Alt", "Meta", "CapsLock"].includes(e.key)) return;
    const { id, category } = normaliseKey(e.key);
    const shift_held = shiftPressedAt.current !== null;
    const shift_hold_ms = shift_held ? Math.round(ts - shiftPressedAt.current!) : 0;
    eventsRef.current.push({
      key_id: id,
      key_category: category,
      press_ts: ts,
      release_ts: null,
      segment: segment === "dialogue" ? "free" : "pangram",
      shift_held,
      shift_hold_ms,
    });
  }

  function handleKeyUp(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Shift") { shiftPressedAt.current = null; return; }
    if (["Control", "Alt", "Meta", "CapsLock"].includes(e.key)) return;
    const ts = performance.now();
    // attach release to the most recent open event for this key id
    const { id } = normaliseKey(e.key);
    for (let i = eventsRef.current.length - 1; i >= 0; i--) {
      const ev = eventsRef.current[i];
      if (ev.key_id === id && ev.release_ts === null) {
        ev.release_ts = ts;
        break;
      }
    }
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    if (outOfSync) return; // ignore input while paused for resync
    const val = e.target.value;
    if (segment === "pangram") {
      pangramCharsTyped.current += Math.max(0, val.length - typed.length);
      if (val.length >= target.length) {
        const next = (pangramIdx + 1) % PANGRAMS.length;
        setPangramIdx(next);
        setTarget(PANGRAMS[next]);
        setTyped("");
        return;
      }
    } else if (segment === "dialogue") {
      dialogueCharsTyped.current += Math.max(0, val.length - typed.length);
      if (val.length >= target.length) {
        setTyped("");
        return;
      }
    }

    // count consecutive mismatches trailing the cursor — a run of these means
    // the typed text has drifted out of alignment with the target line
    let consecutiveErrors = 0;
    for (let i = val.length - 1; i >= 0; i--) {
      if (val[i] !== target[i]) consecutiveErrors++;
      else break;
    }

    if (consecutiveErrors >= CONSECUTIVE_ERROR_THRESHOLD) {
      const correctPrefix = val.slice(0, val.length - consecutiveErrors);
      setTyped(val);
      setOutOfSync(true);
      setTimeout(() => {
        setTyped(correctPrefix);
        setOutOfSync(false);
      }, SYNC_PAUSE_MS);
      return;
    }

    setTyped(val);
  }

  const progressPct = (secondsLeft / segmentSeconds) * 100;

  if (segment === "picker") {
    return (
      <div className="flex-1 flex flex-col items-center justify-center px-6">
        <div className="max-w-xl w-full fade-up">
          <div className="font-mono-tight text-xs uppercase tracking-[0.3em] text-amber mb-3 text-center">
            segment 2 · pick a line to type
          </div>
          <h2 className="text-xl font-semibold mb-6 text-center">
            Choose a dialogue — you&apos;ll type it on repeat for {segmentSeconds} seconds
          </h2>
          <div className="grid sm:grid-cols-2 gap-3">
            {DIALOGUES.map((d) => (
              <button
                key={d.movie}
                onClick={() => pickDialogue(d)}
                className="text-left bg-surface border border-border rounded-lg p-4 hover:border-amber transition group"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="font-mono-tight text-sm text-text group-hover:text-amber transition">
                    {d.movie}
                  </span>
                  <span className="text-[10px] uppercase tracking-wider text-muted">
                    {d.lang}
                  </span>
                </div>
                <p className="text-xs text-muted leading-relaxed">&ldquo;{d.line.substring(0, 100)}...&rdquo;</p>
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6">
      <div className="max-w-2xl w-full fade-up">
        <div className="flex items-center justify-between mb-4">
          <span className="font-mono-tight text-xs uppercase tracking-[0.3em] text-amber">
            {segment === "pangram" ? "segment 1 · repeat the line" : `segment 2 · ${dialogue?.movie ?? ""}`}
          </span>
          <span className="font-mono-tight text-lg text-text tabular-nums">
            0:{secondsLeft.toString().padStart(2, "0")}
          </span>
        </div>

        <div className="h-1 w-full bg-border rounded-full mb-8 overflow-hidden">
          <div
            className="h-full bg-amber transition-all duration-1000 ease-linear"
            style={{ width: `${progressPct}%` }}
          />
        </div>

        <div className="relative">
          {outOfSync && (
            <div className="absolute inset-x-0 -top-2 flex justify-center z-10">
              <span className="font-mono-tight text-xs uppercase tracking-wider bg-danger/15 text-danger border border-danger/40 rounded-full px-4 py-1.5 fade-up">
                out of sync — pausing for a second…
              </span>
            </div>
          )}
          <div
            className={`font-mono-tight text-xl leading-relaxed mb-8 select-none transition-opacity ${
              outOfSync ? "opacity-40" : ""
            }`}
          >
            {target.split("").map((ch, i) => {
              const typedCh = typed[i];
              let cls = "text-muted";
              if (typedCh != null) cls = typedCh === ch ? "text-cyan" : "text-danger";
              if (i === typed.length) cls += " border-l-2 border-amber";
              return (
                <span key={i} className={cls}>
                  {ch}
                </span>
              );
            })}
          </div>
        </div>

        <input
          ref={inputRef}
          value={typed}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onKeyUp={handleKeyUp}
          disabled={outOfSync}
          className="absolute opacity-0 pointer-events-none"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
        />
        <div
          onClick={() => inputRef.current?.focus()}
          className="text-center text-xs text-muted font-mono-tight cursor-text"
        >
          click anywhere here and just start typing
        </div>
      </div>
    </div>
  );
}
