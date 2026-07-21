// Approximate global typing-speed percentile bands, hardcoded from
// commonly-published typing-test aggregate statistics (the kind of figures
// widely cited by typing-test sites: an average adult typist is ~40 WPM,
// touch typists average ~50-70 WPM, and speeds much past ~100 WPM are rare).
// This is a rough public benchmark for giving a WPM number meaning to a
// layperson — not a precise scientific population study, and not the same
// as this app's own internal profile-rank (which compares only against
// profiles actually enrolled here).
const WPM_PERCENTILE_BANDS: [wpm: number, percentile: number][] = [
  [0, 1],
  [10, 5],
  [20, 15],
  [30, 35],
  [40, 55],
  [50, 70],
  [60, 80],
  [70, 88],
  [80, 93],
  [90, 96],
  [100, 98],
  [120, 99],
  [150, 99.7],
];

/** Returns an approximate 0-100 percentile for a given WPM against global
 * typing-test benchmarks, via linear interpolation between the hardcoded
 * bands above. Clamped to the table's range at both ends. */
export function globalTypingPercentile(wpm: number): number {
  if (wpm <= WPM_PERCENTILE_BANDS[0][0]) return WPM_PERCENTILE_BANDS[0][1];
  const last = WPM_PERCENTILE_BANDS[WPM_PERCENTILE_BANDS.length - 1];
  if (wpm >= last[0]) return last[1];
  for (let i = 1; i < WPM_PERCENTILE_BANDS.length; i++) {
    const [hiWpm, hiPct] = WPM_PERCENTILE_BANDS[i];
    if (wpm <= hiWpm) {
      const [loWpm, loPct] = WPM_PERCENTILE_BANDS[i - 1];
      const t = (wpm - loWpm) / (hiWpm - loWpm);
      return Math.round((loPct + t * (hiPct - loPct)) * 10) / 10;
    }
  }
  return last[1];
}

export const AVERAGE_TYPIST_WPM = 40;
