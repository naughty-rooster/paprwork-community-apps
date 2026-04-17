// X Action Engine — Focus Feed v3
// Top 10. Papr memory context. Profile pics. Media. 80/20 score. <100ms compose.

const APP_ID = '3e08bfb2-23f1-4173-b76f-f1910bdc31fd';
const FETCH_JOB_ID = 'a6e3bf40-3d06-44a2-84ca-93ead97a10a9';
const SCORER_JOB_ID = 'b768c137-c0e1-4f56-ad5b-c6d4b035065c';

// ── Types ──────────────────────────────────────────
interface Tweet {
  id: string;
  text: string;
  author_username: string;
  author_name: string;
  author_profile_image: string | null;
  created_at: string;
  reply_count: number;
  retweet_count: number;
  like_count: number;
  media_url: string | null;
  search_topic: string;
  score: number;
  score_type: 'give_value' | 'papr_mention';
  score_reason: string;
  draft_reply: string;
  draft_quote: string;
  status: string;
}

type Mode = 'browse' | 'reply' | 'quote';

// ── State ────────────────────────────────────────────
let tweets: Tweet[] = [];
let idx = 0;
let mode: Mode = 'browse';
let composeText = '';
let composeSeedText = '';
let loading = false;
let refreshing = false;

// ── API ──────────────────────────────────────────────
async function query<T = any>(sql: string, params: any[] = []): Promise<T[]> {
  const r = await fetch('/api/db/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ appId: APP_ID, sql, params })
  });
  const data = await r.json();
  return (data.rows || []) as T[];
}

async function dbWrite(sql: string, params: any[] = []) {
  await fetch('/api/db/write', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ appId: APP_ID, sql, params })
  });
}

async function ensureFeedbackTable() {
  await dbWrite(`CREATE TABLE IF NOT EXISTS draft_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tweet_id TEXT,
    mode TEXT,
    original_draft TEXT,
    edited_draft TEXT,
    was_changed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    posted_at TEXT,
    source_tweet_text TEXT,
    author_username TEXT,
    score_type TEXT
  )`);
}

async function runBash(cmd: string): Promise<{ stdout: string; exitCode: number }> {
  const r = await fetch('/api/bash/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command: cmd })
  });
  return r.json();
}

async function runJob(jobId: string, wait = false): Promise<any> {
  const r = await fetch('/api/jobs/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jobId, wait })
  });
  return r.json();
}

// ── Load ──────────────────────────────────────────────
async function loadFeed() {
  loading = true;
  render();

  try {
    await ensureFeedbackTable();
    // Prefer tweets that already have generated drafts so Reply/Quote opens pre-filled
    const withDrafts = await query<Tweet>(`
      SELECT * FROM tweets
      WHERE status = 'new' AND IFNULL(draft_reply, '') <> ''
      ORDER BY score DESC, datetime(scored_at) DESC
      LIMIT 10
    `);

    if (withDrafts.length > 0) {
      tweets = withDrafts;
    } else {
      // Next: scored tweets, even if draft field happened to be empty
      const scored = await query<Tweet>(`
        SELECT * FROM tweets
        WHERE score > 0 AND status = 'new'
        ORDER BY score DESC
        LIMIT 10
      `);

      if (scored.length > 0) {
        tweets = scored;
      } else {
        // Last fallback: engagement, but these may not have generated drafts yet
        tweets = await query<Tweet>(`
          SELECT * FROM tweets
          WHERE status = 'new'
          ORDER BY (like_count + retweet_count * 3 + reply_count * 2) DESC
          LIMIT 10
        `);
      }
    }

    idx = 0;
    mode = 'browse';
    composeText = '';
  } catch (e) {
    console.error('Load error:', e);
  }

  loading = false;
  render();
}

