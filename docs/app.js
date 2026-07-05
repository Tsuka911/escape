/* ============================================================
   リアル脱出ゲーム 名古屋 空き状況チェッカー（静的サイト版）

   - 演目メタ情報は週1回ビルドの data/catalog.json から読む
   - 空き状況はブラウザから公式API(api.scrapmagazine.com)を直接ライブ取得する
   - ロジックは旧 scraper.py / app.py からの移植
   ============================================================ */

'use strict';

// ── 定数 ──────────────────────────────────────────────────
const TICKETS_API = 'https://api.scrapmagazine.com/public/api/1/tickets';
const PLACE_NAME = 'リアル脱出ゲーム名古屋店';

const TYPE_OPTIONS = ['ホール型', 'ルーム型', 'その他'];
const TIME_OPTIONS = ['午前', '午後', '夜'];
const EXCLUDE_TITLE_KEYWORDS = ['街歩き'];

// localStorageキー（旧Streamlit版と同名）
const LS = {
  excluded: 'escape_excluded_events',
  lastEvent: 'escape_last_event',
  groupSize: 'escape_group_size',
  filterTypes: 'escape_filter_types',
  filterTimes: 'escape_filter_times',
  hideFull: 'escape_hide_full',
};
const LS_TICKET_PREFIX = 'escape_tickets_';   // 日付ごとのライブ取得キャッシュ
const TICKET_TTL_MS = 10 * 60 * 1000;         // 10分

// 状態の並び順・記号
const STATUS_RANK = { ok: 0, warn: 1, full: 2, unknown: 3 };
const STATUS_MARK = { ok: '○', warn: '△', full: '×', unknown: '－' };
const STATUS_CLASS = { ok: 's-ok', warn: 's-warn', full: 's-full', unknown: 's-unknown' };

const BOOK_ARROW =
  '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" ' +
  'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>';

// ── アプリ状態 ────────────────────────────────────────────
const S = {
  catalog: null,
  activeView: 'event',
  groupSize: 4,
  hideFull: true,
  filterTypes: [],
  filterTimes: [],
  excluded: [],
  selEvent: null,        // 演目から探す/カレンダーで共有する選択中の演目名
  sortMode: '空き多い順',
  range: {},             // {event:{start,end,weekendOnly}, date:{...}}
  cal: { year: null, month: null, selected: null },
  ticketCache: new Map(), // 日付 -> {ts, rows}（セッション内メモリ）
};

// ============================================================
//  純ロジック（scraper.py / app.py からの移植）
// ============================================================

function normalizeTitle(title) {
  let t = (title || '').replace(/^【[^】]*】/, '');
  t = t.replace(/『/g, '「').replace(/』/g, '」');
  t = t.replace(/[\s　]+/g, '');
  return t.trim();
}

function cleanEventName(name) {
  return (name || '').replace(/^【[^】]*】\s*/, '').trim();
}

function isExcludedTitle(name) {
  return EXCLUDE_TITLE_KEYWORDS.some((kw) => (name || '').includes(kw));
}

function slotPeriod(timeStr) {
  const hour = parseInt((timeStr || '').slice(0, 2), 10);
  if (isNaN(hour)) return '午後';
  if (hour < 12) return '午前';
  if (hour < 17) return '午後';
  return '夜';
}

function typeCategory(eventType) {
  return (eventType === 'ホール型' || eventType === 'ルーム型') ? eventType : 'その他';
}

function eventPassesType(eventType, types) {
  if (!types || types.length === 0) return true;
  return types.includes(typeCategory(eventType));
}

function filterSlots(slots, times) {
  if (!times || times.length === 0) return slots;
  return slots.filter((s) => times.includes(slotPeriod(s.time)));
}

// 在庫と人数から [状態キー, 表示テキスト] を返す
function capacityStatus(stock, unit, groupSize) {
  if (stock === null || stock === undefined) return ['unknown', '不明'];
  if (stock === 0) return ['full', '満員'];
  if (unit === '人') {
    if (stock >= groupSize) return ['ok', `残り${stock}人`];
    return ['warn', `残り${stock}人`];
  }
  return ['ok', `残り${stock}組`]; // 「組」単位は1以上あればOK
}

// ライブ取得した演目に、カタログのメタ情報を突合（URL優先→正規化タイトル）
function lookupMeta(eventUrl, eventName) {
  const cat = S.catalog;
  if (!cat) return null;
  if (eventUrl && cat.meta_by_url[eventUrl]) return cat.meta_by_url[eventUrl];
  const norm = normalizeTitle(eventName);
  if (cat.meta_by_title[norm]) return cat.meta_by_title[norm];
  return null;
}

