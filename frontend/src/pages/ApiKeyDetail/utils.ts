export function fmtNum(n: number): string {
  if (n >= 1_000_000_000) return (n / 1_000_000_000).toFixed(1) + 'B';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return n.toLocaleString();
}

/** Format a per-1M-token price like $3.00/1M — strips trailing zeros beyond 2 decimal places. */
export function fmtPrice(n: number | null | undefined): string {
  const v = Number(n) || 0;
  // Remove floating-point noise (e.g. 3.0000000000 → "3")
  return parseFloat(v.toFixed(6)).toString();
}

export function fmtCost(n: number | null | undefined): string {
  const v = Number(n) || 0;
  if (v >= 1000) return '$' + (v / 1000).toFixed(1) + 'K';
  if (v >= 1) return '$' + v.toFixed(2);
  if (v >= 0.01) return '$' + v.toFixed(3);
  if (v > 0) return '$' + v.toFixed(4);
  return '$0.00';
}

export function fmtDate(s: string | null): string {
  if (!s) return '-';
  const d = s.includes('T') && !s.endsWith('Z') && !s.includes('+') ? s + 'Z' : s;
  return new Date(d).toLocaleString('zh-CN');
}

export const PIE_COLORS = [
  '#6366f1', '#06b6d4', '#f59e0b', '#ef4444', '#10b981',
  '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#3b82f6',
];

export const BUDGET_COLORS = ['#6366f1', '#06b6d4', '#f59e0b', '#10b981', '#8b5cf6', '#ec4899', '#f97316', '#3b82f6'];