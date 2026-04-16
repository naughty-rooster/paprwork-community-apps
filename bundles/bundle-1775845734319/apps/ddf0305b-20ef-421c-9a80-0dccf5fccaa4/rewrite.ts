// learn.ts — Guided lesson cards with visual examples
import { type Coeffs, fmtStd, fmtVtx, toVertex } from './math.ts';
import { lessonsBasic } from './lessons-basic.ts';
import { lessonsGraph } from './lessons-graph.ts';

interface Lesson { title: string; emoji: string; body: string; graphs: (Coeffs & { label?: string })[]; }
export type { Lesson };
const L: Lesson[] = [...lessonsBasic, ...lessonsGraph];

export function setupLearn(el: HTMLElement, onGraph: (c: Coeffs) => void) {
  let idx = 0;
  function render() {
    const ls = L[idx], g = ls.graphs;
    el.innerHTML = '<div class="lesson-hdr"><span class="lesson-num">' + (idx + 1) + '/' + L.length +
      '</span><span class="lesson-emoji">' + ls.emoji + '</span><h2 class="lesson-title">' +
      ls.title + '</h2></div><div class="lesson-body">' + ls.body + '</div>' +
      (g.length > 1 ? '<div class="lesson-examples">' + g.map((e, i) =>
        '<button class="btn btn-ghost example-btn' + (i === 0 ? ' active' : '') + '" data-i="' + i + '">' +
        (e.label || fmtStd(e)) + '</button>').join('') + '</div>' : '') +
      '<div class="lesson-nav">' +
      (idx > 0 ? '<button class="btn btn-ghost" id="ln-prev">← Back</button>' : '<span></span>') +
      (idx < L.length - 1 ? '<button class="btn btn-primary" id="ln-next">Next →</button>' :
        '<button class="btn btn-primary" id="ln-next">🎯 Go Explore!</button>') + '</div>' +
      '<div class="lesson-dots">' + L.map((_, i) =>
        '<span class="dot' + (i === idx ? ' active' : '') + '"></span>').join('') + '</div>';
    onGraph(g[0]);
    el.querySelectorAll('.example-btn').forEach(b => b.addEventListener('click', () => {
      el.querySelectorAll('.example-btn').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      onGraph(g[parseInt((b as HTMLElement).dataset.i!)]);
    }));
    el.querySelector('#ln-prev')?.addEventListener('click', () => { idx--; render(); });
    el.querySelector('#ln-next')?.addEventListener('click', () => {
      if (idx < L.length - 1) { idx++; render(); }
      else { (document.querySelector('[data-tab="explore"]') as HTMLElement)?.click(); }
    });
  }
  render();
}
