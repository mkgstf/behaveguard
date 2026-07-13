export function normaliseKey(key: string): { id: string; category: "alphanum" | "symbol" | "special" | "space" } {
  if (key === " ") return { id: "space", category: "space" };
  if (key.length === 1) {
    if (/[a-zA-Z0-9]/.test(key)) return { id: key.toLowerCase(), category: "alphanum" };
    return { id: "symbol", category: "symbol" };
  }
  // special keys: Backspace, Shift, Enter, Tab, Arrow*, etc — bucket, never log content
  const specials: Record<string, string> = {
    Backspace: "backspace",
    Shift: "shift",
    Enter: "enter",
    Tab: "tab",
    CapsLock: "capslock",
    Control: "ctrl",
    Alt: "alt",
    Meta: "meta",
  };
  return { id: specials[key] ?? "other", category: "special" };
}
