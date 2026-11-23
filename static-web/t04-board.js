(function () {
  'use strict';
  const Core = window.T04Core;
  if (!Core) return;

  const $ = (id) => document.getElementById(id);
  const kstFmt = new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
  });
  const toKst = (iso) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '(해석할 수 없는 시각)' : `${kstFmt.format(d)} KST`;
  };
  const num = (n, digits) => (digits == null ? String(+Number(n).toFixed(2)) : Number(n).toFixed(digits));

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function table(rows, cls) {
    const t = el('table', `t04-table ${cls || ''}`);
    const body = el('tbody');
    for (const [k, v, id] of rows) {
      const tr = el('tr');
      tr.appendChild(el('th', null, k)).scope = 'row';
      const td = el('td');
      if (v instanceof Node) td.appendChild(v); else td.textContent = v;
      if (id) td.id = id;
      tr.appendChild(td);
      body.appendChild(tr);
    }
    t.appendChild(body);
    return t;
  }
  function link(url) {
    if (typeof url === 'string' && url.startsWith('https://')) {
      const a = el('a', null, url);
      a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer';
      return a;
    }
    return el('span', null, String(url));
  }
  // 변화량 문구: comparison 객체 하나만 보고 만든다(방향은 comparison.direction).
  function cmpText(c, digits) {
    if (c.state === 'insufficient') return '비교할 이전 날짜 없음(기록 2일째부터 표시)';
    if (c.state === 'unit_mismatch') return '단위가 달라 비교하지 않음';
    if (c.direction === 'unchanged') return `0 ${c.unit} (변화 없음)`;
    return `${c.direction === 'increase' ? '+' : '−'}${num(c.magnitude, digits)} ${c.unit}`;
  }

  /* ───────── ① 실제 기록 ───────── */
  async function renderReal() {
    const box = $('t04Real');
    box.textContent = '';
    let rows;
    try {
      const res = await fetch('data/t04/daily.json', { cache: 'no-store' });
      if (res.status === 404) rows = [];
      else if (!res.ok) throw new Error(String(res.status));
      else {
        rows = (await res.json()).rows;
        if (!Array.isArray(rows)) throw new Error('rows');
        rows.forEach((r) => Core.validateNormalizedReading(r.reading));
      }
    } catch (_) {
      box.appendChild(el('p', 't04-msg t04-msg-err',
        '기록 파일을 불러오지 못했습니다. 파일로 직접 열었다면 정적 서버로 여세요.'));
      return;
    }
    if (!rows.length) {
      box.appendChild(el('p', 't04-msg', '아직 실제 기록이 없습니다. 하루 1회 자동 기록 뒤 표시됩니다.'));
      return;
    }
    rows.sort((a, b) => a.reading.record_date.localeCompare(b.reading.record_date));
    const last = rows[rows.length - 1];
    const { reading: r, raw } = last;
    const sameRows = rows.filter((x) => x.reading.signal_id === r.signal_id);
    const cmp = Core.comparisonFor(sameRows.map((x) => x.reading), r);
    const age = Math.round((Date.parse(Core.kstDate(new Date().toISOString())) - Date.parse(r.record_date)) / 86400000);

    if (last.hourly && last.target_date) { renderForecast(box, sameRows, last, age); return; }
    const value = el('p', 't04-bigvalue');
    const vSpan = el('span', null, String(r.normalized_value)); vSpan.id = 't04ScreenVal';
    const uSpan = el('span', 't04-unit', r.unit); uSpan.id = 't04ScreenUnit';
    value.append(vSpan, ' ', uSpan);
    box.appendChild(value);
    if (age >= 2) {
      box.appendChild(el('p', 't04-msg t04-msg-warn', `마지막 기록이 ${age}일 전입니다. 자동 기록이 멈췄을 수 있습니다.`));
    }
    box.appendChild(el('p', 't04-note', '마지막 조회 값입니다. 같은 날 다시 조회하면 값이 바뀔 수 있고, 그것이 정상입니다.'));

    box.appendChild(table([
      ['출처', r.source_name],
      ['출처 URL', link(r.source_url)],
      ['출처 시각(source_time)', r.source_time ? `${r.source_time} (${toKst(r.source_time)})` : '원천이 시각을 주지 않음'],
      ['조회 시각(fetched_at)', `${r.fetched_at} (UTC) = ${toKst(r.fetched_at)}`],
      ['기준 시간대', r.record_timezone],
      ['기록 날짜(record_date)', r.record_date],
      ['전일 대비', cmpText(cmp, 1)]
    ]));

    // 3자 대조: 화면값은 위에서 그린 DOM 숫자를 다시 읽는다.
    const rawVal = raw?.current?.temperature_2m;
    const rawUnit = raw?.current_units?.temperature_2m;
    const screenVal = parseFloat(vSpan.textContent);
    const screenUnit = uSpan.textContent;
    const same = rawVal === r.normalized_value && screenVal === r.normalized_value &&
      rawUnit === r.unit && screenUnit === r.unit;
    const t = el('table', 't04-table t04-three');
    t.appendChild(el('caption', null, '값 대조(원본 · 저장값 · 화면값)'));
    const head = el('thead'); const hr = el('tr');
    ['원본(raw.current.temperature_2m, raw.current_units.temperature_2m)',
      '저장값(reading.normalized_value, unit)', '화면값(DOM에 그려진 숫자를 다시 읽은 값)']
      .forEach((h) => hr.appendChild(el('th', null, h)).scope = 'col');
    head.appendChild(hr); t.appendChild(head);
    const tb = el('tbody'); const tr = el('tr');
    [`${rawVal} ${rawUnit}`, `${r.normalized_value} ${r.unit}`, `${screenVal} ${screenUnit}`]
      .forEach((v) => tr.appendChild(el('td', null, v)));
    tb.appendChild(tr); t.appendChild(tb);
    const wrap = el('div', 't04-scroll'); wrap.tabIndex = 0; wrap.setAttribute('role', 'region');
    wrap.setAttribute('aria-label', '값 대조 표'); wrap.appendChild(t);
    box.appendChild(wrap);
    box.appendChild(el('p', `t04-verdict ${same ? 't04-ok' : 't04-bad'}`, `세 값 ${same ? '일치' : '불일치'}`));
    box.appendChild(el('p', 't04-msg', '이 기록에는 시간별 예보가 없습니다.'));
  }

  const ITEMS = [['temperature_2m', '기온'], ['precipitation', '강수'], ['snowfall', '적설']];
  const r2 = (x) => +Number(x).toFixed(2);
  const arrow = (d) => (d > 0 ? `▲ +${r2(d)}` : d < 0 ? `▼ −${r2(-d)}` : '＝ 0');
  function scrollWrap(t, label) {
    const w = el('div', 't04-scroll'); w.tabIndex = 0; w.setAttribute('role', 'region');
    w.setAttribute('aria-label', label); w.appendChild(t); return w;
  }
  function gridTable(caption, heads, bodyRows) {
    const t = el('table', 't04-table t04-grid');
    t.appendChild(el('caption', null, caption));
    const hr = el('tr');
    heads.forEach((h) => { hr.appendChild(el('th', null, h)).scope = 'col'; });
    t.appendChild(el('thead')).appendChild(hr);
    const tb = el('tbody');
    bodyRows.forEach((cells) => {
      const tr = el('tr');
      cells.forEach((c, i) => {
        const x = el(i === 0 ? 'th' : 'td', null, String(c));
        if (i === 0) x.scope = 'row';
        tr.appendChild(x);
      });
      tb.appendChild(tr);
    });
    t.appendChild(tb);
    return t;
  }

  const REASON = {
    no_previous: '비교할 이전 날짜 없음(기록 2일째부터 표시)',
    unit_mismatch: '단위가 달라 비교하지 않음',
    incomplete: '시간별 값이 24칸이 아니거나 비어 있어 비교하지 않음'
  };

  function renderCompare(box, sameRows, last, u, hh) {
    box.appendChild(el('h3', null, '전일 예보와 24시간 비교'));
    if (typeof Core.compareHourly !== 'function' || typeof Core.previousRow !== 'function') {
      box.appendChild(el('p', 't04-msg t04-msg-err', '비교 기능을 불러오지 못했습니다.'));
      return;
    }
    const prev = Core.previousRow(sameRows, last);
    const c = prev ? Core.compareHourly(prev, last) : { comparable: false, reason: 'no_previous' };
    if (!c.comparable) {
      box.appendChild(el('p', 't04-msg', REASON[c.reason] || '비교할 수 없음'));
      return;
    }
    box.appendChild(el('p', 't04-note',
      `비교 대상: 이전 예보(조회 ${prev.reading.record_date}, 대상일 ${prev.target_date})와 이번 예보(대상일 ${last.target_date})`));
    const s = c.summary;
    const tu = u('temperature_2m');
    box.appendChild(table([
      ['평균 기온 차이(시간별 차이의 평균)', `${arrow(s.mean_delta)} ${tu}`],
      ['저장한 대표값(소수 첫째 자리) 차이', `${arrow(+(last.reading.normalized_value - prev.reading.normalized_value).toFixed(1))} ${tu} (${prev.reading.normalized_value} → ${last.reading.normalized_value})`],
      ['가장 크게 달라진 시각', `${hh(s.hour_of_max_abs)} (기온 차이 ${arrow(c.hours[s.hour_of_max_abs]?.delta?.temperature_2m ?? 0)} ${tu})`]
    ]));
    for (const [k, n] of ITEMS) {
      box.appendChild(scrollWrap(gridTable(`${n} 비교(${u(k)})`, ['시각', '이전 예보', '이번 예보', '차이'],
        c.hours.map((x) => [hh(x.hour), x.prev[k], x.curr[k], arrow(x.delta[k])])), `${n} 비교 표`));
    }
  }

  function renderForecast(box, sameRows, last, age) {
    const { reading: r, raw, hourly: h, target_date: td } = last;
    const u = (k) => (last.hourly_units || {})[k] || '';
    const hh = (i) => `${String(i).padStart(2, '0')}시`;

    const value = el('p', 't04-bigvalue');
    const vSpan = el('span', null, String(r.normalized_value)); vSpan.id = 't04ScreenVal';
    const uSpan = el('span', 't04-unit', r.unit); uSpan.id = 't04ScreenUnit';
    value.append(vSpan, ' ', uSpan);
    box.appendChild(el('p', 't04-note', '대상일 24시간 평균 기온(예보)'));
    box.appendChild(value);
    if (age >= 2) box.appendChild(el('p', 't04-msg t04-msg-warn', `마지막 기록이 ${age}일 전입니다. 자동 기록이 멈췄을 수 있습니다.`));
    box.appendChild(el('p', 't04-note',
      `예보 대상일은 ${td}이고, 조회한 날(${r.record_date})과 다릅니다. 같은 날 다시 조회하면 예보 값이 바뀔 수 있고, 그것이 정상입니다.`));
    box.appendChild(table([
      ['예보 대상일(target_date)', td],
      ['출처', r.source_name],
      ['출처 URL', link(r.source_url)],
      ['예보 기준 시각(대상일 00:00 KST)', r.source_time ? `${r.source_time} (${toKst(r.source_time)})` : '원천이 시각을 주지 않음'],
      ['조회 시각(fetched_at)', `${r.fetched_at} (UTC) = ${toKst(r.fetched_at)}`],
      ['기준 시간대', r.record_timezone],
      ['조회 날짜(record_date)', r.record_date]
    ]));

    box.appendChild(el('h3', null, `${td} 24시간 예보`));
    box.appendChild(scrollWrap(gridTable(`${td} 시간별 예보`,
      ['시각', ...ITEMS.map(([k, n]) => `${n}(${u(k)})`)],
      Array.from({ length: 24 }, (_, i) => [hh(i), ...ITEMS.map(([k]) => (h[k] ? h[k][i] : '—'))])), '24시간 예보 표'));

    renderCompare(box, sameRows, last, u, hh);

    // 3자 대조: 화면 평균은 위에 그린 DOM 숫자를 다시 읽는다.
    const rt = raw?.hourly?.time || [];
    const idx = rt.map((t, i) => (String(t).startsWith(td) ? i : -1)).filter((i) => i >= 0);
    const rawCol = (k) => idx.map((i) => raw.hourly[k]?.[i]);
    const have24 = idx.length === 24;
    const rawMean = have24 ? rawCol('temperature_2m').reduce((a, b) => a + b, 0) / 24 : NaN;
    const screenVal = parseFloat(vSpan.textContent);
    const screenUnit = uSpan.textContent;
    const cellsSame = have24 && ITEMS.every(([k]) => Array.isArray(h[k]) && h[k].length === 24 &&
      rawCol(k).every((v, i) => v === h[k][i]));
    const canRound = typeof Core.roundToTenth === 'function';
    const rounded = have24 && canRound ? Core.roundToTenth(rawMean) : null;
    const meanSame = have24 && canRound && rounded === r.normalized_value && screenVal === r.normalized_value &&
      screenUnit === r.unit && raw.hourly_units?.temperature_2m === r.unit;
    box.appendChild(scrollWrap(gridTable('값 대조(원본 · 저장값 · 화면값)',
      ['원본(raw.hourly 대상일 24칸 평균)', '저장값(reading.normalized_value, unit)', '화면값(DOM에서 다시 읽은 값)'],
      [[!have24 ? '대상일 24칸을 찾지 못함' : !canRound ? '반올림 기능을 불러오지 못했습니다'
          : `${r2(rawMean)} → 소수 첫째 자리 반올림 → ${rounded} ${raw.hourly_units?.temperature_2m ?? ''}`,
        `${r.normalized_value} ${r.unit}`, `${screenVal} ${screenUnit}`]]), '값 대조 표'));
    box.appendChild(el('p', `t04-verdict ${meanSame ? 't04-ok' : 't04-bad'}`, canRound ? `평균 대조: ${meanSame ? '일치' : '불일치'}` : '평균 대조: 비교 불가(반올림 기능을 불러오지 못했습니다)'));
    box.appendChild(el('p', `t04-verdict ${cellsSame ? 't04-ok' : 't04-bad'}`,
      `저장한 24칸(기온·강수·적설)과 원본 같은 날짜 칸 대조: ${cellsSame ? '일치' : '불일치'}`));
  }

  /* ───────── ② 합성 재생 ───────── */
  let state = Core.resetState();   // 메모리 객체만 사용. 저장소·daily.json 쓰기 없음.
  let stage = 0;                   // 순서대로 재생한 정상 fixture 수(0~3)
  let log = [];
  let compare = null;              // {before, after}
  let fixtureError = false;
  let busy = false;
  let fileMap = null;
  const cache = {};
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const SHORT = { D1A: 'T04-NORMAL-D1-A', D1B: 'T04-NORMAL-D1-B', D2: 'T04-NORMAL-D2', RECOVER: 'T04-RECOVER-D2' };

  async function loadFixture(id) {
    if (cache[id]) return cache[id];
    if (!fileMap) {
      const m = await (await fetch('data/t04/fixture-manifest.json')).json();
      fileMap = Object.fromEntries(m.fixtures.map((f) => [f.fixture_id, f.file]));
    }
    const res = await fetch(`data/t04/fixtures/${fileMap[id]}`);
    if (!res.ok) throw new Error(String(res.status));
    return (cache[id] = await res.json());
  }

  async function play(id) {
    let fx;
    try { fx = await loadFixture(id); } catch (_) { fixtureError = true; render(); return false; }
    fixtureError = false;
    const before = state.daily_readings.length;
    state = Core.runFixture(state, fx);
    const d = Core.describe(state);
    log.push(`${log.length + 1}단계: ${id} 재생 → 행 수 ${before}건 → ${d.row_count}건, 상태 ${d.freshness} / ${d.error_code}`);
    return true;
  }

  function reset() { state = Core.resetState(); stage = 0; log = []; compare = null; fixtureError = false; }

  async function manual(fn) {
    if (busy) return;
    busy = true; render();
    try { await fn(); } finally { busy = false; render(); }
  }
  async function playStage(n, id) { compare = null; if (await play(id)) stage = n; }

  async function auto(order, endStage) {
    reset(); render();
    for (const id of order) {
      if (!(await play(id))) { reset(); fixtureError = true; return; }
      render(); await sleep(450);
    }
    stage = endStage;
  }

  async function retry() {
    const before = Core.describe(state);
    if (await play(SHORT.RECOVER)) { compare = { before, after: Core.describe(state) }; stage = 3; }
  }

  function stateTable(d, unit) {
    const u = unit ? ` ${unit}` : '';
    const val = (v) => (v == null ? '—' : `${v}${u}`);
    return table([
      ['신선도(freshness)', d.freshness ?? '—'],
      ['오류 코드(error_code)', d.error_code ?? '—'],
      ['행 수', `${d.row_count}건`],
      ['저장값', val(d.stored_value)],
      ['마지막 정상값', val(d.last_good_value)],
      ['기록 날짜', d.record_date ?? '—'],
      ['변화량', d.freshness == null ? '—' : cmpText({ ...d.comparison, magnitude: d.delta, unit: d.comparison.unit || unit }, null)]
    ]);
  }

  function render() {
    const d = Core.describe(state);
    const cur = state.current_reading;
    const unit = cur?.unit || '';
    const failed = d.freshness === 'stale';

    // 버튼 상태와 이유
    const want = { t04Reset: true, t04D1A: stage === 0, t04D1B: stage === 1, t04D2: stage === 2, };
    for (const [id, ok] of Object.entries(want)) $(id).disabled = busy || !ok;
    $('t04Fail').disabled = busy || stage < 2;
    $('t04FailKind').disabled = busy || stage < 2;
    ['t04AutoOk', 't04AutoFail', 't04AutoRec'].forEach((id) => { $(id).disabled = busy; });
    $('t04Reason').textContent = stage === 0 ? '먼저 「D1-A 재생」을 누르세요.'
      : stage === 1 ? 'D1-A를 재생했습니다. 다음은 「D1-B 재생」입니다.'
      : stage === 2 ? 'D1-B까지 재생했습니다. 「D2 재생」 또는 실패 재생을 고를 수 있습니다.'
      : '모든 정상 단계를 재생했습니다. 「처음으로」로 다시 시작할 수 있습니다.';

    const box = $('t04Synth');
    const hadFocus = box.contains(document.activeElement);
    box.textContent = '';
    const heading = el('h3', 't04-restitle', '상태표');
    heading.id = 't04Result'; heading.tabIndex = -1;
    box.appendChild(heading);
    if (fixtureError) {
      box.appendChild(el('p', 't04-msg t04-msg-err',
        'fixture를 불러오지 못했습니다. 파일로 직접 열었다면 정적 서버로 여세요.'));
    }
    const live = $('t04Live');
    live.textContent = '';
    live.appendChild(el('span', `t04-state t04-state-${d.freshness || 'none'}`,
      d.freshness == null ? '아직 재생 없음' : `${d.freshness} / ${d.error_code}`));
    live.appendChild(document.createTextNode(` 행 ${d.row_count}건`));

    if (failed && d.error_code !== 'none') {
      const info = Core.ERROR_INFO[d.error_code];
      const p = el('div', 't04-errbox');
      p.appendChild(el('h3', null, info.label));
      p.appendChild(el('p', null, `원인: ${info.cause}`));
      p.appendChild(el('p', null, `조치: ${info.action}`));
      if (d.retry_after_seconds != null) p.appendChild(el('p', null, `Retry-After: ${d.retry_after_seconds}초 뒤에 다시 시도`));
      p.appendChild(el('p', 't04-stale', `오래된 값(stale) — 마지막 정상값 ${d.last_good_value}${unit ? ' ' + unit : ''}, 행 ${d.row_count}건을 그대로 보여 줍니다.`));
      const b = el('button', 't04-btn t04-btn-primary', '다시 시도');
      b.type = 'button'; b.disabled = busy;
      b.addEventListener('click', () => manual(retry));
      p.appendChild(b);
      box.appendChild(p);
    }

    if (compare) {
      const g = el('div', 't04-sidebyside');
      for (const [title, dd] of [['복구 전', compare.before], ['복구 후', compare.after]]) {
        const c = el('div', 't04-col'); c.appendChild(el('h3', null, title));
        c.appendChild(stateTable(dd, unit)); g.appendChild(c);
      }
      box.appendChild(g);
    } else {
      box.appendChild(stateTable(d, unit));
    }

    if (cur) {
      const synthetic = cur.source_url.includes('fixtures.aleph.invalid');
      box.appendChild(table([
        ['출처', cur.source_name],
        ['출처 URL', synthetic ? el('span', null, `${cur.source_url} (합성 주소)`) : link(cur.source_url)]
      ], 't04-small'));
    }

    const logBox = el('ol', 't04-log');
    log.forEach((l) => logBox.appendChild(el('li', null, l)));
    box.appendChild(el('h3', 't04-logtitle', '재생 로그'));
    if (hadFocus) heading.focus();
    box.appendChild(log.length ? logBox : el('p', 't04-note', '아직 재생한 단계가 없습니다.'));
  }

  function wire() {
    $('t04Reset').addEventListener('click', () => manual(async () => reset()));
    $('t04D1A').addEventListener('click', () => manual(() => playStage(1, SHORT.D1A)));
    $('t04D1B').addEventListener('click', () => manual(() => playStage(2, SHORT.D1B)));
    $('t04D2').addEventListener('click', () => manual(() => playStage(3, SHORT.D2)));
    $('t04Fail').addEventListener('click', () => manual(async () => { compare = null; await play($('t04FailKind').value); }));
    $('t04AutoOk').addEventListener('click', () => manual(() => auto(Core.FIXTURE_ORDER.success, 3)));
    $('t04AutoFail').addEventListener('click', () => manual(() => auto([...Core.FIXTURE_ORDER.baseline, ...Core.FIXTURE_ORDER.failures], 2)));
    $('t04AutoRec').addEventListener('click', () => manual(() => auto(Core.FIXTURE_ORDER.recovery, 3)));
    // 라이브 영역은 짧은 요약 한 줄만 둔다. 표·로그는 읽어 주지 않는다.
    for (const id of ['t04Synth', 't04Real']) { $(id).removeAttribute('role'); $(id).removeAttribute('aria-live'); }
    const live = el('p', 't04-statusline'); live.id = 't04Live';
    live.setAttribute('role', 'status'); live.setAttribute('aria-live', 'polite');
    $('t04Synth').before(live);
    render();
    renderReal();
  }

  function openFromHash() {
    if (location.hash === '#t04') document.querySelector('.tab-nav-btn[data-tab="t04"]')?.click();
  }
  function init() {
    if (!$('t04Real')) return;
    wire();
    openFromHash();
    window.addEventListener('hashchange', openFromHash);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