// ── 日付ヘルパー ──────────────────────────────────────────
function pad2(n) { return String(n).padStart(2, '0'); }
function toISO(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`; }
function todayDate() { const d = new Date(); d.setHours(0, 0, 0, 0); return d; }
function parseISO(s) { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); }
function addDays(d, n) { const r = new Date(d); r.setDate(r.getDate() + n); return r; }
const WD_JP = '月火水木金土日';
function weekdayJP(d) { return WD_JP[(d.getDay() + 6) % 7]; }
function isWeekend(d) { return d.getDay() === 0 || d.getDay() === 6; }

function nextSat(offsetWeeks = 0) {
  const t = todayDate();
  const pw = (t.getDay() + 6) % 7;       // Mon=0..Sun=6
  const add = (((5 - pw) % 7) + 7) % 7;  // 次の土曜まで
  return addDays(t, add + offsetWeeks * 7);
}

function fmtMD(d) { return `${d.getMonth() + 1}/${d.getDate()}`; }

// ============================================================
//  公式APIからのライブ取得
// ============================================================

// 1日分の全演目チケットをAPIから取得（pagination込み）→ メタとマージして整形
async function fetchTicketsForDate(dateStr) {
  // メモリキャッシュ
  const mem = S.ticketCache.get(dateStr);
  if (mem && Date.now() - mem.ts < TICKET_TTL_MS) return mem.rows;

  // localStorageキャッシュ（再訪問を速く）
  try {
    const raw = localStorage.getItem(LS_TICKET_PREFIX + dateStr);
    if (raw) {
      const obj = JSON.parse(raw);
      if (Date.now() - obj.ts < TICKET_TTL_MS) {
        S.ticketCache.set(dateStr, obj);
        return obj.rows;
      }
    }
  } catch (e) { /* ignore */ }

  // API取得
  const events = [];
  let page = 1;
  while (true) {
    const params = new URLSearchParams({
      date: dateStr, per: '30', page: String(page),
      place_name: PLACE_NAME, lang: 'ja',
    });
    let data;
    try {
      const resp = await fetch(`${TICKETS_API}?${params.toString()}`);
      if (!resp.ok) break;
      data = await resp.json();
    } catch (e) {
      break;
    }
    (data.events || []).forEach((ev) => events.push(ev));
    const lastPage = data.last_page || 1;
    if (page >= lastPage) break;
    page += 1;
  }

  const rows = integrateRows(dateStr, events);
  const entry = { ts: Date.now(), rows };
  S.ticketCache.set(dateStr, entry);
  try { localStorage.setItem(LS_TICKET_PREFIX + dateStr, JSON.stringify(entry)); } catch (e) { /* quota */ }
  return rows;
}

// APIのevents配列を、画面で使う行に整形（fetch_schedule の1日分相当）
function integrateRows(dateStr, events) {
  const d = parseISO(dateStr);
  const weekday = weekdayJP(d);
  const rows = [];
  for (const ev of events) {
    const name = ev.event_name || '';
    if (isExcludedTitle(name)) continue;
    const meta = lookupMeta(ev.event_url || '', name);
    if (meta && meta.is_anytime) continue; // 随時スタートは除外

    const slots = [];
    for (const t of (ev.tickets || [])) {
      const startsAt = t.starts_at || '';
      if (!startsAt.startsWith(dateStr)) continue;
      slots.push({
        time: startsAt.slice(11, 16),
        stock: t.stock,
        status: t.status,
        ticket_url: t.ticket_url,
      });
    }
    if (slots.length === 0) continue;
    slots.sort((a, b) => a.time.localeCompare(b.time));

    rows.push({
      date: dateStr,
      weekday,
      event_name: cleanEventName(name),
      event_url: ev.event_url,
      tickets_url: ev.tickets_url,
      type: meta ? meta.type : null,
      max_team_size: meta ? meta.max_team_size : null,
      order_unit: ev.order_unit || '組',
      slots,
    });
  }
  return rows;
}

// 期間内の対象日を集めてライブ取得（並列・同時実行数制限つき）
async function fetchSchedule(startISO, endISO, weekendOnly, onProgress) {
  const dates = [];
  let cur = parseISO(startISO);
  const end = parseISO(endISO);
  while (cur <= end) {
    if (!weekendOnly || isWeekend(cur)) dates.push(toISO(cur));
    cur = addDays(cur, 1);
  }

  const all = [];
  let done = 0;
  const CONCURRENCY = 4;
  let idx = 0;
  async function worker() {
    while (idx < dates.length) {
      const myDate = dates[idx++];
      const rows = await fetchTicketsForDate(myDate);
      rows.forEach((r) => all.push(r));
      done += 1;
      if (onProgress) onProgress(done, dates.length);
    }
  }
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, dates.length) }, worker));
  return all;
}

function clearTicketCache() {
  S.ticketCache.clear();
  try {
    const keys = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(LS_TICKET_PREFIX)) keys.push(k);
    }
    keys.forEach((k) => localStorage.removeItem(k));
  } catch (e) { /* ignore */ }
}

// ============================================================
//  localStorage 設定の読み書き
// ============================================================

function loadJSONList(key) {
  try { const v = JSON.parse(localStorage.getItem(key)); return Array.isArray(v) ? v : []; }
  catch (e) { return []; }
}

function loadSettings() {
  const g = parseInt(localStorage.getItem(LS.groupSize), 10);
  S.groupSize = isNaN(g) ? 4 : g;
  const hf = localStorage.getItem(LS.hideFull);
  S.hideFull = hf === null ? true : hf === '1';
  S.filterTypes = loadJSONList(LS.filterTypes).filter((v) => TYPE_OPTIONS.includes(v));
  S.filterTimes = loadJSONList(LS.filterTimes).filter((v) => TIME_OPTIONS.includes(v));
  S.excluded = loadJSONList(LS.excluded);
  const last = localStorage.getItem(LS.lastEvent);
  S.selEvent = last || null;
}

function saveSetting(key, value) {
  try { localStorage.setItem(key, value); } catch (e) { /* ignore */ }
}

// ============================================================
//  小さなDOMヘルパー
// ============================================================
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function el(id) { return document.getElementById(id); }
function root() { return el('viewRoot'); }

// 日付見出し
function dayHeadHTML(d, rightText) {
  const wd = weekdayJP(d);
  const color = wd === '土' ? '#2F6FED' : wd === '日' ? '#D8453D' : '#1A2230';
  return (
    '<div class="day-head">' +
    `<span class="day-date">${d.getMonth() + 1}/${d.getDate()}` +
    `<span style="color:${color};font-weight:700">（${wd}）</span></span>` +
    '<span class="day-rule"></span>' +
    `<span class="day-count">${esc(rightText)}</span>` +
    '</div>'
  );
}

function bookBtn(url) {
  if (!url) return '';
  return `<a class="book-btn" href="${esc(url)}" target="_blank" rel="noopener">予約ページ${BOOK_ARROW}</a>`;
}

// 公演の特集ページ（公式サイトの演目紹介ページ）へのリンク
function detailBtn(url) {
  if (!url) return '';
  return `<a class="detail-btn" href="${esc(url)}" target="_blank" rel="noopener">公演の詳細${BOOK_ARROW}</a>`;
}

function formatEventLabel(e) {
  const extra = [];
  if (e.type) extra.push(e.type);
  if (e.max_team_size) extra.push(`最大${e.max_team_size}人`);
  return e.event_name + (extra.length ? `（${extra.join(' / ')}）` : '');
}

// 除外・種別フィルタ適用後の演目シード一覧（ピッカー用）
function filteredEventList() {
  if (!S.catalog) return [];
  const exSet = new Set(S.excluded);
  return S.catalog.events.filter(
    (e) => !exSet.has(e.event_name) && eventPassesType(e.type, S.filterTypes)
  );
}

// ============================================================
//  設定パネルの構築・配線
// ============================================================
function initSettingsPanel() {
  // 人数
  el('grpVal').textContent = S.groupSize;
  el('grpMinus').onclick = () => { S.groupSize = Math.max(1, S.groupSize - 1); el('grpVal').textContent = S.groupSize; saveSetting(LS.groupSize, S.groupSize); renderActiveView(); };
  el('grpPlus').onclick = () => { S.groupSize = Math.min(20, S.groupSize + 1); el('grpVal').textContent = S.groupSize; saveSetting(LS.groupSize, S.groupSize); renderActiveView(); };

  // 満員非表示
  const hf = el('hideFull');
  hf.checked = S.hideFull;
  hf.onchange = () => { S.hideFull = hf.checked; saveSetting(LS.hideFull, hf.checked ? '1' : '0'); renderActiveView(); };

  // 絞り込み pills
  buildPills('filterTypes', TYPE_OPTIONS, S.filterTypes, (vals) => {
    S.filterTypes = vals; saveSetting(LS.filterTypes, JSON.stringify(vals));
    if (S.selEvent && !filteredEventList().some((e) => e.event_name === S.selEvent)) {
      S.selEvent = null; saveSetting(LS.lastEvent, '');
    }
    renderActiveView();
  });
  buildPills('filterTimes', TIME_OPTIONS, S.filterTimes, (vals) => {
    S.filterTimes = vals; saveSetting(LS.filterTimes, JSON.stringify(vals)); renderActiveView();
  });

  buildExcludeList();

  // 更新ボタン
  el('refreshBtn').onclick = async () => {
    clearTicketCache();
    await loadCatalog(true);
    buildExcludeList();
    renderActiveView();
  };
}

function buildPills(containerId, options, selected, onChange) {
  const c = el(containerId);
  c.innerHTML = '';
  const sel = new Set(selected);
  options.forEach((opt) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'pill' + (sel.has(opt) ? ' on' : '');
    b.textContent = opt;
    b.onclick = () => {
      if (sel.has(opt)) sel.delete(opt); else sel.add(opt);
      b.classList.toggle('on');
      onChange(options.filter((o) => sel.has(o)));
    };
    c.appendChild(b);
  });
}

function buildExcludeList() {
  const c = el('excludeList');
  c.innerHTML = '';
  const names = new Set();
  if (S.catalog) S.catalog.events.forEach((e) => names.add(e.event_name));
  S.excluded.forEach((n) => names.add(n));
  const options = Array.from(names).sort((a, b) => a.localeCompare(b, 'ja'));
  if (options.length === 0) { c.innerHTML = '<div class="muted">演目を読み込めませんでした。</div>'; return; }

  const exSet = new Set(S.excluded);
  options.forEach((name) => {
    const lab = document.createElement('label');
    lab.className = 'check-row';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = exSet.has(name);
    cb.onchange = () => {
      if (cb.checked) exSet.add(name); else exSet.delete(name);
      S.excluded = Array.from(exSet);
      saveSetting(LS.excluded, JSON.stringify(S.excluded));
      renderActiveView();
    };
    lab.appendChild(cb);
    lab.appendChild(document.createTextNode(name));
    c.appendChild(lab);
  });
}

function updatedInfoText(lastFetched) {
  const parts = [];
  if (S.catalog && S.catalog.updated_at) {
    const dt = new Date(S.catalog.updated_at);
    parts.push(`演目情報の更新: ${dt.getFullYear()}/${pad2(dt.getMonth() + 1)}/${pad2(dt.getDate())}`);
  }
  parts.push('空き状況はその場でライブ取得（10分キャッシュ）');
  el('updatedInfo').textContent = parts.join(' ・ ');
}

// ============================================================
//  演目ピッカー（モーダル）
// ============================================================
function openPicker(onPick) {
  const events = filteredEventList();
  const mr = el('modalRoot');
  const items = events.map((e) => {
    const selCls = e.event_name === S.selEvent ? ' sel' : '';
    const sub = [];
    if (e.type) sub.push(e.type);
    if (e.max_team_size) sub.push(`最大${e.max_team_size}人`);
    return `<button class="picker-item${selCls}" data-name="${esc(e.event_name)}">${esc(e.event_name)}` +
      (sub.length ? `<span class="sub">${esc(sub.join(' / '))}</span>` : '') + '</button>';
  }).join('');

  mr.innerHTML =
    '<div class="modal-backdrop" id="pickerBackdrop">' +
    '<div class="modal">' +
    '<div class="modal-head">演目をタップして選ぶ<button class="x" id="pickerClose">&times;</button></div>' +
    `<div class="modal-list">${items || '<div class="muted" style="padding:1rem">演目がありません</div>'}</div>` +
    '</div></div>';

  function close() { mr.innerHTML = ''; }
  el('pickerClose').onclick = close;
  el('pickerBackdrop').onclick = (e) => { if (e.target.id === 'pickerBackdrop') close(); };
  mr.querySelectorAll('.picker-item').forEach((b) => {
    b.onclick = () => { close(); onPick(b.getAttribute('data-name')); };
  });
}

// ============================================================
//  日付範囲（開閉式）
// ============================================================
function ensureRange(viewKey, defaultEndDays) {
  if (!S.range[viewKey]) {
    const t = todayDate();
    S.range[viewKey] = { start: toISO(t), end: toISO(addDays(t, defaultEndDays)), weekendOnly: true };
  }
  return S.range[viewKey];
}

function dateRangeHTML(viewKey) {
  const r = S.range[viewKey];
  const s = parseISO(r.start), e = parseISO(r.end);
  return (
    `<details class="date-range" data-rangekey="${viewKey}">` +
    `<summary>期間：${fmtMD(s)} 〜 ${fmtMD(e)}` +
    '<svg class="chev" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M7 10l5 5 5-5z"/></svg></summary>' +
    '<div class="date-range-body">' +
    '<div class="date-fields">' +
    `<div class="field"><label>開始</label><input type="date" class="r-start" value="${r.start}"></div>` +
    `<div class="field"><label>終了</label><input type="date" class="r-end" value="${r.end}" min="${r.start}"></div>` +
    `<label class="check-row"><input type="checkbox" class="r-weekend" ${r.weekendOnly ? 'checked' : ''}>土日のみ</label>` +
    '</div>' +
    '<div class="quick"><div class="qlabel">クイック選択（土曜日をセット）</div>' +
    '<div class="quick-row"><span class="qlabel">開始</span>' +
    '<button class="chip-btn q" data-q="s0">今週</button><button class="chip-btn q" data-q="s1">来週</button>' +
    '<span class="qlabel" style="margin-left:.5rem">終了</span>' +
    '<button class="chip-btn q" data-q="e0">今週</button><button class="chip-btn q" data-q="e1">来週</button>' +
    '</div></div>' +
    '</div></details>'
  );
}

// 日付範囲のイベント配線。変更時に onChange を呼ぶ（再取得はしない＝ボタン起点）
function wireDateRange(container, viewKey, onChange) {
  const det = container.querySelector(`.date-range[data-rangekey="${viewKey}"]`);
  if (!det) return;
  const r = S.range[viewKey];
  const sIn = det.querySelector('.r-start');
  const eIn = det.querySelector('.r-end');
  const wIn = det.querySelector('.r-weekend');

  function refreshSummary() {
    const s = parseISO(r.start), e = parseISO(r.end);
    det.querySelector('summary').childNodes[0].nodeValue = `期間：${fmtMD(s)} 〜 ${fmtMD(e)}`;
  }
  sIn.onchange = () => {
    r.start = sIn.value;
    if (r.end < r.start) { r.end = r.start; eIn.value = r.end; }
    eIn.min = r.start;
    refreshSummary(); onChange();
  };
  eIn.onchange = () => { r.end = eIn.value; if (r.end < r.start) { r.end = r.start; eIn.value = r.end; } refreshSummary(); onChange(); };
  wIn.onchange = () => { r.weekendOnly = wIn.checked; onChange(); };
  det.querySelectorAll('.chip-btn.q').forEach((b) => {
    b.onclick = (ev) => {
      ev.preventDefault();
      const q = b.getAttribute('data-q');
      const d = nextSat(q.endsWith('1') ? 1 : 0);
      if (q.startsWith('s')) { r.start = toISO(d); if (r.end < r.start) r.end = r.start; }
      else { r.end = toISO(d); if (r.end < r.start) r.start = r.end; }
      sIn.value = r.start; eIn.value = r.end; eIn.min = r.start;
      refreshSummary(); onChange();
    };
  });
}

// 除外中バナー
function excludedBannerHTML() {
  if (!S.excluded.length) return '';
  const chips = S.excluded.map((n) => `<span class="excl-chip">${esc(n)}</span>`).join('');
  return `<details class="excl-details"><summary>除外中の演目（${S.excluded.length}件）</summary>` +
    `<div class="excl-banner">${chips}</div></details>`;
}

function loadingHTML(msg) { return `<div class="loading"><span class="spinner"></span>${esc(msg)}</div>`; }
function notice(msg, kind) { return `<div class="notice ${kind || ''}">${esc(msg)}</div>`; }

// ============================================================
//  ビュー描画
// ============================================================
function renderActiveView() {
  updatedInfoText();
  if (S.activeView === 'event') renderEventView();
  else if (S.activeView === 'date') renderDateView();
  else renderCalendarView();
}

// ── 演目から探す ──
function renderEventView() {
  ensureRange('event', 60);
  const events = filteredEventList();
  const pickerLabel = S.selEvent
    ? `演目：${esc(S.selEvent)}`
    : '<span class="ph">演目を選ぶ</span>';

  let html = `<button class="picker-btn" id="evPicker">` +
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M2 16.5A1.5 1.5 0 0 0 3.5 18h17a1.5 1.5 0 0 0 1.5-1.5v-9A1.5 1.5 0 0 0 20.5 6h-17A1.5 1.5 0 0 0 2 7.5v9z"/></svg>' +
    `${pickerLabel}</button>`;

  if (S.selEvent) {
    html += `<button class="btn" id="evClear" style="margin-top:.5rem"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>選択中の演目をクリア</button>`;
    const selCat = S.catalog.events.find((e) => e.event_name === S.selEvent);
    if (selCat && selCat.event_url) html += `<div style="margin-top:.5rem">${detailBtn(selCat.event_url)}</div>`;
    html += dateRangeHTML('event');
    html += `<button class="btn btn-primary full" id="evSearch" style="margin-top:.6rem"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M15.5 14h-.79l-.28-.27A6.47 6.47 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0A4.5 4.5 0 1 1 14 9.5 4.49 4.49 0 0 1 9.5 14z"/></svg>この条件で空きを検索</button>`;
    html += excludedBannerHTML();
  } else {
    html += notice('上の「演目を選ぶ」から、空き状況を見たい演目を選んでください。');
  }
  html += '<div id="evResult"></div>';

  if (events.length === 0) {
    root().innerHTML = notice('条件に合う演目がありません。設定の種別の絞り込みを見直してください。', 'warn');
    return;
  }
  root().innerHTML = html;

  el('evPicker').onclick = () => openPicker((name) => {
    S.selEvent = name; saveSetting(LS.lastEvent, name); renderEventView();
  });
  if (el('evClear')) el('evClear').onclick = () => { S.selEvent = null; saveSetting(LS.lastEvent, ''); renderEventView(); };
  if (el('evSearch')) el('evSearch').onclick = runEventSearch;
  wireDateRange(root(), 'event', () => { /* 範囲変更は検索ボタンで反映 */ });
}

