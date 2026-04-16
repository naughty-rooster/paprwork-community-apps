// math.ts — Conversion utilities for standard ↔ vertex form
export interface Coeffs { a: number; b: number; c: number }
export interface VForm { a: number; h: number; k: number }

export const r2 = (n: number) => Math.round(n * 100) / 100;
export const ri = (lo: number, hi: number) => Math.round(Math.random() * (hi - lo) + lo);

export function toVertex(s: Coeffs): VForm {
  const h = r2(-s.b / (2 * s.a));
  const k = r2(s.c - (s.b * s.b) / (4 * s.a));
  return { a: s.a, h, k };
}

export function toStandard(v: VForm): Coeffs {
  return { a: v.a, b: r2(-2 * v.a * v.h), c: r2(v.a * v.h * v.h + v.k) };
}

export function fmtStd(c: Coeffs): string {
  let s = '';
  if (c.a === 1) s = 'x²'; else if (c.a === -1) s = '−x²'; else s = c.a + 'x²';
  if (c.b > 0) s += ' + ' + (c.b === 1 ? '' : c.b) + 'x';
  else if (c.b < 0) s += ' − ' + (c.b === -1 ? '' : Math.abs(c.b)) + 'x';
  if (c.c > 0) s += ' + ' + c.c;
  else if (c.c < 0) s += ' − ' + Math.abs(c.c);
  return 'y = ' + (s || '0');
}

export function fmtVtx(v: VForm): string {
  const a = v.a === 1 ? '' : v.a === -1 ? '−' : v.a + '';
  const h = v.h === 0 ? 'x' : v.h > 0 ? '(x − ' + v.h + ')' : '(x + ' + Math.abs(v.h) + ')';
  let s = a + h + '²';
  if (v.k > 0) s += ' + ' + v.k;
  else if (v.k < 0) s += ' − ' + Math.abs(v.k);
  return 'y = ' + s;
}
