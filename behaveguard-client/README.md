# BehaveGuard

A short, monkeytype-styled typing + mouse test that records keystroke and
cursor dynamics for behavioral biometrics research, with a real consent step
before anything is recorded.

Flow: landing → **consent** → name → keyboard test (pangram + free typing) →
mouse test (target-follow + drag) → analytics dashboard → silent submit →
thank you.

## Run locally

```bash
npm install
npm run dev
```

The integrated backend runs from the parent directory:

```bash
uv sync --extra dev
uv run behaveguard import-xlsx Behaveguard-client.xlsx
uv run behaveguard serve --reload
```

The frontend uses `http://127.0.0.1:8000/api/v1` by default. Override it with
`NEXT_PUBLIC_API_URL` when deploying elsewhere.

## Connect it to a Google Sheet

1. Create a Google Sheet with two tabs: `Sessions` and `RawData`.
2. In the Sheet, go to **Extensions → Apps Script** and paste:

```js
function doPost(e) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sessions = ss.getSheetByName("Sessions");
  const raw = ss.getSheetByName("RawData");
  const data = JSON.parse(e.postData.contents);

  sessions.appendRow([
    data.subject_id,
    data.collected_at,
    data.keyboard.events.length,
    data.mouse.passive_points.length,
    data.mouse.dot_trials.length,
    data.duration_ms,
  ]);

  raw.appendRow([data.subject_id, data.collected_at, JSON.stringify(data)]);

  return ContentService.createTextOutput("ok");
}
```

3. **Deploy → New deployment → Web app**. Set "Who has access" to **Anyone**,
   deploy, and copy the web app URL.
4. Set it as an environment variable before building/deploying the site:

```bash
NEXT_PUBLIC_SHEETS_ENDPOINT="https://script.google.com/macros/s/XXXX/exec"
```

On Vercel/Netlify, add this in the project's environment variables. Locally,
put it in a `.env.local` file.

## Deploy

This is a standard Next.js app — deploy it on **Vercel** (recommended,
zero-config: `vercel deploy`) or any host that supports Next.js. Static
GitHub Pages hosting won't work as-is because this isn't a single static
HTML file; if you specifically need GitHub Pages, the app would need to be
exported as a static site (`next export`) — ask if you want that version.

## Data collected

- **Keyboard**: press/release timestamps, normalised key id (no text
  content), category (alphanum/symbol/special/space), per pangram + free
  typing segments.
- **Mouse (passive)**: cursor position sampled the whole session, throttled
  to ~5px or 16ms.
- **Mouse (target task)**: target position, click position, timestamps,
  travel time, click error, full path between targets.
- **Mouse (drag task)**: start/end position, full drag path, duration,
  success.

Every session is gated behind an explicit consent screen describing exactly
this list before any recording starts.