async function runEventSearch() {
  const ev = S.catalog.events.find((e) => e.event_name === S.selEvent);
  const r = S.range.event;
  const out = el('evResult');
  out.innerHTML = loadingHTML(`「${S.selEvent}」の空き状況をライブ取得中...`);

  let rows;
  try {
    rows = await fetchSchedule(r.start, r.end, r.weekendOnly,
      (done, total) => { out.innerHTML = loadingHTML(`空き状況を取得中... (${done}/${total}日)`); });
  } catch (e) {
    out.innerHTML = notice('データ取得に失敗しました。通信状況を確認して再度お試しください。', 'error');
    return;
  }

  const unit = ev ? ev.order_unit : '組';
  const meta = [];
  if (ev && ev.type) meta.push(['種別', ev.type]);
  if (ev && ev.max_team_size) meta.push(['1チーム最大', `${ev.max_team_size}人`]);
  meta.push(['残数単位', unit]);
  const metaHTML = '<div class="meta-row">' +
    meta.map(([k, v]) => `<span class="meta-chip">${esc(k)} <b>${esc(v)}</b></span>`).join('') + '</div>';

  // 選択演目の行だけ抽出 → 枠を整形
  const target = rows.filter((row) => row.event_name === S.selEvent);
  const tableRows = [];
  for (const row of target) {
    const d = parseISO(row.date);
    for (const s of filterSlots(row.slots, S.filterTimes)) {
      if (S.hideFull && s.stock === 0) continue;
      const [status, text] = capacityStatus(s.stock, unit, S.groupSize);
      tableRows.push({ d, dayLabel: `${d.getMonth() + 1}/${d.getDate()}(${row.weekday})`, time: s.time, text, status, url: s.ticket_url || '' });
    }
  }

  if (tableRows.length === 0) {
    out.innerHTML = metaHTML + notice('指定期間内に表示できる空き枠が見つかりませんでした。期間を広げるか「土日のみ」を外してみてください。');
    return;
  }
  tableRows.sort((a, b) => (a.d - b.d) || a.time.localeCompare(b.time));

  // 日付ごとにグループ化
  const byDay = new Map();
  for (const tr of tableRows) { if (!byDay.has(tr.dayLabel)) byDay.set(tr.dayLabel, []); byDay.get(tr.dayLabel).push(tr); }

  let html = metaHTML;
  for (const [, items] of byDay) {
    html += dayHeadHTML(items[0].d, `空き ${items.length} 枠`);
    const cards = items.map((it) =>
      '<div class="slot-card">' +
      `<div class="slot-time">${esc(it.time)}</div>` +
      `<span class="badge ${STATUS_CLASS[it.status]}">${esc(it.text)}</span>` +
      bookBtn(it.url) + '</div>'
    ).join('');
    html += `<div class="card-grid grid-slots">${cards}</div>`;
  }
  html += `<div class="foot-note">${tableRows.length} 件表示</div>`;
  out.innerHTML = html;
}

