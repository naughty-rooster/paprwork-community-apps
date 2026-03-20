// Meetings Manager — Steve Jobs × Elon Musk
// One job: Record meeting → transcribe → summarize. That's it.

const APP_ID = 'ea6d8d7c-a15e-4c02-8273-117450b498f4';
const RECORDER_JOB    = '54837f40-1e64-4810-a387-f81151d014af';
const STOP_JOB        = '5a5c47c7-46f0-430e-8b01-499bdf65de42';
const WHISPER_JOB     = '52b4abeb-0d23-4724-9a82-0559c64150c1';
const SUMMARIZER_JOB  = '8eea1893-4ca5-48ed-bfb4-187b9456fb31';
const PERM_JOB        = 'eb3200be-fa32-4a83-8313-94df426dea89';
const CALENDAR_JOB    = '40407339-ca0b-4650-a009-426201025e81';
const PREP_JOB        = '4d58f7c1-40b5-4aed-805f-f983c0ac0c4c';
const BG_JOB          = 'd4a2aad6-4722-44b1-b869-d2834cd56975';

interface Meeting {
  id: string; title: string; date: string; duration: number;
  status: string; transcript: string; summary: string; notes: string;
  tags: string; // JSON array string e.g. '["Product","Engineering"]'
  created_at: number;
}
interface CalEvent {
  id: string; title: string; start_time: string; end_time: string;
  calendar_name: string; meeting_id: string;
  attendees: string; prep_status: string; prep_doc: string;
}
interface Attendee { name: string; email: string; organizer?: boolean; }
interface LocationBackground {
  city: string; reason: string; prompt: string; image_url: string; image_data: string; generated_on: string;
}

type View = 'home' | 'meeting';
type Filter = 'all' | 'today' | 'week' | 'month';

let view: View = 'home';
let meetings: Meeting[] = [];
let calEvents: CalEvent[] = [];
let bg: LocationBackground | null = null;
let liveCity = '';
let liveLocationReason = '';
let selectedId: string | null = null;
let isRecording = false;
let recordingId: string | null = null;
let permissionGranted: boolean | null = null;
let showPermModal = false;
let elapsedSeconds = 0;
let timerInterval: ReturnType<typeof setInterval> | null = null;
let pollInterval: ReturnType<typeof setInterval> | null = null;
let saveTimeout: ReturnType<typeof setTimeout> | null = null;
let activeFilter: Filter = 'all';
let activeTags: string[] = [];
let activePeople: string[] = [];
let calView: string = '';
let calMeetingIdx: number = 0;
let calDayNavDir: 'left'|'right' = 'right';
let calDayView: 'focus'|'all' = 'focus';
let calWeekOffset: number = 0;
let mainPage: 'meetings' | 'notes' = 'meetings';
let activeTab: 'notes' | 'transcript' | 'prep' = 'notes';
let selectedCalId: string | null = null;
let prepPollInterval: ReturnType<typeof setInterval> | null = null;
let showBgHero: boolean = localStorage.getItem('mm-show-bg') === 'true'; // default off

// DB & Jobs
async function q(sql: string, p: unknown[] = []): Promise<any[]> {
  const r = await fetch('/api/db/query', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({appId: APP_ID, sql, params: p})
  });
  return (await r.json()).rows || [];
}
async function w(sql: string, p: unknown[] = []): Promise<void> {
  await fetch('/api/db/write', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({appId: APP_ID, sql, params: p})
  });
}
async function runJob(id: string): Promise<void> {
  await fetch('/api/jobs/run', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({jobId: id})
  });
}
function sleep(ms: number) { return new Promise(r => setTimeout(r, ms)); }

// Data
async function loadAll(): Promise<void> {
  try { meetings = await q('SELECT * FROM meetings ORDER BY created_at DESC'); } catch { meetings = []; }
  try {
    calEvents = await q(`SELECT id, title, start_time, end_time, calendar_name, meeting_id, 
      COALESCE(attendees, '[]') as attendees, COALESCE(prep_status, '') as prep_status, 
      COALESCE(prep_doc, '') as prep_doc
      FROM calendar_events
      WHERE NOT (start_time LIKE '%T00:00' AND end_time LIKE '%T23:59')
      ORDER BY start_time ASC`);
  } catch { calEvents = []; }
  try {
    const rows = await q(`SELECT city, reason, prompt, image_url, image_data, generated_on FROM location_background WHERE id='daily' LIMIT 1`);
    bg = rows[0] || null;
  } catch { bg = null; }
  render();
  loadBgImage();
}

// Permission
async function checkPerm(): Promise<boolean> {
  await w('DELETE FROM permission_checks');
  await runJob(PERM_JOB);
  for (let i = 0; i < 30; i++) {
    await sleep(500);
    const rows = await q('SELECT result FROM permission_checks ORDER BY created_at DESC LIMIT 1');
    if (rows.length) { permissionGranted = rows[0].result === 'PERMISSION_GRANTED'; return permissionGranted; }
  }
  permissionGranted = false; return false;
}

