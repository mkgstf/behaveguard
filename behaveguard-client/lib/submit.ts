import { SessionData } from "./types";

// Set this to your deployed Google Apps Script Web App URL.
// See README.md for the script to paste into Apps Script and how to deploy it.
export const SUBMIT_URL = process.env.NEXT_PUBLIC_SHEETS_ENDPOINT || "";

export async function submitSession(data: SessionData): Promise<boolean> {
  if (!SUBMIT_URL) {
    console.warn("NEXT_PUBLIC_SHEETS_ENDPOINT is not set — skipping submit.");
    return false;
  }
  try {
    // Apps Script web apps don't send CORS headers back for normal fetch reads,
    // so we fire-and-forget with no-cors. The script still receives and logs the POST.
    await fetch(SUBMIT_URL, {
      method: "POST",
      mode: "no-cors",
      headers: { "Content-Type": "text/plain" },
      body: JSON.stringify(data),
    });
    return true;
  } catch (err) {
    console.error("Submit failed", err);
    return false;
  }
}
