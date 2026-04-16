// app.ts — Parabola Lab main controller
import { drawParabola } from './graph.ts';
import { setupChallenge } from './challenge.ts';
import { setupLearn } from './rewrite.ts';
import { setupChat } from './chat.ts';
import { type Coeffs, toVertex, fmtStd, fmtVtx } from './math.ts';

const state: Coeffs = { a: 1, b: 0, c: 0 };
const canvas = document.getElementById('graph') as HTMLCanvasElement;
const eqStd = document.getElementById('eq-standard')!;
const eqVtx = document.getElementById('eq-vertex')!;
const slidersEl = document.getElementById('sliders')!;
const controlsEl = document.getElementById('controls')!;
const practiceEl = document.getElementById('practice-area')!;
const learnSection = document.getElementById('learn-section')!;
const learnEl = document.getElementById('learn-area')!;
const chatEl = document.getElementById('chat-area')!;
let mode: 'learn' | 'explore' | 'practice' = 'explore';

function render() {
  eqStd.textContent = fmtStd(state);
  const v = toVertex(state);
  eqVtx.textContent = fmtVtx(v);
  const ghost = mode === 'practice' ? challenge.target ?? undefined : undefined;
  drawParabola(canvas, state.a, state.b, state.c, ghost);
  challenge.onUpdate?.(state);
}

const defs: { key: keyof Coeffs; min: number; max: number; step: number }[] = [
  { key: 'a', min: -5, max: 5, step: 0.5 },
  { key: 'b', min: -10, max: 10, step: 1 },
  { key: 'c', min: -10, max: 10, step: 1 },
];
defs.forEach(d => {
  const g = document.createElement('div'); g.className = 'slider-group';
  const lbl = document.createElement('div'); lbl.className = 'slider-label';
  const name = document.createElement('span'); name.textContent = d.key;
  const val = document.createElement('span'); val.textContent = String(state[d.key]);
  lbl.append(name, val);
  const inp = document.createElement('input');
  Object.assign(inp, { type: 'range', min: d.min, max: d.max, step: d.step, value: state[d.key] });
  inp.addEventListener('input', () => {
    state[d.key] = parseFloat(inp.value); val.textContent = String(state[d.key]); render();
  });
  g.append(lbl, inp); slidersEl.appendChild(g);
});

// Tabs — explore / rewrite / practice
document.querySelectorAll('.tab').forEach(t => t.addEventListener('click', () => {
  document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
  t.classList.add('active');
  mode = (t as HTMLElement).dataset.tab as typeof mode;
  controlsEl.classList.toggle('hidden', mode === 'learn');
  practiceEl.classList.toggle('hidden', mode !== 'practice');
  learnSection.classList.toggle('hidden', mode !== 'learn');
  render();
}));

const challenge = setupChallenge(practiceEl, render);
setupLearn(learnEl, (c: Coeffs) => {
  state.a = c.a; state.b = c.b; state.c = c.c; render();
});
setupChat(chatEl);

window.addEventListener('resize', render);
render();