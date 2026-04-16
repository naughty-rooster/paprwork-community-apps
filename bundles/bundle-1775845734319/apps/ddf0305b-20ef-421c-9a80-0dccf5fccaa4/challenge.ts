// challenge.ts — Practice mode: match the target parabola
import { type Coeffs, fmtStd } from './math.ts';
export type { Coeffs };
export interface ChallengeState {
  target: Coeffs | null;
  onUpdate: ((user: Coeffs) => void) | null;
}

const rand = (lo: number, hi: number) => Math.round((Math.random() * (hi - lo) + lo) * 2) / 2;
const genTarget = (): Coeffs => ({ a: rand(-3, 3) || 1, b: Math.round(rand(-4, 4)), c: Math.round(rand(-4, 4)) });

export function setupChallenge(el: HTMLElement, rerender: () => void): ChallengeState {
  let streak = 0, total = 0;
  const state: ChallengeState = { target: null, onUpdate: null };

  el.innerHTML = `
    <div class="practice-prompt" id="prompt">Tap <b>New Challenge</b> to start!<br>Match the <span style="color:var(--red)">red dashed</span> curve using the sliders.</div>
    <div class="feedback" id="fb" style="display:none"></div>
    <div class="score-bar"><span class="label">Score</span><span class="val" id="score">0 / 0</span></div>
    <div class="practice-btns">
      <button class="btn btn-sm-pill" id="newBtn">🎯 New Challenge</button>
      <button class="btn btn-sm-ghost hidden" id="hintBtn">💡 Hint</button>
    </div>`;

  const fb = el.querySelector('#fb') as HTMLElement;
  const scoreEl = el.querySelector('#score') as HTMLElement;
  const prompt = el.querySelector('#prompt') as HTMLElement;
  const newBtn = el.querySelector('#newBtn') as HTMLElement;
  const hintBtn = el.querySelector('#hintBtn') as HTMLElement;

  function start() {
    state.target = genTarget();
    fb.style.display = 'none';
    hintBtn.classList.remove('hidden');
    newBtn.textContent = '⏭ Skip';
    prompt.innerHTML = `Match this parabola!<strong style="color:var(--red)">y = ${fmt(state.target)}</strong>`;
    rerender();
  }

  state.onUpdate = (user: Coeffs) => {
    if (!state.target) return;
    const d = Math.abs(user.a - state.target.a) + Math.abs(user.b - state.target.b) + Math.abs(user.c - state.target.c);
    fb.style.display = 'block';
    if (d === 0) {
      streak++; total++;
      fb.className = 'feedback perfect'; fb.textContent = `✨ Perfect! ${streak} in a row!`;
      scoreEl.textContent = `${total} solved`;
      hintBtn.classList.add('hidden'); newBtn.textContent = '🎯 Next';
      state.target = null;
    } else if (d <= 1.5) {
      fb.className = 'feedback close'; fb.textContent = '🔥 Almost there!';
    } else {
      fb.className = 'feedback off'; fb.textContent = 'Keep adjusting the sliders';
    }
  };

  newBtn.addEventListener('click', () => { if (state.target) { streak = 0; } start(); });
  hintBtn.addEventListener('click', () => {
    if (!state.target) return;
    const t = state.target;
    const hints = [
      t.a > 0 ? 'Opens upward (a > 0)' : 'Opens downward (a < 0)',
      `y-intercept is ${t.c}`, `Vertex near x = ${(-t.b / (2 * t.a)).toFixed(1)}`
    ];
    fb.style.display = 'block'; fb.className = 'feedback close';
    fb.textContent = '💡 ' + hints[Math.floor(Math.random() * 3)];
  });
  return state;
}

const fmt = fmtStd;