// ── Helpers ───────────────────────────────────────────
function esc(s: string): string {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

function decodeHTMLEntities(s: string): string {
  return (s || '')
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&#x27;/g, "'")
    .replace(/&nbsp;/g, ' ');
}

function escTweet(s: string): string {
  // Decode X API entities first, then safe-escape for HTML
  const decoded = decodeHTMLEntities(s);
  // Escape < and & for XSS safety, but keep > readable
  const safe = decoded
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/"/g, '&quot;');
  // Format: newlines → <br>, @mentions linkable
  return safe.replace(/\n/g, '<br>');
}

function initials(name: string): string {
  return (name || '?').split(' ').map((w: string) => w[0]).join('').slice(0, 2).toUpperCase();
}

function ago(d: string): string {
  if (!d) return '';
  try {
    const s = (Date.now() - new Date(d).getTime()) / 1000;
    if (s < 60) return 'now';
    if (s < 3600) return `${Math.floor(s / 60)}m`;
    if (s < 86400) return `${Math.floor(s / 3600)}h`;
    return `${Math.floor(s / 86400)}d`;
  } catch { return ''; }
}

function fmtNum(n: number): string {
  if (!n) return '0';
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}

function toast(msg: string, duration = 2500) {
  const el = document.getElementById('toast');
  if (el) {
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(() => el.classList.remove('show'), duration);
  }
}

function getCurrentTweet(): Tweet | null {
  return tweets[idx] || null;
}

// ── Actions ───────────────────────────────────────────
async function removeCurrent() {
  const t = getCurrentTweet();
  if (!t) return;

  const card = document.querySelector('.tweet-card') as HTMLElement;
  if (card) {
    card.classList.add('card-exit');
    await new Promise(r => setTimeout(r, 220));
  }

  tweets.splice(idx, 1);
  if (idx >= tweets.length) idx = Math.max(0, tweets.length - 1);
  mode = 'browse';
  composeText = '';
  composeSeedText = '';
  render();
}

async function skipTweet() {
  const t = getCurrentTweet();
  if (!t) return;
  await dbWrite(`UPDATE tweets SET status = 'skipped' WHERE id = ?`, [t.id]);
  await removeCurrent();
}

async function postAction() {
  const t = getCurrentTweet();
  if (!t || !composeText.trim()) return;

  const text = composeText.trim();
  const originalDraft = (composeSeedText || (mode === 'reply' ? t.draft_reply : t.draft_quote) || '').trim();
  const tweetUrl = `https://x.com/${t.author_username}/status/${t.id}`;
  const fullText = mode === 'quote' ? `${text}\n\n${tweetUrl}` : text;

  try {
    await navigator.clipboard.writeText(fullText);
  } catch (e) {
    console.warn('Clipboard failed:', e);
  }

  let xUrl: string;
  if (mode === 'reply') {
    xUrl = `https://x.com/intent/tweet?in_reply_to=${t.id}&text=${encodeURIComponent(text)}`;
  } else {
    xUrl = `https://x.com/intent/tweet?text=${encodeURIComponent(fullText)}`;
  }

  await ensureFeedbackTable();
  await dbWrite(
    `INSERT INTO draft_feedback (tweet_id, mode, original_draft, edited_draft, was_changed, posted_at, source_tweet_text, author_username, score_type)
     VALUES (?, ?, ?, ?, ?, datetime('now'), ?, ?, ?)`,
    [t.id, mode, originalDraft, text, originalDraft !== text ? 1 : 0, t.text || '', t.author_username || '', t.score_type || 'give_value']
  );

  await runBash(`open "${xUrl}"`);

  await dbWrite(
    `UPDATE tweets SET status = ?, acted_at = datetime('now') WHERE id = ?`,
    [mode === 'quote' ? 'quoted' : 'replied', t.id]
  );

  toast('✓ Copied! X opened in browser — your edit was saved to improve future drafts.', 4200);
  await removeCurrent();
}

async function runFetchAndScore() {
  refreshing = true;
  render();
  try {
    toast('Fetching fresh tweets...', 3000);
    const fetchRun = await runJob(FETCH_JOB_ID, true);
    if (fetchRun?.status === 'failed') {
      throw new Error('Feed fetch job failed');
    }

    toast('Scoring with Papr memory + edit feedback...', 5000);
    const scorerRun = await runJob(SCORER_JOB_ID, true);
    if (scorerRun?.status === 'failed') {
      const logs = String(scorerRun?.logs || '');
      if (logs.toLowerCase().includes('credit balance is too low')) {
        throw new Error('Scorer failed: Anthropic credits are exhausted');
      }
      throw new Error('Scorer job failed');
    }

    toast('✓ Feed updated!');
    await loadFeed();
  } catch (err: any) {
    const msg = String(err?.message || '');
    if (msg.includes('credits are exhausted')) {
      toast('⚠️ Scorer failed: add Anthropic credits or switch model key', 5000);
    } else {
      toast('⚠️ Refresh failed', 3000);
    }
    console.error('Refresh failed:', err);
  }
  refreshing = false;
  render();
}

async function openOnX(t: Tweet) {
  await runBash(`open "https://x.com/${t.author_username}/status/${t.id}"`);
}

// ── INSTANT Compose — <100ms, pre-populated textarea ──
// Key insight: innerHTML sets HTML attributes, NOT DOM properties.
// textarea.value is a DOM property — must be set via JS after DOM insertion.
// Solution: render() then synchronously set .value before browser paints.

function openCompose(newMode: 'reply' | 'quote') {
  const t = getCurrentTweet();
  if (!t) return;
  mode = newMode;
  composeText = decodeHTMLEntities(newMode === 'reply' ? (t.draft_reply || '') : (t.draft_quote || ''));
  composeSeedText = composeText;

  if (!composeText.trim()) {
    toast('No generated draft on this tweet yet. Tap refresh to re-score.', 3000);
  }

  // Full render — guarantees correct DOM structure
  render();

  // Synchronously set textarea value BEFORE next paint (guaranteed <16ms)
  const ta = document.querySelector('.compose-input') as HTMLTextAreaElement;
  if (ta) {
    ta.value = composeText;
    autoResizeTA(ta);
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
    // Also update the post button state since composeText is now populated
    const btn = document.querySelector('.compose-btns .btn-primary') as HTMLButtonElement;
    if (btn) btn.disabled = false;
    // Update char counter
    const maxChars = newMode === 'reply' ? 280 : 240;
    const counter = document.querySelector('.char-count') as HTMLElement;
    if (counter) counter.textContent = String(maxChars - composeText.length);
  }
}

function startReply() { openCompose('reply'); }
function startQuote() { openCompose('quote'); }

function cancelCompose() {
  mode = 'browse';
  composeText = '';
  composeSeedText = '';
  render();
}

function autoResizeTA(ta: HTMLTextAreaElement) {
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 160) + 'px';
}