// ── 日付から探す ──
function renderDateView() {
  ensureRange('date', 30);
  let html = dateRangeHTML('date');
  html += excludedBannerHTML();
  html += '<div style="margin:.6rem 0"><div class="muted" style="margin-bottom:.3rem">並び順</div>' +
    '<div class="segmented" id="sortSeg">' +
    `<button data-sort="空き多い順" class="${S.sortMode === '空き多い順' ? 'on' : ''}">空き多い順</button>` +
    `<button data-sort="演目名順" class="${S.sortMode === '演目名順' ? 'on' : ''}">演目名順</button>` +
    '</div></div>';
  html += `<button class="btn btn-primary full" id="dateSearch"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M15.5 14h-.79l-.28-.27A6.47 6.47 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0A4.5 4.5 0 1 1 14 9.5 4.49 4.49 0 0 1 9.5 14z"/></svg>この期間で空きを検索</button>`;
  html += '<div class="foot-note">○=参加人数OK / △=人数に対し残席不足の可能性 / ×=満員</div>';
  html += '<div id="dateResult"></div>';
  root().innerHTML = html;

  wireDateRange(root(), 'date', () => {});
  el('sortSeg').querySelectorAll('button').forEach((b) => {
    b.onclick = () => {
      S.sortMode = b.getAttribute('data-sort');
      el('sortSeg').querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b));
      // 既に結果がある場合は並べ替えのため再描画（再取得しない）
      if (el('dateResult').dataset.loaded === '1') renderDateResult();
    };
  });
  el('dateSearch').onclick = runDateSearch;
}

