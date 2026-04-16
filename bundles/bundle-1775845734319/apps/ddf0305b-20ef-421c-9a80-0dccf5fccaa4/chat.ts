// chat.ts — AI teacher chat using Claude via bash proxy
const APP_ID = 'ddf0305b-20ef-421c-9a80-0dccf5fccaa4';
const SYS = `You are Ms. Parabola, a warm, encouraging math teacher for a 6th grader learning algebra-1. You ONLY answer questions about parabolas, quadratic functions, standard form (y=ax²+bx+c), vertex form (y=a(x-h)²+k), and converting between them. Keep answers SHORT (2-4 sentences), use simple language, and add emoji. If asked something off-topic, gently redirect to parabolas. Never use LaTeX.`;
interface Msg { role: 'user' | 'assistant'; text: string }
const history: Msg[] = [];

export function setupChat(el: HTMLElement) {
  el.innerHTML = `<div class="chat-box">
    <div class="chat-header"><span>🧑‍🏫</span> Ask Ms. Parabola</div>
    <div class="chat-messages" id="chat-msgs">
      <div class="chat-bubble assistant">Hi! I'm <b>Ms. Parabola</b> 🧑‍🏫 Ask me anything about parabolas, standard form, or vertex form! I'm here to help you learn 💖</div>
    </div>
    <form class="chat-input-row" id="chat-form">
      <input type="text" id="chat-input" placeholder="Ask a question..." autocomplete="off">
      <button type="submit" class="btn btn-primary chat-send">→</button>
    </form>
  </div>`;
  const msgs = el.querySelector('#chat-msgs') as HTMLElement;
  const form = el.querySelector('#chat-form') as HTMLFormElement;
  const inp = el.querySelector('#chat-input') as HTMLInputElement;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const q = inp.value.trim(); if (!q) return;
    inp.value = ''; inp.disabled = true;
    history.push({ role: 'user', text: q });
    msgs.innerHTML += `<div class="chat-bubble user">${esc(q)}</div>`;
    msgs.innerHTML += `<div class="chat-bubble assistant typing" id="typing">thinking... 💭</div>`;
    msgs.scrollTop = msgs.scrollHeight;
    try {
      const reply = await askClaude(history);
      history.push({ role: 'assistant', text: reply });
      el.querySelector('#typing')?.remove();
      msgs.innerHTML += `<div class="chat-bubble assistant">${esc(reply)}</div>`;
    } catch {
      el.querySelector('#typing')?.remove();
      msgs.innerHTML += `<div class="chat-bubble assistant">Oops! Something went wrong. Try again 💖</div>`;
    }
    inp.disabled = false; inp.focus(); msgs.scrollTop = msgs.scrollHeight;
  });
}

async function askClaude(msgs: Msg[]): Promise<string> {
  const apiMsgs = msgs.map(m => ({ role: m.role, content: m.text }));
  const body = JSON.stringify({
    model: 'claude-sonnet-4-20250514', max_tokens: 300,
    system: SYS, messages: apiMsgs
  });
  const escaped = body.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const cmd = `curl -s https://api.anthropic.com/v1/messages -H "content-type: application/json" -H "x-api-key: \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" -H "anthropic-version: 2023-06-01" -d "${escaped}"`;
  const res = await fetch('/api/bash/run', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ appId: APP_ID, command: cmd })
  });
  const data = await res.json();
  const parsed = JSON.parse(data.stdout || '{}');
  return parsed?.content?.[0]?.text || 'Hmm, I had trouble thinking. Try again! 🤔';
}

function esc(s: string) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