// ── Render ──────────────────────────────────────────
function render() {
  const app = document.getElementById('app')!;
  const t = getCurrentTweet();
  const hasItems = tweets.length > 0;

  app.innerHTML = `
    <div class="app">
      ${renderTopbar()}
      <div class="card-area">
        ${loading || refreshing
          ? renderLoading()
          : !hasItems
          ? renderEmpty()
          : t
          ? `<div class="tweet-card" id="tweet-card">${mode !== 'browse' ? renderCompose(t) : renderTweetContent(t)}</div>`
          : ''}
      </div>
      ${!loading && !refreshing && hasItems && t && mode === 'browse' ? renderBottom() : ''}
      <div class="toast" id="toast"></div>
    </div>
  `;

  // Note: textarea value is set synchronously by openCompose() after render()
  // No async needed here — openCompose calls render() then sets .value immediately
}

function renderTopbar(): string {
  const hasItems = tweets.length > 0;
  return `
    <div class="topbar">
      <div class="topbar-left">
        <div class="topbar-logo">
          <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
            <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.744l7.737-8.845L1.396 2.25H8.28l4.259 5.63L18.244 2.25zm-1.161 17.52h1.833L7.084 4.126H5.117L17.083 19.77z"/>
          </svg>
          Action Engine
        </div>
        ${hasItems && !loading && !refreshing
          ? `<span class="topbar-counter">${idx + 1} / ${tweets.length}</span>`
          : ''}
      </div>
      <div class="topbar-right">
        <button class="icon-btn" onclick="openSettings()" title="Search topics">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
          </svg>
        </button>
        <button class="icon-btn ${refreshing ? 'spinning' : ''}" onclick="W.refresh()" title="Refresh + score with Papr memory" ${refreshing ? 'disabled' : ''}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M23 4v6h-6"/><path d="M1 20v-6h6"/>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
          </svg>
        </button>
      </div>
    </div>
  `;
}

function renderLoading(): string {
  return `
    <div class="loading-state">
      <div class="spinner-ring"></div>
      <p>${refreshing ? 'Fetching + scoring with Papr memory...' : 'Loading...'}</p>
    </div>
  `;
}

function renderEmpty(): string {
  return `
    <div class="empty-state">
      <div class="empty-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="40" height="40">
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
        </svg>
      </div>
      <h3>All caught up</h3>
      <p>No high-value tweets to act on.<br>Refresh to score new conversations.</p>
      <button class="btn-primary" onclick="W.refresh()">Refresh Feed</button>
    </div>
  `;
}