let _dateRowsCache = null;
async function runDateSearch() {
  const r = S.range.date;
  const out = el('dateResult');
  out.dataset.loaded = '0';
  out.innerHTML = loadingHTML('空き状況をライブ取得中...');
  try {
    _dateRowsCache = await fetchSchedule(r.start, r.end, r.weekendOnly,
      (done, total) => { out.innerHTML = loadingHTML(`空き状況を取得中... (${done}/${total}日)`); });
  } catch (e) {
    out.innerHTML = notice('データ取得に失敗しました。通信状況を確認して再度お試しください。', 'error');
    return;
  }
  out.dataset.loaded = '1';
  renderDateResult();
}

function renderDateResult() {
  const out = el('dateResult');
  if (!_dateRowsCache) return;
  const exSet = new Set(S.excluded);
  const byDate = new Map();
  for (const row of _dateRowsCache) {
    if (exSet.has(row.event_name)) continue;
    if (!byDate.has(row.date)) byDate.set(row.date, []);
    byDate.get(row.date).push(row);
  }
  const dates = Array.from(byDate.keys()).sort();
  let html = '';
  let shown = 0;
  for (const ds of dates) {
    const block = dayEventCardsHTML(parseISO(ds), byDate.get(ds));
    if (block) { html += block; shown += 1; }
  }
  out.innerHTML = shown === 0
    ? notice('条件に合う空き枠のある演目が見つかりませんでした。絞り込みや期間を見直してみてください。')
    : html;
}

