/**
 * Normalizes requireAuth from environment (boolean or string e.g. envsubst / Docker).
 * The string "false" is truthy in JS — this treats it as disabled auth.
 */
export function parseAuthRequiredFlag(value: unknown): boolean {
  if (value === false) return false;
  if (value === true) return true;
  if (typeof value === 'string') {
    const s = value.trim().toLowerCase();
    if (s === 'false' || s === '0' || s === 'no' || s === 'off') return false;
    if (s === 'true' || s === '1' || s === 'yes' || s === 'on') return true;
  }
  return true;
}