// Recording
async function startRecording(fromCalId?: string): Promise<void> {
  if (permissionGranted !== true) {
    const ok = await checkPerm();
    if (!ok) { showPermModal = true; render(); return; }
  }
  const id = crypto.randomUUID();
  const now = new Date().toISOString();
  let title = 'Meeting \u2014 ' + new Date().toLocaleString(undefined, {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'});
  if (fromCalId) {
    const ev = calEvents.find(e => e.id === fromCalId);
    if (ev) {
      title = ev.title;
      await w("UPDATE calendar_events SET meeting_id = ? WHERE id = ?", [id, fromCalId]);
    }
  }
  await w("INSERT INTO meetings (id, title, date, status) VALUES (?, ?, ?, 'recording')", [id, title, now]);
  recordingId = id; isRecording = true; elapsedSeconds = 0; selectedId = id;
  view = 'meeting';
  timerInterval = setInterval(() => {
    elapsedSeconds++;
    const el = document.getElementById('rec-timer');
    if (el) el.textContent = fmtDur(elapsedSeconds);
  }, 1000);
  await runJob(RECORDER_JOB);
  await loadAll();
}

async function stopRecording(): Promise<void> {
  if (!recordingId) return;
  const editor = document.getElementById('notes-editor') as HTMLElement;
  if (editor) {
    const notes = editor.innerHTML.trim();
    if (notes) await w("UPDATE meetings SET notes=?, updated_at=strftime('%s','now') WHERE id=?", [notes, recordingId]);
  }
  isRecording = false;
  if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
  await w("UPDATE meetings SET duration=?, updated_at=strftime('%s','now') WHERE id=?", [elapsedSeconds, recordingId]);
  await w("UPDATE meetings SET status='stopping', updated_at=strftime('%s','now') WHERE id=?", [recordingId]);
  await runJob(STOP_JOB);
  const sid = recordingId;
  recordingId = null; elapsedSeconds = 0;
  await loadAll();
  triggerWhisperWhenReady(sid);
  startPoll(sid);
}

async function triggerWhisperWhenReady(mid: string): Promise<void> {
  for (let i = 0; i < 60; i++) {
    await sleep(2000);
    const rows = await q("SELECT status FROM meetings WHERE id=?", [mid]);
    if (!rows.length || rows[0].status === 'failed') return;
    if (rows[0].status === 'recorded') { await runJob(WHISPER_JOB); return; }
    // Keep polling through 'stopping' and 'recording' states
  }
}

function startPoll(mid: string): void {
  let attempts = 0, last = '';
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(async () => {
    if (++attempts > 300) { clearInterval(pollInterval!); return; }
    const rows = await q("SELECT status FROM meetings WHERE id=?", [mid]);
    if (!rows.length) return;
    const s = rows[0].status;
    if (s !== last) {
      last = s;
      await loadAll();
      if (s === 'pending') runJob(SUMMARIZER_JOB).catch(() => {});
    }
    if (s === 'summarized' || s === 'failed') { clearInterval(pollInterval!); pollInterval = null; }
  }, 2000);
}

function flushSave(): void {
  const editor = document.getElementById('notes-editor') as HTMLElement;
  const id = isRecording ? recordingId : selectedId;
  if (!editor || !id) return;
  const html = editor.innerHTML.trim();
  if (saveTimeout) { clearTimeout(saveTimeout); saveTimeout = null; }
  if (activeTab === 'prep' && selectedCalId) {
    w("UPDATE calendar_events SET prep_doc=? WHERE id=?", [html, selectedCalId]);
  } else if (activeTab === 'notes') {
    w("UPDATE meetings SET notes=?, updated_at=strftime('%s','now') WHERE id=?", [html, id]);
  }
}

function autoSave(): void {
  if (saveTimeout) clearTimeout(saveTimeout);
  saveTimeout = setTimeout(() => flushSave(), 1500);
}

// Find linked CalEvent: first by explicit meeting_id, then by title+date fuzzy match
function findLinkedCalEvent(m: Meeting): CalEvent | undefined {
  const byId = calEvents.find(e => e.meeting_id === m.id);
  if (byId) return byId;
  if (!m.date) return undefined;
  return calEvents.find(e =>
    e.title.toLowerCase() === m.title.toLowerCase()
    && e.start_time.split('T')[0] === m.date.split('T')[0]);
}

function parseAttendees(json: string): Attendee[] {
  try { return JSON.parse(json || '[]'); } catch { return []; }
}
function getInitials(name: string): string {
  if (!name) return '?';
  const parts = name.split(/[\s@.]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase();
}
const avatarColors = ['#0161E0','#7C3AED','#059669','#D97706','#DC2626','#0891B2','#BE185D','#4F46E5'];
function avatarColor(name: string): string {
  let h = 0; for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h);
  return avatarColors[Math.abs(h) % avatarColors.length];
}

async function triggerPrep(eventId: string): Promise<void> {
  const ev = calEvents.find(e => e.id === eventId);
  if (!ev) return;
  const attendees = parseAttendees(ev.attendees);
  const req = { event_id: eventId, title: ev.title, attendees, start_time: ev.start_time, calendar_name: ev.calendar_name };
  await w("UPDATE calendar_events SET prep_status='preparing', prep_doc=? WHERE id=?", [JSON.stringify(req), eventId]);
  await runJob(PREP_JOB);
  startPrepPoll(eventId);
  await loadAll();
}

function startPrepPoll(eventId: string): void {
  if (prepPollInterval) clearInterval(prepPollInterval);
  let attempts = 0;
  const MAX_ATTEMPTS = 200; // 10 min timeout (200 * 3s)
  prepPollInterval = setInterval(async () => {
    attempts++;
    const rows = await q("SELECT prep_status, prep_doc FROM calendar_events WHERE id=?", [eventId]);
    if (rows.length && rows[0].prep_status === 'ready') {
      clearInterval(prepPollInterval!); prepPollInterval = null;
      await loadAll();
    } else if (attempts >= MAX_ATTEMPTS) {
      clearInterval(prepPollInterval!); prepPollInterval = null;
      await w("UPDATE calendar_events SET prep_status='failed' WHERE id=? AND prep_status='preparing'", [eventId]);
      await loadAll();
    }
  }, 3000);
}

async function recoverStuckPreps(): Promise<void> {
  const stuck = await q("SELECT id FROM calendar_events WHERE prep_status='preparing'");
  if (stuck.length > 0) {
    startPrepPoll(stuck[0].id);
  }
}

// Recover recording state on app load (e.g. after navigating away or refresh)
async function recoverRecordingState(): Promise<void> {
  const rows = await q("SELECT id, date FROM meetings WHERE status='recording' LIMIT 1");
  if (rows.length > 0) {
    const m = rows[0];
    isRecording = true;
    recordingId = m.id;
    permissionGranted = true;
    const startTime = new Date(m.date).getTime();
    elapsedSeconds = Math.max(0, Math.floor((Date.now() - startTime) / 1000));
    if (!timerInterval) {
      timerInterval = setInterval(() => {
        elapsedSeconds++;
        const el = document.getElementById('rec-timer');
        if (el) el.textContent = fmtDur(elapsedSeconds);
      }, 1000);
    }
  }
}

async function detectLiveLocation(): Promise<void> {
  const saveLocation = async (city: string, source: string, lat: number | null = null, lon: number | null = null): Promise<void> => {
    liveCity = city;
    liveLocationReason = `${source === 'geolocation' ? 'Live location' : 'Network location'} says ${city}${bg?.city && bg.city !== city ? ` — overriding calendar-derived ${bg.city}` : ''}`;
    await w(`CREATE TABLE IF NOT EXISTS location_override (id TEXT PRIMARY KEY, city TEXT DEFAULT '', lat REAL, lon REAL, source TEXT DEFAULT '', updated_at INTEGER DEFAULT (strftime('%s','now')))`);
    await w(`INSERT INTO location_override (id, city, lat, lon, source, updated_at) VALUES ('latest', ?, ?, ?, ?, strftime('%s','now')) ON CONFLICT(id) DO UPDATE SET city=excluded.city, lat=excluded.lat, lon=excluded.lon, source=excluded.source, updated_at=excluded.updated_at`, [city, lat, lon, source]);
    render();
    if (city !== bg?.city) {
      await runJob(BG_JOB).catch(() => {});
      await sleep(1800);
      await loadAll();
    }
  };

  if ('geolocation' in navigator) {
    try {
      const pos = await new Promise<GeolocationPosition>((resolve, reject) => navigator.geolocation.getCurrentPosition(resolve, reject, { enableHighAccuracy: false, timeout: 3500, maximumAge: 60 * 60 * 1000 }));
      const lat = pos.coords.latitude;
      const lon = pos.coords.longitude;
      const r = await fetch(`https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${lat}&lon=${lon}`, { headers: { 'Accept': 'application/json' } });
      const data = await r.json();
      const addr = data.address || {};
      const city = addr.city || addr.town || addr.village || addr.county || data.name || '';
      if (city) {
        await saveLocation(city, 'geolocation', lat, lon);
        return;
      }
    } catch {}
  }

  try {
    const r = await fetch('https://ipapi.co/json/');
    const data = await r.json();
    const city = data?.city || data?.region || '';
    if (city) await saveLocation(city, 'ip');
  } catch {}
}

async function deleteMeeting(id: string, e: Event): Promise<void> {
  e.stopPropagation();
  await w("DELETE FROM meetings WHERE id=?", [id]);
  if (selectedId === id) { selectedId = null; view = 'home'; }
  await loadAll();
}

function openMeeting(id: string, tab?: string): void {
  selectedId = id; view = 'meeting'; activeTab = (tab as any) || 'notes';
  const m = meetings.find(x => x.id === id);
  if (m) {
    const linkedEv = findLinkedCalEvent(m);
    selectedCalId = linkedEv?.id || null;
    // Recover recording state if navigating back to an active recording
    if (m.status === 'recording' && !isRecording) {
      isRecording = true;
      recordingId = id;
      permissionGranted = true;
      if (!timerInterval) {
        const startTime = new Date(m.date).getTime();
        elapsedSeconds = Math.max(0, Math.floor((Date.now() - startTime) / 1000));
        timerInterval = setInterval(() => {
          elapsedSeconds++;
          const el = document.getElementById('rec-timer');
          if (el) el.textContent = fmtDur(elapsedSeconds);
        }, 1000);
      }
    }
    if (['stopping','recorded','transcribing','pending'].includes(m.status)) startPoll(id);
    if (m.status === 'stopping') triggerWhisperWhenReady(id);
    if (m.status === 'recorded') runJob(WHISPER_JOB).catch(() => {});
    if (m.status === 'pending') runJob(SUMMARIZER_JOB).catch(() => {});
  } else {
    const ev = calEvents.find(e => e.id === id);
    if (ev) {
      selectedCalId = ev.id;
      selectedId = ev.meeting_id || null;
      activeTab = tab || 'prep';
    }
  }
  render();
}

// Tags — LLM-generated, stored as JSON array in DB
function extractTags(m: Meeting): string[] {
  if (!m.tags) return [];
  try { return JSON.parse(m.tags) as string[]; } catch { return []; }
}
function getAllTags(): string[] {
  const all = new Set<string>();
  meetings.forEach(m => extractTags(m).forEach(t => all.add(t)));
  return [...all];
}
function getAllPeople(): Attendee[] {
  const seen = new Map<string, Attendee>();
  meetings.forEach(m => {
    const ev = findLinkedCalEvent(m);
    if (ev) {
      parseAttendees(ev.attendees).forEach(a => {
        if (!seen.has(a.email)) seen.set(a.email, a);
      });
    }
  });
  return [...seen.values()].sort((a, b) => (a.name || a.email).localeCompare(b.name || b.email));
}
function filterMeetings(): Meeting[] {
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const weekStart = new Date(todayStart); weekStart.setDate(todayStart.getDate() - 7);
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
  return meetings.filter(m => {
    const d = new Date(m.date);
    if (activeFilter === 'today' && d < todayStart) return false;
    if (activeFilter === 'week' && d < weekStart) return false;
    if (activeFilter === 'month' && d < monthStart) return false;
    if (activeTags.length > 0 && !activeTags.some(t => extractTags(m).includes(t))) return false;
    if (activePeople.length > 0) {
      const ev = findLinkedCalEvent(m);
      if (!ev) return false;
      const emails = parseAttendees(ev.attendees).map(a => a.email);
      if (!activePeople.some(p => emails.includes(p))) return false;
    }
    return true;
  });
}

// Calendar helpers
function localDateStr(d = new Date()): string {
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}
function getTodayEvents(): CalEvent[] {
  const todayStr = localDateStr();
  return calEvents.filter(e => e.start_time.startsWith(todayStr));
}
function getWeekEvents(): Map<string, CalEvent[]> {
  const now = new Date();
  const startOfWeek = new Date(now); startOfWeek.setDate(now.getDate() - now.getDay());
  const endOfWeek = new Date(startOfWeek); endOfWeek.setDate(startOfWeek.getDate() + 6);
  const byDay = new Map<string, CalEvent[]>();
  for (let d = new Date(startOfWeek); d <= endOfWeek; d.setDate(d.getDate() + 1)) {
    byDay.set(localDateStr(d), []);
  }
  calEvents.forEach(e => {
    const k = e.start_time.slice(0, 10);
    if (byDay.has(k)) byDay.get(k)!.push(e);
  });
  return byDay;
}
function getMonthEvents(): { weeks: {day: number, date: string, isToday: boolean, events: CalEvent[]}[][] } {
  const now = new Date();
  const y = now.getFullYear(), mo = now.getMonth();
  const first = new Date(y, mo, 1);
  const last = new Date(y, mo + 1, 0);
  const todayStr = localDateStr(now);
  const weeks: {day: number, date: string, isToday: boolean, events: CalEvent[]}[][] = [];
  let week: typeof weeks[0] = [];
  for (let i = 0; i < first.getDay(); i++) week.push({day: 0, date: '', isToday: false, events: []});
  for (let d = 1; d <= last.getDate(); d++) {
    const ds = y + '-' + String(mo+1).padStart(2,'0') + '-' + String(d).padStart(2,'0');
    const evs = calEvents.filter(e => e.start_time.startsWith(ds));
    week.push({day: d, date: ds, isToday: ds === todayStr, events: evs});
    if (week.length === 7) { weeks.push(week); week = []; }
  }
  if (week.length) { while (week.length < 7) week.push({day: 0, date: '', isToday: false, events: []}); weeks.push(week); }
  return {weeks};
}
function shortDay(i: number): string { return ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][i]; }
function isEventNow(e: CalEvent): boolean {
  const now = new Date();
  return new Date(e.start_time) <= now && now <= new Date(e.end_time);
}
function isEventSoon(e: CalEvent): boolean {
  const diff = (new Date(e.start_time).getTime() - Date.now()) / 60000;
  return diff > 0 && diff <= 30;
}

// Formatting
function fmtDur(s: number): string {
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60), sec = s%60;
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}
function pad(n: number) { return String(n).padStart(2,'0'); }
function fmtDate(d: string): string {
  return new Date(d).toLocaleDateString(undefined, {weekday:'short', month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'});
}
function fmtTime(t: string): string {
  return new Date(t).toLocaleTimeString(undefined, {hour:'2-digit', minute:'2-digit'});
}
function fmtDayLabel(t: string): string {
  const d = new Date(t), now = new Date();
  const tom = new Date(now); tom.setDate(now.getDate() + 1);
  if (d.toDateString() === now.toDateString()) return 'Today';
  if (d.toDateString() === tom.toDateString()) return 'Tomorrow';
  return d.toLocaleDateString(undefined, {weekday:'long', month:'short', day:'numeric'});
}
function esc(s: string): string { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
function statusLabel(s: string): string {
  return {recording:'Recording', stopping:'Processing', recorded:'Transcribing', transcribing:'Transcribing',
    pending:'Summarizing', summarized:'Complete', failed:'Failed'}[s] || s;
}
function statusClass(s: string): string {
  return {recording:'status-recording', stopping:'status-processing', recorded:'status-processing',
    transcribing:'status-processing', pending:'status-processing',
    summarized:'status-done', failed:'status-failed'}[s] || '';
}
function formatSummary(text: string): string {
  if (!text) return '';
  const lines = text.split('\n');
  let html = '';
  let inList = false;
  let inTable = false;
  let tableHeader = false;
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      if (inList) { html += '</ul>'; inList = false; }
      if (inTable) { html += '</tbody></table>'; inTable = false; tableHeader = false; }
      continue;
    }
    // Table rows (pipes)
    if (/^\|(.+)\|$/.test(trimmed)) {
      if (inList) { html += '</ul>'; inList = false; }
      // Skip separator rows like |---|---|
      if (/^\|[\s\-:|]+\|$/.test(trimmed)) {
        tableHeader = false;
        continue;
      }
      const cells = trimmed.split('|').filter(c => c.trim() !== '').map(c => c.trim().replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>'));
      if (!inTable) {
        html += '<table class="md-table"><thead><tr>';
        cells.forEach(c => html += `<th>${c}</th>`);
        html += '</tr></thead><tbody>';
        inTable = true;
        tableHeader = true;
      } else {
        html += '<tr>';
        cells.forEach(c => html += `<td>${c}</td>`);
        html += '</tr>';
      }
      continue;
    }
    if (inTable) { html += '</tbody></table>'; inTable = false; tableHeader = false; }
    // Headers
    if (/^## (.+)/.test(trimmed)) {
      if (inList) { html += '</ul>'; inList = false; }
      html += `<h3>${trimmed.replace(/^## /, '')}</h3>`;
    } else if (/^### (.+)/.test(trimmed)) {
      if (inList) { html += '</ul>'; inList = false; }
      html += `<h4>${trimmed.replace(/^### /, '')}</h4>`;
    }
    // Action items
    else if (/^- \[ \] (.+)/.test(trimmed)) {
      if (inList) { html += '</ul>'; inList = false; }
      html += `<label class="action-item"><input type="checkbox"> ${trimmed.replace(/^- \[ \] /, '').replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')}</label>`;
    } else if (/^- \[x\] (.+)/.test(trimmed)) {
      if (inList) { html += '</ul>'; inList = false; }
      html += `<label class="action-item done"><input type="checkbox" checked> ${trimmed.replace(/^- \[x\] /, '').replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')}</label>`;
    }
    // List items
    else if (/^[-*] (.+)/.test(trimmed)) {
      if (!inList) { html += '<ul>'; inList = true; }
      html += `<li>${trimmed.replace(/^[-*] /, '').replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')}</li>`;
    }
    // Regular text
    else {
      if (inList) { html += '</ul>'; inList = false; }
      html += `<p>${trimmed.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')}</p>`;
    }
  }
  if (inList) html += '</ul>';
  if (inTable) html += '</tbody></table>';
  return html;
}

function icon(name: string, size = 18): string {
  const i: Record<string, string> = {
    mic: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>`,
    stop: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>`,
    back: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>`,
    lock: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>`,
    settings: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`,
    check: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>`,
    trash: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`,
    clock: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
    cal: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>`,
    chevron: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>`,
    note: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`,
    sparkle: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z"/></svg>`,
    refresh: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>`,
    tag: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>`,
    person: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
    eye: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`,
    'eye-off': `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`,
  };
  return i[name] || '';
}

// Render — background image handling
let cachedBgBlobUrl = '';

function bgSrc(): string {
  return cachedBgBlobUrl || '';
}

async function loadBgImage(): Promise<void> {
  // Prefer inline data URL (works everywhere, no protocol issues)
  if (bg?.image_data && bg.image_data.startsWith('data:')) {
    cachedBgBlobUrl = bg.image_data;
    applyBackground(); render(); return;
  }
  // Fallback: try fetching file:// URL (works in some Electron configs)
  const fileUrl = bg?.image_url || '';
  if (!fileUrl) return;
  try {
    const resp = await fetch(fileUrl);
    if (resp.ok) {
      const blob = await resp.blob();
      if (cachedBgBlobUrl) URL.revokeObjectURL(cachedBgBlobUrl);
      cachedBgBlobUrl = URL.createObjectURL(blob);
      applyBackground(); render(); return;
    }
  } catch {}
}

function applyBackground(): void {
  const body = document.body as HTMLBodyElement;
  const src = bgSrc();
  if (src && showBgHero) body.style.setProperty('--bg-image', `url("${src}")`);
  else body.style.removeProperty('--bg-image');
}

function renderBackgroundLayer(): string {
  if (!showBgHero) return '<div class="app-bg app-bg--fallback"></div>';
  const src = bgSrc();
  const city = liveCity || bg?.city || '';
  if (!src) return '<div class="app-bg app-bg--fallback"></div>';
  return `<div class="app-bg" aria-hidden="true">
    <img class="app-bg-img" src="${esc(src)}" alt="${esc(city + ' background')}">
    <div class="app-bg-scrim"></div>
  </div>`;
}

function render(): void {
  const root = document.getElementById('root')!;
  const content = showPermModal ? renderPermModal() : (view === 'home' ? renderHome() : renderMeeting());
  root.innerHTML = `${renderBackgroundLayer()}<div class="app-shell">${content}</div>
    <button class="bg-toggle-fab" id="btn-toggle-bg" title="${showBgHero ? 'Hide' : 'Show'} background & location">
      ${showBgHero ? icon('eye', 16) : icon('eye-off', 16)}
    </button>`;
  applyBackground();
  attachListeners();
}

function renderPermModal(): string {
  return `
    <div class="perm-overlay">
      <div class="perm-modal glass">
        <div class="perm-icon">${icon('lock', 28)}</div>
        <h2>Screen Recording Required</h2>
        <p>To capture audio from Zoom, Teams, or Meet, Paprwork needs Screen Recording access.</p>
        <ol>
          <li>Open <strong>System Settings</strong></li>
          <li>Go to <strong>Privacy &amp; Security &rarr; Screen Recording</strong></li>
          <li>Enable <strong>Paprwork</strong></li>
        </ol>
        <div class="perm-actions">
          <button class="btn-primary" id="btn-open-settings">${icon('settings', 15)} Open System Settings</button>
          <button class="btn-ghost" id="btn-retry-perm">${icon('refresh', 15)} I've enabled it</button>
        </div>
      </div>
    </div>`;
}

function renderAttendees(attendees: Attendee[], max = 5): string {
  if (!attendees.length) return '';
  const shown = attendees.slice(0, max);
  const extra = attendees.length - max;
  return `<div class="attendee-row">
    ${shown.map(a => `<div class="avatar" style="background:${avatarColor(a.name || a.email)}" title="${esc(a.name || a.email)}">${getInitials(a.name || a.email)}</div>`).join('')}
    ${extra > 0 ? `<div class="avatar avatar-more">+${extra}</div>` : ''}
  </div>`;
}

function toggleBgHero(): void {
  showBgHero = !showBgHero;
  localStorage.setItem('mm-show-bg', String(showBgHero));
  applyBackground();
  render();
}

function renderBackgroundHero(): string {
  if (!showBgHero) return '';
  const city = liveCity || bg?.city || 'San Francisco';
  const reason = liveLocationReason || bg?.reason || '';
  return `
    <section class="bg-hero">
      <h1 class="bg-hero-city">${esc(city)}</h1>
      ${reason ? `<p class="bg-hero-reason">${esc(reason)}</p>` : ''}
      <button class="bg-hero-refresh" id="btn-refresh-bg">${icon('refresh', 14)} Refresh</button>
    </section>`;
}

function renderHome(): string {
  const todayEvs = getTodayEvents();
  const filtered = filterMeetings();
  const allTags = getAllTags();
  const allPeople = getAllPeople();

  return `
    <div class="home-layout">
      <header class="home-header glass">
        <nav class="home-nav">
          <button class="home-nav-tab${mainPage === 'meetings' ? ' active' : ''}" data-page="meetings">Meetings</button>
          <button class="home-nav-tab${mainPage === 'notes' ? ' active' : ''}" data-page="notes">Notes</button>
        </nav>
        <div class="header-actions">
          <button class="btn-record" id="btn-new-rec">
            New Note
          </button>
        </div>
      </header>
      <div class="home-main">
        ${renderBackgroundHero()}

        ${mainPage === 'meetings' ? `
        <section class="home-section">
          <div class="section-header">
            <div class="cal-pills-row">
              <button class="week-nav-btn" onclick="event.stopPropagation(); shiftWeek(-1)">&#8249;</button>
              <div class="cal-pills">
                ${getWeekDayPills()}
              </div>
              <button class="week-nav-btn" onclick="event.stopPropagation(); shiftWeek(1)">&#8250;</button>
            </div>
          </div>
          ${renderCalView()}
        </section>
        ` : `
        <section class="home-section">
          <div class="section-header">
            <div class="filter-bar">
              <div class="filter-pills">
                ${(['all','today','week','month'] as Filter[]).map(f => `
                  <button class="pill${activeFilter === f ? ' pill-active' : ''}" data-filter="${f}">
                    ${f === 'all' ? 'All' : f === 'today' ? 'Today' : f === 'week' ? 'This Week' : 'This Month'}
                  </button>`).join('')}
              </div>
              <div class="filter-selectors">
                ${allTags.length ? `
                <div class="filter-select-wrap">
                  <button class="filter-select${activeTags.length ? ' has-selection' : ''}" id="btn-topic-select">
                    ${icon('tag', 13)}
                    ${activeTags.length ? activeTags.join(', ') : 'Topics'}
                    ${icon('chevron', 10)}
                  </button>
                  <div class="filter-dropdown" id="dropdown-topics">
                    ${allTags.map(t => `
                      <label class="filter-option"><input type="checkbox" value="${esc(t)}" ${activeTags.includes(t) ? 'checked' : ''} data-topic-check> ${esc(t)}</label>
                    `).join('')}
                    <button class="filter-clear" id="btn-clear-topics">Clear</button>
                  </div>
                </div>` : ''}
                ${allPeople.length ? `
                <div class="filter-select-wrap">
                  <button class="filter-select${activePeople.length ? ' has-selection' : ''}" id="btn-people-select">
                    ${icon('person', 13)}
                    ${activePeople.length ? activePeople.length + ' selected' : 'People'}
                    ${icon('chevron', 10)}
                  </button>
                  <div class="filter-dropdown" id="dropdown-people">
                    ${allPeople.map(p => `
                      <label class="filter-option"><input type="checkbox" value="${esc(p.email)}" ${activePeople.includes(p.email) ? 'checked' : ''} data-people-check>
                        <span class="avatar-sm" style="background:${avatarColor(p.name||p.email)}">${getInitials(p.name||p.email)}</span>
                        ${esc(p.name || p.email)}
                      </label>
                    `).join('')}
                    <button class="filter-clear" id="btn-clear-people">Clear</button>
                  </div>
                </div>` : ''}
              </div>
            </div>
          </div>
          <div class="meeting-list">
            ${filtered.length > 0 ? filtered.map(m => {
              const tags = extractTags(m);
              const ev = findLinkedCalEvent(m);
              const att = ev ? parseAttendees(ev.attendees) : [];
              return `
              <div class="meeting-card" data-meeting-id="${m.id}">
                <div class="card-row">
                  <div class="card-status-dot ${statusClass(m.status)}"></div>
                  <div class="card-info">
                    <div class="card-title">${esc(m.title)}</div>
                    <div class="card-meta">${icon('clock', 12)} ${fmtDate(m.date)}${m.duration ? ' · ' + fmtDur(m.duration) : ''}</div>
                    ${tags.length ? `<div class="card-tags">${tags.map(t => `<span class="pill">${esc(t)}</span>`).join('')}</div>` : ''}
                  </div>
                  <div class="card-actions">
                    <button class="btn-icon card-del" data-id="${m.id}" title="Delete">${icon('trash', 13)}</button>
                  </div>
                </div>
              </div>`;
            }).join('') : `<div class="empty-state">No meeting notes yet</div>`}
          </div>
        </section>
        `}
      </div>
    </div>`;
}

function getWeekDayPills(): string {
  const today = new Date();
  const todayStr = localDateStr(today);
  const weekStart = new Date(today);
  weekStart.setDate(today.getDate() - today.getDay() + (calWeekOffset * 7));
  const todayDow = today.getDay();
  const isWeekend = todayDow === 0 || todayDow === 6;
  const indices = isWeekend ? [0,1,2,3,4,5,6] : [1,2,3,4,5];
  return indices.map(i => {
    const d = new Date(weekStart);
    d.setDate(weekStart.getDate() + i);
    const ds = localDateStr(d);
    const isToday = ds === todayStr;
    const isActive = calView === ds;
    const dayName = d.toLocaleDateString(undefined, {weekday: 'short'});
    const dayNum = d.getDate();
    const hasEvents = calEvents.some(e => e.start_time.split('T')[0] === ds)
      || meetings.some(m => m.date && localDateStr(new Date(m.date)) === ds && !findLinkedCalEvent(m));
    return '<button class="day-pill' + (isActive ? ' pill-active' : '') + (isToday && !isActive ? ' day-pill-today' : '') + '" data-calview="' + ds + '">'
      + '<span class="day-pill-name">' + dayName + '</span>'
      + '<span class="day-pill-num' + (isToday ? ' day-pill-num-today' : '') + '">' + dayNum + '</span>'
      + (hasEvents ? '<span class="day-pill-dot"></span>' : '')
      + '</button>';
  }).join('');
}

function renderCalView(): string {
  if (!calView) {
    const todayStr = localDateStr(new Date());
    const weekDays = getWeekDays();
    calView = weekDays.includes(todayStr) ? todayStr : weekDays[0];
  }
  return renderCalDay(calView);
}

function getWeekDays(): string[] {
  const today = new Date();
  const weekStart = new Date(today);
  weekStart.setDate(today.getDate() - today.getDay() + (calWeekOffset * 7));
  const todayDow = today.getDay();
  const isWeekend = (calWeekOffset === 0 && (todayDow === 0 || todayDow === 6));
  const indices = isWeekend ? [0,1,2,3,4,5,6] : [1,2,3,4,5];
  return indices.map(i => {
    const d = new Date(weekStart);
    d.setDate(weekStart.getDate() + i);
    return localDateStr(d);
  });
}

function getPrepSnippet(prepDoc: string): string {
  if (!prepDoc) return '';
  try { const o = JSON.parse(prepDoc); if (o.event_id) return ''; } catch {}
  // Look for ## TL;DR section first
  const tldrMatch = prepDoc.match(/## TL;?DR\n+([\s\S]*?)(?=\n## |$)/i);
  if (tldrMatch) {
    const para = tldrMatch[1].trim().replace(/\*\*/g, '').replace(/\n+/g, ' ').slice(0, 400);
    return `<div class="prep-snip-tldr">${esc(para)}</div>`;
  }
  // Fallback: Context & Background paragraph
  const ctxMatch = prepDoc.match(/## Context.*?\n+([\s\S]*?)(?=\n## |$)/i);
  if (ctxMatch) {
    const lines = ctxMatch[1].split('\n').map(l => l.replace(/\*\*/g, '').trim()).filter(l => l && !l.startsWith('---') && !l.startsWith('|'));
    const para = lines.slice(0, 3).join(' ').slice(0, 300);
    return `<div class="prep-snip-tldr">${esc(para)}</div>`;
  }
  return '';
}

function renderCalDay(dateStr: string): string {
  const evs = calEvents.filter(e => e.start_time.split('T')[0] === dateStr);
  const linkedIds = new Set(evs.map(e => e.meeting_id).filter(Boolean));
  // Meetings with no linked CalEvent — synthesize one so they use the same card
  const orphanEvs: CalEvent[] = meetings
    .filter(m => {
      if (!m.date) return false;
      return localDateStr(new Date(m.date)) === dateStr
        && !linkedIds.has(m.id)
        && !findLinkedCalEvent(m);
    })
    .map(m => ({
      id: m.id, title: m.title,
      start_time: m.date, end_time: m.date,
      calendar_name: '', meeting_id: m.id,
      attendees: '[]', prep_status: '', prep_doc: ''
    }));
  const allEvs = [...evs, ...orphanEvs].sort((a, b) => a.start_time.localeCompare(b.start_time));
  if (!allEvs.length) return '<div class="day-empty">No meetings this day</div>';
  return '<div class="day-cards">' + allEvs.map(ev => renderMeetingCard(ev)).join('') + '</div>';
}


function renderMeetingCard(e: CalEvent): string {
  const now = new Date();
  const st = new Date(e.start_time);
  const et = new Date(e.end_time);
  const isLive = now >= st && now <= et;
  const isSoon = !isLive && st.getTime() - now.getTime() < 900000 && st > now;
  const isPast = now > et;
  const linked = e.meeting_id
    ? meetings.find(m => m.id === e.meeting_id)
    : meetings.find(m => m.title.toLowerCase() === e.title.toLowerCase()
        && m.date && m.date.split('T')[0] === e.start_time.split('T')[0]) || null;
  const attendees = parseAttendees(e.attendees);
  const minsLeft = isLive ? Math.round((et.getTime() - now.getTime()) / 60000) : 0;
  const minsTill = isSoon ? Math.round((st.getTime() - now.getTime()) / 60000) : 0;

  // Status
  const statusBadge = isLive
    ? '<span class="mc-badge mc-badge-live"><span class="pulse-dot red"></span>Live \u00b7 ' + minsLeft + 'm left</span>'
    : isSoon
    ? '<span class="mc-badge mc-badge-soon">In ' + minsTill + 'm</span>'
    : isPast
    ? '<span class="mc-badge mc-badge-past">Past</span>'
    : '';

  // Avatars
  const avatarsHtml = attendees.slice(0, 5).map((a, i) =>
    '<div class="mc-avatar" style="background:' + avatarColor(a.name || a.email) + ';z-index:' + (10 - i) + '" title="' + esc(a.name || a.email) + '">' + getInitials(a.name || a.email) + '</div>'
  ).join('');
  const overflow = attendees.length > 5 ? '<span class="mc-avatar-more">+' + (attendees.length - 5) + '</span>' : '';

  // Prep snippet
  const snippet = e.prep_status === 'ready' ? getPrepSnippet(e.prep_doc) : '';
  const snippetHtml = snippet ? '<div class="mc-prep">' + snippet + '</div>' : '';

  // Actions
  const prepBtn = e.prep_status === 'ready'
    ? '<button class="mc-btn mc-btn-glass" onclick="event.stopPropagation();openMeeting(\'' + (linked?.id || e.id) + '\',\'prep\')">View Prep</button>'
    : e.prep_status === 'preparing'
    ? '<button class="mc-btn mc-btn-glass" disabled><span class="spinner-sm"></span> Prepping\u2026</button>'
    : e.prep_status === 'failed'
    ? '<button class="mc-btn mc-btn-warn" onclick="event.stopPropagation();triggerPrep(\'' + e.id + '\')">Retry Prep</button>'
    : '<button class="mc-btn mc-btn-glass" onclick="event.stopPropagation();triggerPrep(\'' + e.id + '\')">\u2726 Prep</button>';

  const actionBtn = linked
    ? '<button class="mc-btn mc-btn-primary" onclick="event.stopPropagation();openMeeting(\'' + linked.id + '\')">View Notes</button>'
    : '<button class="mc-btn mc-btn-primary" onclick="event.stopPropagation();startRecording(\'' + e.id + '\')">\u25b6 Start</button>';

  const cardClass = 'mc' + (isLive ? ' mc-live' : '') + (isSoon ? ' mc-soon' : '') + (isPast ? ' mc-past' : '');
  const clickAttr = linked ? ' onclick="openMeeting(\'' + linked.id + '\')"' : '';

  return '<div class="' + cardClass + '"' + clickAttr + '>' +
    '<div class="mc-inner">' +
      '<div class="mc-left">' +
        '<div class="mc-title-row">' +
          '<span class="mc-title">' + esc(e.title) + '</span>' +
          statusBadge +
        '</div>' +
        '<div class="mc-meta">' +
          '<span class="mc-time">' + fmtTime(e.start_time) + ' \u2013 ' + fmtTime(e.end_time) + '</span>' +
          '<span class="mc-cal">' + esc(e.calendar_name || 'Calendar') + '</span>' +
        '</div>' +
        (attendees.length ? '<div class="mc-avatars">' + avatarsHtml + overflow + '</div>' : '') +
      '</div>' +
      '<div class="mc-right">' +
        prepBtn + actionBtn +
      '</div>' +
    '</div>' +
    (snippet ? '<div class="mc-prep-row">' + snippet + '</div>' : '') +
  '</div>';
}


function renderCalWeek(): string {
  const weekMap = getWeekEvents();
  const now = new Date();
  const todayStr = localDateStr(now);
  const entries = [...weekMap.entries()].filter(([,evs]) => evs.length > 0);
  if (!entries.length) return '<div class="empty-state">No meetings this week</div>';
  return `
    <div class="week-list">
      ${entries.map(([dateStr, evs]) => {
        const d = new Date(dateStr + 'T12:00');
        const isToday = dateStr === todayStr;
        const dayLabel = isToday ? 'Today' : d.toLocaleDateString(undefined, {weekday:'long', month:'short', day:'numeric'});
        return `
        <div class="week-day-group">
          <div class="week-day-heading${isToday ? ' week-day-today' : ''}">${dayLabel}</div>
          <div class="week-day-events">
            ${evs.map(e => {
              const linked = e.meeting_id;
              const prepReady = e.prep_status === 'ready';
              const prepBusy  = e.prep_status === 'preparing';
              const click = linked ? `onclick="openMeeting('${linked}')"` : '';
              return `
              <div class="week-row${linked ? ' week-row-linked' : ''}" ${click}>
                <span class="week-row-time">${fmtTime(e.start_time)}</span>
                <span class="week-row-dot" style="background:${e.calendar_name ? 'var(--accent)' : 'var(--muted)'}"></span>
                <span class="week-row-title">${esc(e.title)}</span>
                ${e.calendar_name ? `<span class="week-row-cal">${esc(e.calendar_name)}</span>` : ''}
                ${linked ? `<span class="week-row-notes">${icon('note', 12)} Notes</span>` : ''}
                <span class="week-row-actions">
                  ${prepReady
                    ? `<button class="week-action-btn" onclick="event.stopPropagation();openMeeting('${linked}')">${icon('sparkle',12)} View Prep</button>`
                    : prepBusy
                    ? `<button class="week-action-btn" disabled>${icon('sparkle',12)} Prepping…</button>`
                    : e.prep_status === 'failed'
              ? `<button class="week-action-btn week-action-warn" onclick="event.stopPropagation();triggerPrep('${e.id}')">${icon('sparkle',12)} Retry</button>`
              : `<button class="week-action-btn" onclick="event.stopPropagation();triggerPrep('${e.id}')">${icon('sparkle',12)} Prep</button>`
                  }
                  <button class="week-action-btn week-action-primary" onclick="event.stopPropagation();startRecording('${e.id}')">${icon('record',12)} Start</button>
                </span>
              </div>`;
            }).join('')}
          </div>
        </div>`;
      }).join('')}
    </div>`;
}
function renderCalMonth(): string {
  const {weeks} = getMonthEvents();
  const now = new Date();
  const monthName = now.toLocaleDateString(undefined, {month: 'long', year: 'numeric'});
  return `
    <div class="month-view">
      <div class="month-header-label">${monthName}</div>
      <div class="month-grid">
        <div class="month-day-labels">
          ${['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map(d => `<div class="month-day-label">${d}</div>`).join('')}
        </div>
        ${weeks.map(week => `
          <div class="month-week">
            ${week.map(cell => `
              <div class="month-cell${cell.isToday ? ' month-today' : ''}${cell.day === 0 ? ' month-cell-empty' : ''}"
                ${cell.day > 0 && cell.events.length ? `onclick="showMonthDay('${cell.date}')" style="cursor:pointer"` : ''}>
                ${cell.day > 0 ? `
                  <div class="month-cell-num${cell.isToday ? ' today-num' : ''}">${cell.day}</div>
                  ${cell.events.length ? `
                    <div class="month-dots">
                      ${cell.events.slice(0, 3).map(e => `<span class="month-dot${e.meeting_id ? ' month-dot-linked' : ''}"></span>`).join('')}
                      ${cell.events.length > 3 ? `<span class="month-dot-more">+${cell.events.length - 3}</span>` : ''}
                    </div>` : ''}
                ` : ''}
              </div>
            `).join('')}
          </div>
        `).join('')}
      </div>
      <div class="month-day-detail" id="month-day-detail"></div>
    </div>`;
}

function showMonthDay(dateStr: string): void {
  const evs = calEvents.filter(e => e.start_time.split('T')[0] === dateStr);
  const detail = document.getElementById('month-day-detail');
  if (!detail || !evs.length) return;
  const d = new Date(dateStr + 'T12:00');
  const label = d.toLocaleDateString(undefined, {weekday:'long', month:'long', day:'numeric'});
  detail.innerHTML = `
    <div class="month-detail-header">${label}</div>
    <div class="week-day-events">
      ${evs.map(e => {
        const linked = e.meeting_id;
        return `
        <div class="week-row${linked ? ' week-row-linked' : ''}" ${linked ? `onclick="openMeeting('${linked}')"` : ''}>
          <span class="week-row-time">${fmtTime(e.start_time)}</span>
          <span class="week-row-dot" style="background:var(--accent)"></span>
          <span class="week-row-title">${esc(e.title)}</span>
          ${e.calendar_name ? `<span class="week-row-cal">${esc(e.calendar_name)}</span>` : ''}
          ${linked ? `<span class="week-row-notes">${icon('note', 12)} Notes</span>` : ''}
          <span class="week-row-actions">
            ${e.prep_status === 'ready'
              ? `<button class="week-action-btn" onclick="event.stopPropagation();openMeeting('${linked}')">${icon('sparkle',12)} View Prep</button>`
              : e.prep_status === 'preparing'
              ? `<button class="week-action-btn" disabled>${icon('sparkle',12)} Prepping…</button>`
              : e.prep_status === 'failed'
              ? `<button class="week-action-btn week-action-warn" onclick="event.stopPropagation();triggerPrep('${e.id}')">${icon('sparkle',12)} Retry</button>`
              : `<button class="week-action-btn" onclick="event.stopPropagation();triggerPrep('${e.id}')">${icon('sparkle',12)} Prep</button>`
            }
            <button class="week-action-btn week-action-primary" onclick="event.stopPropagation();startRecording('${e.id}')">${icon('record',12)} Start</button>
          </span>
        </div>`;
      }).join('')}
    </div>`;
}


function renderPrepView(ev: CalEvent): string {
  const attendees = parseAttendees(ev.attendees);
  const isPreparing = ev.prep_status === 'preparing';
  const isReady = ev.prep_status === 'ready';

  return `
    <div class="meeting-layout">
      <div class="meeting-topbar glass">
        <button class="btn-icon" id="btn-back">${icon('back', 20)}</button>
        <div class="meeting-topbar-title">${icon('sparkle', 16)} Prep: ${esc(ev.title)}</div>
        <div class="topbar-right">
          <span class="cal-time-chip">${fmtTime(ev.start_time)} – ${fmtTime(ev.end_time)}</span>
        </div>
      </div>
      <div class="meeting-body">
        ${attendees.length ? `
        <div class="prep-attendees">
          <div class="prep-section-label">Attendees</div>
          <div class="prep-people">
            ${attendees.slice(0, 12).map(a => `
              <div class="prep-person">
                <div class="avatar" style="background:${avatarColor(a.name || a.email)}">${getInitials(a.name || a.email)}</div>
                <div class="prep-person-info">
                  <div class="prep-person-name">${esc(a.name || a.email.split('@')[0])}</div>
                  <div class="prep-person-email">${esc(a.email)}</div>
                </div>
              </div>
            `).join('')}
          </div>
        </div>` : ''}
        ${isPreparing ? `
          <div class="processing-bar"><div class="spinner"></div><span>Researching attendees, searching memory, and building your prep doc\u2026</span></div>
        ` : isReady ? `
          <div class="notes-editor notes-editable" contenteditable="false">${formatSummary(ev.prep_doc)}</div>
        ` : ev.prep_status === 'failed' ? `
          <div class="prep-empty">
            <p>Prep timed out or failed.</p>
            <button class="btn btn-primary" onclick="triggerPrep('${ev.id}')">Retry Prep</button>
          </div>
        ` : `
          <div class="prep-empty">
            <p>Click <strong>Prep</strong> on a calendar event to generate a prep document with attendee research, prior meeting context, and suggested talking points.</p>
          </div>
        `}
      </div>
    </div>`;
}

function renderMeeting(): string {
  // Check if viewing a prep doc or a calendar event with no linked meeting
  if (selectedCalId) {
    const ev = calEvents.find(e => e.id === selectedCalId);
    if (ev && (activeTab === 'prep' || !meetings.find(x => x.id === selectedId))) {
      return renderPrepView(ev);
    }
  }
  const m = meetings.find(x => x.id === selectedId);
  const ev = m ? findLinkedCalEvent(m) : undefined;
  const isRec = selectedId === recordingId;
  const title = m?.title || 'New Meeting';
  const status = m?.status || (isRec ? 'recording' : '');

  const bodyHtml = isRec ? `
    <div id="notes-editor" class="notes-editor is-empty" contenteditable="true" spellcheck="true"
      data-placeholder="Write your notes\u2026&#10;&#10;Key decisions, action items, context \u2014 whatever matters to you."></div>
  ` : renderDetailBody(m);

  const hasNotes = m?.notes?.trim();
  const hasTranscript = m?.transcript?.trim();
  const showTabs = !isRec && (hasNotes || hasTranscript || ev?.prep_status === 'ready');

  return `
    <div class="meeting-layout">
      <div class="meeting-topbar glass">
        <button class="btn-icon" id="btn-back">${icon('back', 20)}</button>
        <div class="meeting-topbar-title" id="meeting-title" contenteditable="${!isRec}" spellcheck="false">${esc(title)}</div>
        <div class="topbar-right">
          ${isRec ? `
            <span class="rec-indicator">${icon('mic', 14)} <span id="rec-timer">${fmtDur(elapsedSeconds)}</span></span>
            <button class="btn-stop" id="btn-stop">${icon('stop', 14)} Stop Recording</button>
          ` : `
            <span class="status-chip ${statusClass(status)}">${statusLabel(status)}</span>
          `}
        </div>
      </div>
      ${showTabs ? `
      <div class="meeting-tabs">
        <div class="meeting-tabs-left">
          <button class="meeting-tab${activeTab === 'notes' ? ' active' : ''}" data-tab="notes">${icon('note', 14)} Notes</button>
          ${ev?.prep_status === 'ready' ? `<button class="meeting-tab${activeTab === 'prep' ? ' active' : ''}" data-tab="prep">${icon('sparkle', 14)} Prep</button>` : ''}
          ${hasTranscript ? `<button class="meeting-tab${activeTab === 'transcript' ? ' active' : ''}" data-tab="transcript">${icon('mic', 14)} Transcript</button>` : ''}
        </div>
        <div class="meeting-tabs-right">${renderMeetingMeta(m)}</div>
      </div>` : ''}
      <div class="meeting-body">${bodyHtml}</div>
    </div>`;
}

function renderMeetingMeta(m: Meeting): string {
  const tags = extractTags(m);
  const linked = findLinkedCalEvent(m);
  const attendees = linked ? parseAttendees(linked.attendees) : [];
  if (!tags.length && !attendees.length) return '';
  return `<div class="meeting-meta">
    ${tags.length ? `<div class="meeting-meta-tags">${tags.map(t => `<span class="meta-tag">${esc(t)}</span>`).join('')}</div>` : ''}
    ${attendees.length ? `<div class="meeting-meta-people">
      ${attendees.slice(0,8).map(a => `<span class="meta-avatar" style="background:${avatarColor(a.name||a.email)}" title="${esc(a.name||a.email)}">${(a.name||a.email)[0].toUpperCase()}</span>`).join('')}
      ${attendees.length > 8 ? `<span class="meta-avatar-more">+${attendees.length-8}</span>` : ''}
    </div>` : ''}
  </div>`;
}

function renderDetailBody(m: Meeting | undefined): string {
  if (!m) return '<p style="padding:40px;opacity:.4">Meeting not found</p>';
  if (['stopping','recorded','transcribing','pending'].includes(m.status)) {
    const s = m.status;
    const recDone = s !== 'stopping';
    const worActive = s === 'recorded' || s === 'transcribing';
    const worDone = s === 'pending';
    const sumActive = s === 'pending';
    return `
      ${m.notes ? `<div class="notes-editor notes-readonly">${/<[a-z][\s\S]*>/i.test(m.notes) ? m.notes : formatSummary(m.notes)}</div>` : ''}
      <div class="pipeline-progress">
        <div class="pipeline-step ${recDone ? 'done' : 'active'}"><div class="pipeline-step-dot"></div><span>${recDone ? 'Recorded' : 'Saving audio\u2026'}</span></div>
        <div class="pipeline-connector"></div>
        <div class="pipeline-step ${worDone ? 'done' : worActive ? 'active' : ''}"><div class="pipeline-step-dot"></div><span>Transcribing</span></div>
        <div class="pipeline-connector"></div>
        <div class="pipeline-step ${sumActive ? 'active' : ''}"><div class="pipeline-step-dot"></div><span>Summarizing</span></div>
      </div>`;
  }
  if (m.status === 'failed') {
    return `<div class="processing-bar failed"><span>Processing failed. <button class="inline-btn" id="btn-retry-pipeline">Retry</button></span></div>`;
  }
  const hasSummary = m.summary?.trim();
  const hasNotes = m.notes?.trim();

  if (activeTab === 'notes') {
    // Notes tab: show AI summary + user notes merged, or just user notes, or empty
    // Detect if content is already HTML (edited & saved) vs raw markdown (from AI)
    const isHtml = (s: string) => /<[a-z][\s\S]*>/i.test(s);
    const fmt = (s: string) => isHtml(s) ? s : formatSummary(s);
    let content = '';
    if (hasSummary && hasNotes) content = fmt(m.summary) + '<hr style="margin:24px 0;opacity:.15">' + fmt(m.notes);
    else if (hasSummary) content = fmt(m.summary);
    else if (hasNotes) content = fmt(m.notes);
    const empty = !hasSummary && !hasNotes;
    return `<div id="notes-editor" class="notes-editor notes-editable${empty ? ' is-empty' : ''}" contenteditable="true" spellcheck="true" data-placeholder="Add your notes\u2026">${content}</div>`;
  }
  if (activeTab === 'prep') {
    const ev = findLinkedCalEvent(m);
    const prepDoc = ev?.prep_doc || '';
    if (prepDoc) {
      return `<div id="notes-editor" class="notes-editor notes-editable" contenteditable="true" spellcheck="true">${formatSummary(prepDoc)}</div>`;
    }
    return '<p style="padding:40px;opacity:.4">No prep available yet</p>';
  }
  if (activeTab === 'transcript' && m.transcript) {
    return `<div id="notes-editor" class="notes-editor notes-editable" contenteditable="false" spellcheck="false">${formatSummary(m.transcript)}</div>`;
  }
  // Fallback to notes
  return `<div id="notes-editor" class="notes-editor notes-editable is-empty"
      contenteditable="true" spellcheck="true" data-placeholder="Add your notes\u2026"></div>`;
}

function attachListeners(): void {
  // Tab switching
  document.querySelectorAll('.meeting-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      flushSave();
      activeTab = (btn as HTMLElement).dataset.tab as any || 'notes';
      loadAll();
    });
  });
  // Perm modal
  document.getElementById('btn-open-settings')?.addEventListener('click', () => {
    fetch('/api/shell', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({command:"open 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'"})
    }).catch(()=>{});
  });
  document.getElementById('btn-retry-perm')?.addEventListener('click', async () => {
    showPermModal = false;
    const ok = await checkPerm();
    if (!ok) { showPermModal = true; render(); return; }
    startRecording();
  });

  // Home
  document.getElementById('btn-new-rec')?.addEventListener('click', () => startRecording());
  document.getElementById('btn-toggle-bg')?.addEventListener('click', () => toggleBgHero());
  document.getElementById('btn-refresh-bg')?.addEventListener('click', async () => {
    await runJob(BG_JOB).catch(() => {});
    await sleep(2000);
    await loadAll();
  });
  document.querySelectorAll('[data-cal-id]').forEach(btn => {
    btn.addEventListener('click', (e) => { e.stopPropagation(); startRecording((btn as HTMLElement).dataset.calId!); });
  });
  // Prep buttons
  document.querySelectorAll('[data-cal-prep-trigger]').forEach(btn => {
    btn.addEventListener('click', (e) => { e.stopPropagation(); triggerPrep((btn as HTMLElement).dataset.calPrepTrigger!); });
  });
  document.querySelectorAll('[data-cal-prep]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      selectedCalId = (btn as HTMLElement).dataset.calPrep!;
      view = 'meeting'; activeTab = 'prep';
      render();
    });
  });
  
  document.querySelectorAll('[data-page]').forEach(b => b.addEventListener('click', () => { mainPage = (b as HTMLElement).dataset.page as 'meetings' | 'notes'; render(); }));

  document.querySelectorAll('[data-calview]').forEach(b => b.addEventListener('click', () => { calView = (b as HTMLElement).dataset.calview as any; render(); }));


  document.querySelectorAll('[data-filter]').forEach(btn => {
    btn.addEventListener('click', () => { activeFilter = (btn as HTMLElement).dataset.filter as Filter; render(); });
  });
  // Topic dropdown toggle
  document.getElementById('btn-topic-select')?.addEventListener('click', (e) => {
    e.stopPropagation();
    document.getElementById('dropdown-topics')?.classList.toggle('open');
    document.getElementById('dropdown-people')?.classList.remove('open');
  });
  // People dropdown toggle
  document.getElementById('btn-people-select')?.addEventListener('click', (e) => {
    e.stopPropagation();
    document.getElementById('dropdown-people')?.classList.toggle('open');
    document.getElementById('dropdown-topics')?.classList.remove('open');
  });
  // Topic checkbox changes
  document.querySelectorAll('[data-tag]').forEach(cb => {
    cb.addEventListener('change', () => {
      const t = (cb as HTMLInputElement).dataset.tag!;
      if ((cb as HTMLInputElement).checked) { if (!activeTags.includes(t)) activeTags.push(t); }
      else { activeTags = activeTags.filter(x => x !== t); }
      render();
    });
  });
  // People checkbox changes
  document.querySelectorAll('[data-person]').forEach(cb => {
    cb.addEventListener('change', () => {
      const p = (cb as HTMLInputElement).dataset.person!;
      if ((cb as HTMLInputElement).checked) { if (!activePeople.includes(p)) activePeople.push(p); }
      else { activePeople = activePeople.filter(x => x !== p); }
      render();
    });
  });
  // Clear buttons
  document.getElementById('clear-topics')?.addEventListener('click', () => { activeTags = []; render(); });
  document.getElementById('clear-people')?.addEventListener('click', () => { activePeople = []; render(); });
  // Close dropdowns on outside click
  document.addEventListener('click', () => {
    document.querySelectorAll('.filter-dropdown.open').forEach(d => d.classList.remove('open'));
  }, { once: true });
  document.querySelectorAll('.meeting-card').forEach(card => {
    card.addEventListener('click', (e) => {
      if ((e.target as HTMLElement).closest('.delete-btn, .btn-icon')) return;
      openMeeting((card as HTMLElement).dataset.meetingId!);
    });
  });
  document.querySelectorAll('.card-del').forEach(btn => {
    btn.addEventListener('click', (e) => deleteMeeting((btn as HTMLElement).dataset.id!, e));
  });

  // Meeting
  document.getElementById('btn-back')?.addEventListener('click', () => { flushSave(); view = 'home'; loadAll(); });
  document.getElementById('btn-stop')?.addEventListener('click', () => stopRecording());
  document.getElementById('meeting-title')?.addEventListener('blur', async (e) => {
    const el = e.target as HTMLElement;
    if (selectedId && el.textContent?.trim()) {
      await w("UPDATE meetings SET title=?, updated_at=strftime('%s','now') WHERE id=?", [el.textContent.trim(), selectedId]);
    }
  });
  const editor = document.getElementById('notes-editor');
  editor?.addEventListener('input', () => {
    editor.classList.toggle('is-empty', !editor.innerText.trim());
    autoSave();
  });
  document.getElementById('btn-retry-pipeline')?.addEventListener('click', () => {
    if (selectedId) { runJob(WHISPER_JOB).catch(()=>{}); startPoll(selectedId); }
  });
}

// Expose functions called via inline onclick in HTML templates
(window as any).shiftWeek = async (dir: number) => {
  calWeekOffset += dir;
  const today = new Date();
  const todayStr = localDateStr(today);
  const weekStart = new Date(today);
  weekStart.setDate(today.getDate() - today.getDay() + (calWeekOffset * 7));
  const indices = (calWeekOffset === 0 && (today.getDay() === 0 || today.getDay() === 6)) ? [0,1,2,3,4,5,6] : [1,2,3,4,5];
  const days = indices.map(i => { const d = new Date(weekStart); d.setDate(weekStart.getDate() + i); return localDateStr(d); });
  calView = days.includes(todayStr) ? todayStr : days[0];
  render();
  // Fetch calendar events for this week then re-render with fresh data
  runJob(CALENDAR_JOB).catch(() => {});
  await sleep(3000);
  await loadAll();
};
(window as any).openMeeting   = openMeeting;
(window as any).showMonthDay  = showMonthDay;
(window as any).triggerPrep   = triggerPrep;
(window as any).startRecording = startRecording;

// Init
(async () => {
  calView = localDateStr(new Date()); // default to today
  await loadAll(); // show cached events immediately if we have them
  await runJob(CALENDAR_JOB).catch(() => {});
  await runJob(BG_JOB).catch(() => {});
  await sleep(1500);
  await loadAll(); // refresh after the sync job finishes
  await recoverRecordingState();
  await recoverStuckPreps();
  detectLiveLocation().catch(() => {});
})();