// 1日分の演目カード（build_day_events + render_day_event_cards 相当）
function buildDayEvents(dayRows) {
  const rendered = [];
  for (const r of dayRows) {
    if (!eventPassesType(r.type, S.filterTypes)) continue;
    const unit = r.order_unit;
    const slots = filterSlots(r.slots, S.filterTimes);
    const slotsInfo = [];
    const ranks = [];
    for (const s of slots) {
      const [status] = capacityStatus(s.stock, unit, S.groupSize);
      ranks.push(STATUS_RANK[status]);
      if (S.hideFull && s.stock === 0) continue;
      const stockStr = s.stock === 0 ? '満' : `${s.stock}${unit}`;
      slotsInfo.push({ label: `${STATUS_MARK[status]} ${s.time}（${stockStr}）`, status });
    }
    if (slotsInfo.length === 0) continue;
    const bestRank = ranks.length ? Math.min(...ranks) : 3;
    const metaParts = [];
    if (r.type) metaParts.push(r.type);
    if (r.max_team_size) metaParts.push(`最大${r.max_team_size}人`);
    rendered.push({ event_name: r.event_name, meta: metaParts.join(' ・ '), slots: slotsInfo, url: r.tickets_url || '', event_url: r.event_url || '', rank: bestRank });
  }
  return rendered;
}

