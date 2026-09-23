// Synchronous saves close the gap between an input event and leaving the page.
// The memory copy also protects in-app navigation when browser storage is full.
const memory = new Map();
const unsaved = new Set();
export const storageIsUnsaved = key => unsaved.has(key);
export function readSaved(key, fallback) {
  const defaultValue = () => typeof fallback === 'function' ? fallback() : fallback;
  if (unsaved.has(key)) return memory.has(key) ? memory.get(key) : defaultValue();
  try {
    const raw = localStorage.getItem(key);
    if (raw) { const value = JSON.parse(raw); if (value && typeof value === 'object' && !Array.isArray(value)) return value; }
  } catch { /* Use the current session's copy below. */ }
  return memory.has(key) ? memory.get(key) : defaultValue();
}
export function saveLocal(key, value) {
  memory.set(key, value);
  try { localStorage.setItem(key, JSON.stringify(value)); unsaved.delete(key); return true; }
  catch { unsaved.add(key); return false; }
}
export function clearSaved(key) {
  memory.delete(key);
  try { localStorage.removeItem(key); unsaved.delete(key); }
  catch { unsaved.add(key); }
}