function renderTweetContent(t: Tweet): string {
  const isPapr = t.score_type === 'papr_mention';
  const scoreColor = isPapr ? '#a855f7' : '#1D9BF0';
  const scoreLabel = isPapr ? '🧠 PAPR' : '💡 80%';
  const score = t.score || 0;

  const avatarId = `av-${t.id.replace(/\W/g, '')}`;
  const imgSrc = t.author_profile_image
    ? esc(t.author_profile_image)
    : `https://unavatar.io/twitter/${esc(t.author_username)}`;

  return `
    <div class="author-row">
      <div class="avatar-wrap" onclick="W.openProfile('${esc(t.author_username)}')">
        <img 
          id="${avatarId}"
          class="avatar-img" 
          src="${imgSrc}"
          alt="${esc(t.author_name || t.author_username)}"
          onerror="this.style.display='none'; var fb=document.getElementById('${avatarId}-fb'); if(fb) fb.style.display='flex';"
        />
        <div id="${avatarId}-fb" class="avatar-fallback" style="display:none">${initials(t.author_name || t.author_username)}</div>
      </div>
      <div class="author-info">
        <span class="author-name">${esc(t.author_name || t.author_username)}</span>
        <span class="author-handle">@${esc(t.author_username || '')}</span>
      </div>
      <div class="meta-right">
        <span class="tweet-time">${ago(t.created_at)}</span>
        <div class="score-badge" style="background:${scoreColor}20;border-color:${scoreColor}40;color:${scoreColor}">
          ${scoreLabel} · ${score}
        </div>
      </div>
    </div>

    <div class="tweet-text" onclick="W.openX()" title="Open on X">${escTweet(t.text || '')}</div>

    ${t.media_url ? `
      <div class="tweet-media" onclick="W.openX()">
        <img src="${esc(t.media_url)}" alt="Tweet media" class="media-img"
          onerror="this.parentElement.style.display='none'" loading="lazy"/>
      </div>
    ` : ''}

    ${t.score_reason ? `
      <div class="score-reason">${esc(t.score_reason)}</div>
    ` : ''}

    <div class="metrics-row">
      <span class="metric">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="13" height="13"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        ${fmtNum(t.reply_count)}
      </span>
      <span class="metric">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="13" height="13"><path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><path d="M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>
        ${fmtNum(t.retweet_count)}
      </span>
      <span class="metric">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="13" height="13"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>
        ${fmtNum(t.like_count)}
      </span>
      <span class="metric open-x" onclick="W.openX()">
        <svg viewBox="0 0 24 24" fill="currentColor" width="12" height="12"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.744l7.737-8.845L1.396 2.25H8.28l4.259 5.63L18.244 2.25z"/></svg>
        View on X
      </span>
    </div>
  `;
}

function renderCompose(t: Tweet): string {
  const isReply = mode === 'reply';
  const maxChars = isReply ? 280 : 240;
  const remaining = maxChars - composeText.length;
  const isOverLimit = remaining < 0;
  const isNearLimit = remaining < 20;

  // Original tweet author avatar
  const origAvatarId = `oa-${t.id.replace(/\W/g, '')}`;
  const origImgSrc = t.author_profile_image
    ? esc(t.author_profile_image)
    : `https://unavatar.io/twitter/${esc(t.author_username)}`;

  return `
    <div class="compose-panel">

      <!-- Original tweet shown prominently at top -->
      <div class="compose-original-tweet">
        <div class="compose-original-author">
          <img
            id="${origAvatarId}"
            class="compose-original-avatar"
            src="${origImgSrc}"
            alt="${esc(t.author_name || t.author_username)}"
            onerror="this.style.display='none';document.getElementById('${origAvatarId}-fb').style.display='flex';"
          />
          <div id="${origAvatarId}-fb" class="compose-original-avatar-fallback" style="display:none">${initials(t.author_name || t.author_username)}</div>
          <div>
            <div class="compose-original-name">${esc(t.author_name || t.author_username)}</div>
            <div class="compose-original-handle">@${esc(t.author_username)}</div>
          </div>
        </div>
        <div class="compose-original-text">${escTweet(t.text || '')}</div>
      </div>

      <!-- Reply/Quote label -->
      <div class="compose-reply-label">${isReply ? `↩ Replying to @${esc(t.author_username)}` : `↗ Quoting @${esc(t.author_username)}`}</div>

      <!-- Compose area -->
      <div class="compose-area">
        <img class="compose-avatar"
          src="https://abs.twimg.com/sticky/default_profile_images/default_profile_normal.png"
          onerror="this.style.display='none';this.nextElementSibling.style.display='flex'"
          alt="You"
        />
        <div class="compose-avatar-fallback" style="display:none">SK</div>
        <textarea
          class="compose-input"
          placeholder="${isReply ? 'Write your reply...' : 'Add your thoughts...'}"
          maxlength="${maxChars + 50}"
          oninput="W.onInput(this)"
          onkeydown="W.onKey(event)"
        ></textarea>
      </div>
      <div class="compose-footer">
        <span class="char-count ${isNearLimit ? (isOverLimit ? 'over' : 'near') : ''}">${remaining}</span>
        <div class="compose-btns">
          <button class="btn-ghost" onclick="W.cancelCompose()">Cancel</button>
          <button class="btn-primary" onclick="W.post()">
            ${isReply ? '↗ Copy & Reply on X' : '↗ Copy & Quote on X'}
          </button>
        </div>
      </div>
    </div>
  `;
}