function dayEventCardsHTML(d, dayRows) {
  const rendered = buildDayEvents(dayRows);
  if (rendered.length === 0) return '';
  if (S.sortMode === '演目名順') rendered.sort((a, b) => a.event_name.localeCompare(b.event_name, 'ja'));
  else rendered.sort((a, b) => a.rank - b.rank);

  let html = dayHeadHTML(d, `${rendered.length} 演目`);
  const cards = rendered.map((it) => {
    const chips = it.slots.map((si) => `<span class="chip ${STATUS_CLASS[si.status]}">${esc(si.label)}</span>`).join('');
    const metaHTML = it.meta ? `<div class="event-meta">${esc(it.meta)}</div>` : '';
    const links = it.event_url
      ? `<div class="card-links">${bookBtn(it.url)}${detailBtn(it.event_url)}</div>`
      : bookBtn(it.url);
    return '<div class="event-card">' +
      `<div class="event-name">${esc(it.event_name)}</div>${metaHTML}` +
      `<div class="slot-chips">${chips}</div>${links}</div>`;
  }).join('');
  html += `<div class="card-grid grid-events">${cards}</div>`;
  return html;
}

// ── カレンダー ──
function renderCalendarView() {
  const events = filteredEventList();
  if (S.cal.year === null) { const t = todayDate(); S.cal.year = t.getFullYear(); S.cal.month = t.getMonth() + 1; }

  let html = `<button class="picker-btn" id="calPicker">` +
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M2 16.5A1.5 1.5 0 0 0 3.5 18h17a1.5 1.5 0 0 0 1.5-1.5v-9A1.5 1.5 0 0 0 20.5 6h-17A1.5 1.5 0 0 0 2 7.5v9z"/></svg>' +
    (S.selEvent ? `演目：${esc(S.selEvent)}` : '<span class="ph">演目を選ぶ</span>') + '</button>';

  if (events.length === 0) {
    root().innerHTML = notice('条件に合う演目がありません。設定の種別の絞り込みを見直してください。', 'warn');
    return;
  }
  if (!S.selEvent) {
    html += notice('上の「演目を選ぶ」から、カレンダーで見たい演目を選んでください。');
    root().innerHTML = html;
    el('calPicker').onclick = () => openPicker((name) => { S.selEvent = name; saveSetting(LS.lastEvent, name); renderCalendarView(); });
    return;
  }

  html += `<button class="btn" id="calClear" style="margin-top:.5rem"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>選択中の演目をクリア</button>`;
  const calCat = S.catalog.events.find((e) => e.event_name === S.selEvent);
  if (calCat && calCat.event_url) html += `<div style="margin-top:.5rem">${detailBtn(calCat.event_url)}</div>`;
  html += '<div class="cal-nav">' +
    '<button class="btn" id="calPrev">前の月</button>' +
    `<div class="label">${S.cal.year}年${S.cal.month}月</div>` +
    '<button class="btn" id="calNext">次の月</button></div>';
  html += '<div class="cal-legend">' +
    '<span><i style="background:var(--cal-ok)"></i>空きあり</span>' +
    '<span><i style="background:var(--cal-warn)"></i>残りわずか</span>' +
    '<span><i style="background:var(--cal-full)"></i>満員</span>' +
    '<span><i style="background:var(--cal-none)"></i>開催なし</span></div>';
  html += '<div id="calBody">' + loadingHTML('カレンダーを読み込み中...') + '</div>';
  root().innerHTML = html;

  el('calPicker').onclick = () => openPicker((name) => { S.selEvent = name; saveSetting(LS.lastEvent, name); renderCalendarView(); });
  el('calClear').onclick = () => { S.selEvent = null; saveSetting(LS.lastEvent, ''); renderCalendarView(); };
  el('calPrev').onclick = () => { shiftMonth(-1); renderCalendarView(); };
  el('calNext').onclick = () => { shiftMonth(1); renderCalendarView(); };

  loadCalendarBody();
}

function shiftMonth(delta) {
  let m = S.cal.month + delta;
  let y = S.cal.year + Math.floor((m - 1) / 12);
  m = ((m - 1) % 12 + 12) % 12 + 1;
  S.cal.year = y; S.cal.month = m; S.cal.selected = null;
}

