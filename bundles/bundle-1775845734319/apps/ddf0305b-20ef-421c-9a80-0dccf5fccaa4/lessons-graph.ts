// Lessons 8-11: Reading a graph → writing equations
import { type Coeffs } from './math.ts';
interface Lesson { title: string; emoji: string; body: string; graphs: (Coeffs & { label?: string })[]; }
export const lessonsGraph: Lesson[] = [
  { title: 'Reading a Graph: Find the Vertex', emoji: '🔍',
    graphs: [{ a: 1, b: -4, c: 1, label: 'Find the vertex!' },
      { a: -1, b: 2, c: 3, label: 'Opens down ∩' },
      { a: 1, b: 6, c: 5, label: 'Left side' }],
    body: '<p>You see a parabola on a graph. <b>First job: find the vertex!</b></p>' +
      '<p>The vertex is the <b>lowest point</b> (opens up ∪) or <b>highest point</b> (opens down ∩).</p>' +
      '<div class="steps-box"><div class="step">👀 Look — where does the curve turn around?</div>' +
      '<div class="step">📍 Read the <b>x</b> (left-right position)</div>' +
      '<div class="step">📍 Read the <b>y</b> (up-down position)</div>' +
      '<div class="step">That\'s your vertex = <code>(h, k)</code></div></div>' +
      '<p><b>Example:</b> The curve above turns at x=<b>2</b>, y=<b>−3</b></p>' +
      '<p>Vertex = <b>(2, −3)</b> → h=2, k=−3. That\'s it!</p>' +
      '<p class="try-label">👆 Tap examples — spot each vertex on the graph!</p>' },
  { title: 'Reading a Graph: Find "a"', emoji: '🔎',
    graphs: [{ a: 1, b: -4, c: 3, label: 'a = 1' },
      { a: 2, b: -8, c: 7, label: 'a = 2 (narrow)' },
      { a: -1, b: 4, c: -3, label: 'a = −1 (flipped)' }],
    body: '<p>You found the vertex — now find <b>"a"</b>. Here\'s the trick:</p>' +
      '<p><b>Pick any other point on the curve</b>, then plug in!</p>' +
      '<div class="steps-box"><div class="step">1️⃣ You know the vertex: <code>(h, k)</code></div>' +
      '<div class="step">2️⃣ Pick another point on the curve: <code>(x, y)</code></div>' +
      '<div class="step">3️⃣ Plug into: <code>y = a(x − h)² + k</code></div>' +
      '<div class="step">4️⃣ Solve for a!</div></div>' +
      '<p><b>Example:</b> Vertex = (2, −1). Another point = (3, 0).</p>' +
      '<div class="steps-box"><div class="step">0 = a(3 − 2)² + (−1)</div>' +
      '<div class="step">0 = a(1) − 1</div>' +
      '<div class="step"><code>a = 1</code> ✓</div></div>' +
      '<p><b>Shortcut:</b> 1 unit from h? Then a = y − k!</p>' +
      '<p class="try-label">👆 Tap examples — see how a changes the shape</p>' },
  { title: 'Graph → Vertex Form', emoji: '📝',
    graphs: [{ a: 1, b: -6, c: 7, label: 'Example 1' },
      { a: -1, b: 4, c: -2, label: 'Example 2' },
      { a: 2, b: -4, c: 0, label: 'Example 3' }],
    body: '<p>Put it all together! <b>See a graph → write vertex form.</b></p>' +
      '<div class="lesson-eq">y = a(x − h)² + k</div>' +
      '<p><b>Full walkthrough</b> with Example 1 above ☝️</p>' +
      '<div class="steps-box"><div class="step"><b>Step 1:</b> Vertex → lowest point is <b>(3, −2)</b></div>' +
      '<div class="step">So h = 3 and k = −2</div>' +
      '<div class="step"><b>Step 2:</b> Pick point → curve hits <b>(4, −1)</b></div>' +
      '<div class="step"><b>Step 3:</b> Plug in: −1 = a(4−3)² + (−2)</div>' +
      '<div class="step">−1 = a − 2 → <code>a = 1</code></div>' +
      '<div class="step"><b>Step 4:</b> Write it! <code>y = (x − 3)² − 2</code> ✓</div></div>' +
      '<p><b>🧠 Always 3 things:</b> find h, find k, find a. Done!</p>' +
      '<p class="try-label">👆 Tap examples — try each in your head!</p>' },
  { title: 'Graph → Standard Form', emoji: '🏁',
    graphs: [{ a: 1, b: -6, c: 7, label: 'Same curve!' },
      { a: -2, b: 4, c: 1, label: 'Try this one' }],
    body: '<p>Write vertex form from a graph, then <b>convert to standard</b>!</p>' +
      '<p>Lesson 7 again — <b>unwrap the gift</b> 🎁</p>' +
      '<p><b>From the graph:</b></p>' +
      '<div class="lesson-eq">y = (x − 3)² − 2</div>' +
      '<p><b>Step 1: FOIL</b> (x−3)²</p>' +
      '<div class="steps-box"><div class="step">(x−3)(x−3) = x² − 6x + 9</div></div>' +
      '<p><b>Step 2: Add k</b> (−2)</p>' +
      '<div class="steps-box"><div class="step">x²−6x+9+(−2) = <code>x²−6x+7</code></div></div>' +
      '<p>🎉 <b>y = x² − 6x + 7</b></p>' +
      '<div class="steps-box"><div class="step">📊 Graph → 👀 read vertex & find a</div>' +
      '<div class="step">→ 📝 vertex form: y = a(x−h)² + k</div>' +
      '<div class="step">→ 🔁 FOIL + add k → standard form</div></div>' +
      '<p>Graph to <b>both equations</b> — superpower! 💪🎯</p>' },
];