function renderBottom(): string {
  return `
    <div class="bottom-bar">
      <div class="bottom-bar-inner">
        <button class="action-btn-main reply-btn" onclick="W.startReply()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
          Reply
        </button>
        <button class="action-btn-main quote-btn" onclick="W.startQuote()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15">
            <path d="M21 2H3v16h5l3 3 3-3h7V2z"/>
          </svg>
          Quote
        </button>
        <button class="action-btn-ghost" onclick="W.skip()">Skip →</button>
      </div>
    </div>
  `;
}

// ── Global handlers ────────────────────────────────────
const W = {
  startReply,
  startQuote,
  cancelCompose,
  skip: skipTweet,
  post: postAction,
  refresh: runFetchAndScore,

  openX() { const t = getCurrentTweet(); if (t) openOnX(t); },
  openProfile(username: string) { runBash(`open "https://x.com/${username}"`); },

  onInput(el: HTMLTextAreaElement) {
    composeText = el.value;
    autoResizeTA(el);
    const maxChars = mode === 'reply' ? 280 : 240;
    const remaining = maxChars - composeText.length;
    const counter = document.querySelector('.char-count') as HTMLElement;
    if (counter) {
      counter.textContent = String(remaining);
      counter.className = `char-count ${remaining < 0 ? 'over' : remaining < 20 ? 'near' : ''}`;
    }
    const btn = document.querySelector('.compose-btns .btn-primary') as HTMLButtonElement;
    if (btn) btn.disabled = !composeText.trim() || remaining < 0;
  },

  onKey(e: KeyboardEvent) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); postAction(); }
    if (e.key === 'Escape') cancelCompose();
  },

  prevCard() {
    if (mode !== 'browse') { cancelCompose(); return; }
    if (idx > 0) { idx--; render(); }
  },
  nextCard() {
    if (mode !== 'browse') { cancelCompose(); return; }
    if (idx < tweets.length - 1) { idx++; render(); }
  }
};
(window as any).W = W;

// ── Keyboard shortcuts ─────────────────────────────────
document.addEventListener('keydown', (e) => {
  const tag = (e.target as HTMLElement).tagName;
  if (tag === 'TEXTAREA' || tag === 'INPUT') {
    if (e.key === 'Escape') { e.preventDefault(); cancelCompose(); }
    return;
  }
  if (mode !== 'browse') return;
  switch (e.key) {
    case 'r': case 'R': startReply(); break;
    case 'q': case 'Q': startQuote(); break;
    case 'ArrowRight': case 's': case 'S': skipTweet(); break;
    case 'ArrowLeft': W.prevCard(); break;
    case 'ArrowUp': W.prevCard(); break;
    case 'ArrowDown': W.nextCard(); break;
  }
});

// ── WebSocket for live job updates ─────────────────────
function connectWS() {
  try {
    const ws = new WebSocket('ws://localhost:18789');
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === 'jobs:status-changed' && msg.data?.status === 'completed') {
          if (msg.data.jobId === SCORER_JOB_ID) loadFeed();
        }
      } catch {}
    };
    ws.onclose = () => setTimeout(connectWS, 3000);
    ws.onerror = () => setTimeout(connectWS, 5000);
  } catch { setTimeout(connectWS, 5000); }
}

// ── Init ────────────────────────────────────────────────
loadFeed();
connectWS();
