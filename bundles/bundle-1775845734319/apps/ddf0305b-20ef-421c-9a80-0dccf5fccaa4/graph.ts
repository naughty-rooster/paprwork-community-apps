// graph.ts — Parabola renderer on canvas
const GRID_COLOR = 'rgba(100,112,133,0.15)';
const AXIS_COLOR = 'rgba(100,112,133,0.4)';

export function drawParabola(
  canvas: HTMLCanvasElement,
  a: number, b: number, c: number,
  ghost?: { a: number; b: number; c: number }
) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext('2d')!;
  ctx.scale(dpr, dpr);
  const W = rect.width, H = rect.height;
  const cx = W / 2, cy = H / 2;
  const range = 10;
  const scale = Math.min(W, H) / (range * 2 + 2);

  ctx.strokeStyle = GRID_COLOR; ctx.lineWidth = 0.5;
  for (let i = -20; i <= 20; i++) {
    const x = cx + i * scale, y = cy - i * scale;
    if (x > 0 && x < W) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
    if (y > 0 && y < H) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
  }
  ctx.strokeStyle = AXIS_COLOR; ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.moveTo(0, cy); ctx.lineTo(W, cy); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(cx, 0); ctx.lineTo(cx, H); ctx.stroke();
  ctx.strokeStyle = 'rgba(80,80,100,0.4)'; ctx.lineWidth = 1;
  for (let i = -range; i <= range; i++) {
    if (i === 0) continue;
    const x = cx + i * scale, y = cy - i * scale;
    ctx.beginPath(); ctx.moveTo(x, cy - 4); ctx.lineTo(x, cy + 4); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(cx - 4, y); ctx.lineTo(cx + 4, y); ctx.stroke();
  }

  ctx.fillStyle = 'rgba(80,80,100,0.7)'; ctx.font = 'bold 12px system-ui'; ctx.textAlign = 'center';
  for (let i = -range; i <= range; i++) {
    if (i === 0) continue;
    const x = cx + i * scale;
    ctx.fillText(String(i), x, cy + 16);
    const y = cy - i * scale;
    ctx.textAlign = 'right';
    ctx.fillText(String(i), cx - 8, y + 4);
    ctx.textAlign = 'center';
  }
  ctx.fillStyle = 'rgba(80,80,100,0.5)'; ctx.font = 'bold 11px system-ui';
  ctx.fillText('0', cx - 8, cy + 16);

  if (ghost) drawCurve(ctx, cx, cy, scale, W, ghost.a, ghost.b, ghost.c, 'rgba(239,68,68,0.3)', 3, [8, 6]);
  drawCurve(ctx, cx, cy, scale, W, a, b, c, '#e91e8a', 2.5);

  const vx = -b / (2 * (a || 0.001));
  const vy = a * vx * vx + b * vx + c;
  const px = cx + vx * scale, py = cy - vy * scale;
  if (px > 0 && px < W && py > 0 && py < H) {
    ctx.fillStyle = 'rgba(233,30,138,0.15)';
    ctx.beginPath(); ctx.arc(px, py, 12, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#e91e8a';
    ctx.beginPath(); ctx.arc(px, py, 5, 0, Math.PI * 2); ctx.fill();
    ctx.font = 'bold 12px system-ui'; ctx.fillStyle = '#e91e8a'; ctx.textAlign = 'left';
    const lbl = `(${vx.toFixed(1)}, ${vy.toFixed(1)})`;
    ctx.fillText(lbl, px + 10, py - 8);
  }
}

function drawCurve(
  ctx: CanvasRenderingContext2D, cx: number, cy: number, scale: number,
  W: number, a: number, b: number, c: number,
  color: string, lineW: number, dash?: number[]
) {
  ctx.strokeStyle = color; ctx.lineWidth = lineW; ctx.setLineDash(dash || []);
  ctx.beginPath();
  let started = false;
  for (let px = 0; px < W; px++) {
    const x = (px - cx) / scale, y = a * x * x + b * x + c, py = cy - y * scale;
    if (!started) { ctx.moveTo(px, py); started = true; } else ctx.lineTo(px, py);
  }
  ctx.stroke(); ctx.setLineDash([]);
}
