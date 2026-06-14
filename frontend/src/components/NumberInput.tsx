import { useCallback } from 'react';

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
}

/**
 * Number input that:
 * 1. Prevents scroll wheel from changing values
 * 2. Displays numbers without trailing zeros or scientific notation
 * 3. Uses proper NaN-safe parsing (never coerces falsy values)
 */
export default function NumberInput({ value, onChange, min, max, className, ...props }: NumberInputProps) {
  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const raw = e.target.value;
      // Allow empty input (becomes null)
      if (raw === '' || raw.trim() === '') {
        onChange(null);
        return;
      }
      const num = parseFloat(raw);
      if (isNaN(num)) return; // ignore non-numeric input, keep previous value
      // Clamp to min/max
      let clamped = num;
      if (min !== undefined && clamped < min) clamped = min;
      if (max !== undefined && clamped > max) clamped = max;
      onChange(clamped);
    },
    [onChange, min, max],
  );

  // Prevent scroll wheel from changing the value
  const handleWheel = useCallback((e: React.WheelEvent<HTMLInputElement>) => {
    (e.currentTarget as HTMLInputElement).blur();
  }, []);

  return (
    <input
      type="number"
      value={fmtNumber(value)}
      onChange={handleChange}
      onWheel={handleWheel}
      min={min}
      max={max}
      className={`w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all ${className || ''}`}
      {...props}
    />
  );
}