async function loadCalendarBody() {
  const cy = S.cal.year, cm = S.cal.month;
  const monthStart = toISO(new Date(cy, cm - 1, 1));
  const lastDay = new Date(cy, cm, 0).getDate();
  const monthEnd = toISO(new Date(cy, cm - 1, lastDay));
  const body = el('calBody');

  let rows;
  try {
    rows = await fetchSchedule(monthStart, monthEnd, false,
      (done, total) => { body.innerHTML = loadingHTML(`${cy}年${cm}月を取得中... (${done}/${total}日)`); });
  } catch (e) {
    body.innerHTML = notice('データ取得に失敗しました。', 'error');
    return;
  }
  // 画面が切り替わっていたら破棄
  if (S.activeView !== 'calendar' || S.cal.year !== cy || S.cal.month !== cm) return;

  const ev = S.catalog.events.find((e) => e.event_name === S.selEvent);
  const unit = ev ? ev.order_unit : '組';

  const slotsByDate = {};
  for (const r of rows) {
    if (r.event_name !== S.selEvent) continue;
    (slotsByDate[r.date] = slotsByDate[r.date] || []).push(...r.slots);
  }
  const statusByDate = {};
  for (const ds in slotsByDate) {
    const fslots = filterSlots(slotsByDate[ds], S.filterTimes);
    if (fslots.length === 0) continue;
    let best = 'unknown';
    for (const s of fslots) {
      const [st] = capacityStatus(s.stock, unit, S.groupSize);
      if (STATUS_RANK[st] < STATUS_RANK[best]) best = st;
    }
    statusByDate[ds] = best;
  }

  // グリッド構築（日曜始まり）
  const weekHead = ['日', '月', '火', '水', '木', '金', '土'];
  let html = '<div class="cal-grid">';
  weekHead.forEach((w, i) => {
    const cls = i === 0 ? ' sun' : i === 6 ? ' sat' : '';
    html += `<div class="cal-head${cls}">${w}</div>`;
  });
  const firstDow = new Date(cy, cm - 1, 1).getDay(); // 0=日
  for (let i = 0; i < firstDow; i++) html += '<div class="cal-cell empty"></div>';
  const today = todayDate();
  for (let day = 1; day <= lastDay; day++) {
    const d = new Date(cy, cm - 1, day);
    const ds = toISO(d);
    const isPast = d < today;
    const st = statusByDate[ds];
    let cls = 'cal-cell';
    if (isPast) cls += ' past';
    else if (st) cls += ' ' + STATUS_CLASS[st].replace('s-', 's-'); // s-ok/s-warn/s-full
    else cls += ' s-none';
    if (S.cal.selected === ds) cls += ' selected';
    const dis = isPast ? ' data-past="1"' : '';
    html += `<button class="${cls}" data-date="${ds}"${dis}>${day}</button>`;
  }
  html += '</div>';
  html += '<div class="foot-note">色のついた日付をタップすると、その日の時間枠を表示します。</div>';
  html += '<div id="calDrill"></div>';
  body.innerHTML = html;

  body.querySelectorAll('.cal-cell[data-date]').forEach((b) => {
    if (b.getAttribute('data-past') === '1') return;
    b.onclick = () => {
      S.cal.selected = b.getAttribute('data-date');
      body.querySelectorAll('.cal-cell').forEach((x) => x.classList.toggle('selected', x === b));
      renderCalDrill(slotsByDate, ev, unit);
    };
  });
  if (S.cal.selected) renderCalDrill(slotsByDate, ev, unit);
}

function renderCalDrill(slotsByDate, ev, unit) {
  const drill = el('calDrill');
  if (!drill) return;
  const ds = S.cal.selected;
  const d = parseISO(ds);
  let slots = filterSlots(slotsByDate[ds] || [], S.filterTimes).slice().sort((a, b) => a.time.localeCompare(b.time));
  let html = '<hr style="border:none;border-top:1px solid var(--border);margin:1rem 0">';
  html += dayHeadHTML(d, ev ? formatEventLabel(ev) : '');
  if (slots.length === 0) {
    html += notice('この日にこの演目の枠はありませんでした。');
  } else {
    const cards = slots.map((s) => {
      const [status, text] = capacityStatus(s.stock, unit, S.groupSize);
      return '<div class="slot-card">' +
        `<div class="slot-time">${esc(s.time)}</div>` +
        `<span class="badge ${STATUS_CLASS[status]}">${esc(text)}</span>` +
        bookBtn(s.ticket_url || '') + '</div>';
    }).join('');
    html += `<div class="card-grid grid-slots">${cards}</div>`;
  }
  drill.innerHTML = html;
}

// ============================================================
//  起動
// ============================================================
async function loadCatalog(forceFresh) {
  try {
    const url = 'data/catalog.json' + (forceFresh ? `?t=${Date.now()}` : '');
    const resp = await fetch(url, { cache: forceFresh ? 'no-store' : 'default' });
    S.catalog = await resp.json();
  } catch (e) {
    S.catalog = { updated_at: null, events: [], meta_by_url: {}, meta_by_title: {} };
  }
}

function wireViewSwitch() {
  el('viewSwitch').querySelectorAll('.view-btn').forEach((b) => {
    b.onclick = () => {
      S.activeView = b.getAttribute('data-view');
      el('viewSwitch').querySelectorAll('.view-btn').forEach((x) => x.classList.toggle('active', x === b));
      renderActiveView();
    };
  });
}

async function boot() {
  loadSettings();
  wireViewSwitch();
  await loadCatalog(false);
  // 選択中の演目が一覧に無ければ未選択に戻す
  if (S.selEvent && !S.catalog.events.some((e) => e.event_name === S.selEvent)) S.selEvent = null;
  initSettingsPanel();
  renderActiveView();
}

boot();
