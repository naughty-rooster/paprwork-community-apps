// Lessons 1-7: Core concepts
import { type Coeffs } from './math.ts';
interface Lesson { title: string; emoji: string; body: string; graphs: (Coeffs & { label?: string })[]; }
export const lessonsBasic: Lesson[] = [
  { title: 'Meet the Parabola', emoji: '👋', graphs: [{ a: 1, b: 0, c: 0 }],
    body: '<p>A <b>parabola</b> is the U-shaped curve from a <b>quadratic function</b>.</p><p>The simplest:</p><div class="lesson-eq">y = x²</div><p>Every parabola has <b>standard form</b>:</p><div class="lesson-eq">y = ax² + bx + c</div><p><b>a</b>, <b>b</b>, <b>c</b> control shape &amp; position. Let\'s learn each one →</p>' },
  { title: 'The "a" Factor', emoji: '↕️',
    graphs: [{ a: 1, b: 0, c: 0, label: 'a=1' }, { a: -1, b: 0, c: 0, label: 'a=−1' }, { a: 3, b: 0, c: 0, label: 'a=3 (narrow)' }, { a: 0.5, b: 0, c: 0, label: 'a=0.5 (wide)' }],
    body: '<p><b>a</b> controls two things:</p><p>📐 <b>Direction:</b> a&gt;0 → opens <b>up</b> 😊 &nbsp; a&lt;0 → opens <b>down</b> 😞</p><p>📏 <b>Width:</b> bigger |a| = narrower &nbsp; smaller |a| = wider</p><p>⚠️ a can never be 0 (that\'s a line, not a parabola)</p><p class="try-label">👆 Tap examples below to see each on the graph</p>' },
  { title: 'The "c" Constant', emoji: '⬆️',
    graphs: [{ a: 1, b: 0, c: 0, label: 'c=0' }, { a: 1, b: 0, c: 3, label: 'c=3' }, { a: 1, b: 0, c: -2, label: 'c=−2' }],
    body: '<p><b>c</b> slides the parabola <b>up or down</b>.</p><p>It\'s the <b>y-intercept</b> — where the curve crosses the y-axis:</p><div class="lesson-eq">x=0 → y = a(0)²+b(0)+c = c</div><p>c=3 → crosses at (0,3). Simple!</p><p class="try-label">👆 Tap below to see c shift the curve</p>' },
  { title: 'The "b" Coefficient', emoji: '↔️',
    graphs: [{ a: 1, b: 0, c: 0, label: 'b=0' }, { a: 1, b: -4, c: 0, label: 'b=−4' }, { a: 1, b: 4, c: 0, label: 'b=4' }],
    body: '<p><b>b</b> shifts the <b>vertex</b> (turning point) left/right.</p><div class="lesson-eq">vertex x = −b / (2a)</div><p>Negative b → vertex moves <b>right</b>. Positive → <b>left</b>. (Opposite!)</p><p class="try-label">👆 Tap below to see b move the vertex</p>' },
  { title: 'Vertex Form', emoji: '📍',
    graphs: [{ a: 1, b: -4, c: 3, label: 'y=x²−4x+3' }, { a: 2, b: -4, c: -1, label: 'y=2(x−1)²−3' }],
    body: '<p>Another way to write it — <b>vertex form</b>:</p><div class="lesson-eq">y = a(x − h)² + k</div><p>The vertex is at <b>(h, k)</b> — read it directly!</p><p><b>a</b> = direction &amp; width &nbsp; <b>h</b> = vertex x &nbsp; <b>k</b> = vertex y</p><p>Both forms = <b>same curve</b>, different notation.</p>' },
  { title: 'Standard → Vertex', emoji: '🔄',
    graphs: [{ a: 1, b: -6, c: 5, label: 'y=x²−6x+5' }],
    body: '<p>Let\'s convert <b>standard → vertex</b>. 2 calculations!</p><div class="lesson-eq">y = x² − 6x + 5</div><p><b>Step 1: Find h</b> → <b>h = −b ÷ (2×a)</b></p><div class="steps-box"><div class="step">b=−6, a=1 → h = 6÷2 = <code>3</code></div></div><p><b>Step 2: Find k</b> — plug h back in!</p><div class="steps-box"><div class="step">(3)²−6(3)+5 = 9−18+5 = <code>−4</code></div></div><p><b>Write it:</b> a=1, h=3, k=−4</p><div class="steps-box"><div class="step"><code>y = (x−3)² − 4</code> ✓</div></div><p>Vertex at <b>(3,−4)</b> — see it on the graph! 📍</p>' },
  { title: 'Vertex → Standard', emoji: '🔁',
    graphs: [{ a: 1, b: -6, c: 8, label: 'y=(x−3)²−1' }],
    body: '<p>Go backwards — unwrap the gift 🎁</p><div class="lesson-eq">y = (x − 3)² − 1</div><p><b>Step 1: FOIL</b> (x−3)²:</p><div class="steps-box"><div class="step">x·x=x², x·(−3)=−3x, (−3)·x=−3x, (−3)·(−3)=9</div><div class="step">= <code>x² − 6x + 9</code></div></div><p><b>Step 2:</b> Add k (−1):</p><div class="steps-box"><div class="step">x²−6x+9−1 = <code>x²−6x+8</code></div></div><p>🎉 <b>y = x²−6x+8</b></p><p><b>Recipe:</b> 1️⃣ FOIL (x−h)² 2️⃣ Multiply by a 3️⃣ Add k</p>' },
];
