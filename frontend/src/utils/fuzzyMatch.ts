/** Normalize for fuzzy matching: lowercase, drop non-alphanumerics so
 *  "gpt-4" and "gpt4" compare equal. */
const normalize = (s: string): string => s.toLowerCase().replace(/[^a-z0-9]/g, '');

/** Token-based fuzzy match.
 *
 *  Splits `query` on whitespace into tokens, and returns true only when EVERY
 *  token matches at least one of the candidate `haystacks` as a substring of
 *  the normalized form. Empty query → match all.
 *
 *  Examples (with haystacks = ["gpt-4o", "openai"]):
 *    "gpt 4o"      → true  (each token hits gpt-4o)
 *    "openai mini" → false (mini doesn't appear anywhere)
 *    ""            → true
 */
export function fuzzyMatchTokens(
  query: string,
  haystacks: Array<string | null | undefined>,
): boolean {
  const q = query.trim();
  if (!q) return true;
  const normalizedHaystacks = haystacks
    .filter((s): s is string => !!s)
    .map(normalize);
  if (normalizedHaystacks.length === 0) return false;
  const tokens = q.split(/\s+/).map(normalize).filter(Boolean);
  if (tokens.length === 0) return true;
  return tokens.every(t => normalizedHaystacks.some(h => h.includes(t)));
}
