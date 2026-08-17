/**
 * Integer money math. ServiceMinder rates carry up to 3 decimals (e.g. $96.485),
 * so rates are held as integer milli-dollars (1/1000 USD) and charged amounts as
 * integer cents. Rounding is half-up and happens ONLY at the documented points in
 * the engine — never inside intermediate arithmetic.
 */

/** Dollars (SM JSON number, ≤3 decimals) → integer milli-dollars. */
export function dollarsToMilli(dollars: number): number {
  if (!Number.isFinite(dollars)) {
    throw new Error(`Invalid dollar amount: ${dollars}`);
  }
  return Math.round(dollars * 1000);
}

/** Integer milli-dollars → integer cents, half-up. */
export function milliToCents(milli: number): number {
  const q = Math.floor(milli / 10);
  const r = milli - q * 10;
  return r >= 5 ? q + 1 : q;
}

/** (value × num / den) on integers, rounded half-up. Used for percentages. */
export function mulDivHalfUp(value: number, num: number, den: number): number {
  const product = value * num;
  const q = Math.floor(product / den);
  const r = product - q * den;
  return 2 * r >= den ? q + 1 : q;
}

/** Integer cents → "$1,234.56" for logs/tests. */
export function formatCents(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  const dollars = Math.floor(abs / 100).toLocaleString("en-US");
  return `${sign}$${dollars}.${String(abs % 100).padStart(2, "0")}`;
}
