import { useCallback, useEffect, useState } from 'react';

/**
 * Format a number for display: strip trailing zeros, avoid scientific notation.
 * Returns empty string for null/undefined.
 */
export function fmtNumber(v: number | null | undefined): string {
  if (v == null || v === undefined) return '';
  // Coerce string values (from JSON) to number
  const n = typeof v === 'number' ? v : Number(v);
  if (isNaN(n)) return '';
  // Avoid scientific notation for very small numbers
  if (Math.abs(n) < 1e-10 && n !== 0) return '0';
  // Use toFixed to cap precision at 10 decimal places, then strip trailing zeros
  const fixed = n.toFixed(10);
  // Remove trailing zeros after decimal point
  const trimmed = fixed.replace(/\.?0+$/, '');
  return trimmed;
}

interface NumberInputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type' | 'onChange' | 'value'> {
  value: number | null | undefined;
  onChange: (value: number | null) => void;
  /** Minimum allowed value */
  min?: number;
  /** Maximum allowed value */
  max?: number;
  /** Parse input as an integer (for integer-only fields). */
  integer?: boolean;
}

/**
 * Number input that:
 * 1. Prevents scroll wheel from changing values
 * 2. Displays numbers without trailing zeros or scientific notation
 * 3. Uses proper NaN-safe parsing (never coerces falsy values)
 * 4. Keeps the raw string while the user is typing, so intermediate states
 *    like "0." or "0.02" are not clobbered by re-formatting on every keystroke
 *    — this is what makes fractional prices (e.g. 0.023) typeable.
 */
export default function NumberInput({ value, onChange, min, max, integer, className, ...props }: NumberInputProps) {
  // Draft holds the raw input while the user edits. Deriving the display
  // straight from `value` on every keystroke would drop the trailing decimal
  // point (parseFloat("0.") === 0), making values like 0.023 impossible to type.
  const [draft, setDraft] = useState<string | null>(null);

  // Drop the draft whenever the prop value changes externally (load, reset,
  // clamp). Keystrokes that resolve to the same number (e.g. "0." while the
  // value is already 0) leave the draft untouched.
  useEffect(() => {
    setDraft(null);
  }, [value]);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const raw = e.target.value;
      setDraft(raw);
      // Allow empty input (becomes null)
      if (raw === '' || raw.trim() === '') {
        onChange(null);
        return;
      }
      const num = integer ? parseInt(raw, 10) : parseFloat(raw);
      if (isNaN(num)) return; // ignore non-numeric input, keep previous value
      // Clamp to min/max
      let clamped = num;
      if (min !== undefined && clamped < min) clamped = min;
      if (max !== undefined && clamped > max) clamped = max;
      onChange(clamped);
    },
    [onChange, min, max, integer],
  );

  // Prevent scroll wheel from changing the value
  const handleWheel = useCallback((e: React.WheelEvent<HTMLInputElement>) => {
    (e.currentTarget as HTMLInputElement).blur();
  }, []);

  // On blur, fall back to the formatted value (e.g. "0." settles to "0")
  const handleBlur = useCallback(() => {
    setDraft(null);
  }, []);

  return (
    <input
      type="number"
      value={draft ?? fmtNumber(value)}
      onChange={handleChange}
      onBlur={handleBlur}
      onWheel={handleWheel}
      min={min}
      max={max}
      className={className ?? 'w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all'}
      {...props}
    />
  );
}
