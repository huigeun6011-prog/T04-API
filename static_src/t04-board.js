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

  /* ───────── ① 운행일 총 승하차(실제 기록) ───────── */
  const fmt = (n) => Number(n).toLocaleString('ko-KR');
  const nowIso = () => new Date().toISOString();
  const KIND_NOTE = '이 화면의 기록 파일 조회 실패입니다. 앱 로그인과는 관계없습니다.';
  let lastGood = null;   // 마지막으로 정상 불러온 {rows, at}. 실패해도 이 값을 계속 보여 준다.
  let loadError = null;  // 마지막 조회가 실패했다면 오류 유형(ERROR_INFO 키)
  let daysGood = null;   // 마지막으로 정상 불러온 business_days.json 의 {days, at}
  let daysError = null;  // business_days.json 조회 실패 유형
  let baseDate = null;   // 사용자가 고른 기준일(화면 안에서만 유지, null 이면 최근 완성 운행일)

  async function loadDaily() {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const res = await fetch('data/t04/daily.json', { cache: 'no-store', signal: controller.signal });
      if (res.status === 404) return [];
      if (!res.ok) throw Object.assign(new Error(`http_${res.status}`), { status: res.status });
      let rows;
      try { rows = (await res.json()).rows; } catch (e) { throw Object.assign(e, { status: 200 }); }
      // 형식이 틀린 파일은 네트워크 오류(offline)가 아니라 schema_error 로 분류되도록 status 를 붙인다.
      if (!Array.isArray(rows)) throw Object.assign(new Error('rows'), { status: 200 });
      try { rows.forEach((r) => Core.validateNormalizedReading(r.reading)); } catch (e) { throw Object.assign(e, { status: 200 }); }
      return rows;
    } finally { clearTimeout(timer); }
  }

  // 운행일별 총 승하차 + 날씨(고정 형식). 404 는 '자료 없음'(빈 목록)으로 취급한다.
  async function loadBusinessDays() {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const res = await fetch('data/t04/business_days.json', { cache: 'no-store', signal: controller.signal });
      if (res.status === 404) return [];
      if (!res.ok) throw Object.assign(new Error(`http_${res.status}`), { status: res.status });
      let days;
      try { days = Core.validateBusinessDays(await res.json()); } catch (e) { throw Object.assign(e, { status: 200 }); }
      return days;
    } finally { clearTimeout(timer); }
  }

  async function refreshReal() {
    const box = $('t04Real');
    box.setAttribute('aria-busy', 'true');
    const [daily, bdays] = await Promise.allSettled([loadDaily(), loadBusinessDays()]);
    if (daily.status === 'fulfilled') { lastGood = { rows: daily.value, at: nowIso() }; loadError = null; }
    else loadError = Core.classifyLoadError(daily.reason);
    if (bdays.status === 'fulfilled') { daysGood = { days: bdays.value, at: nowIso() }; daysError = null; }
    else daysError = Core.classifyLoadError(bdays.reason);
    drawReal();
    box.removeAttribute('aria-busy');
  }

  function drawReal() {
    const box = $('t04Real');
    box.textContent = '';
    if (loadError) {
      const info = Core.ERROR_INFO[loadError];
      const e = el('div', 't04-errbox');
      e.appendChild(el('h3', null, `기록 조회 실패: ${info.label} (${loadError})`));
      e.appendChild(el('p', null, `원인: ${info.cause}`));
      e.appendChild(el('p', null, `조치: ${info.action}`));
      e.appendChild(el('p', 't04-note', KIND_NOTE));
      if (lastGood) {
        e.appendChild(el('p', 't04-stale', `오래된 값(stale): 아래는 ${toKst(lastGood.at)}에 마지막으로 정상 조회한 기록입니다.`));
      } else {
        e.appendChild(el('p', 't04-stale', '정상 조회한 기록이 아직 없어 보여 줄 값이 없습니다. 파일로 직접 열었다면 정적 서버로 여세요.'));
      }
      const b = el('button', 't04-btn t04-btn-primary', '다시 시도');
      b.type = 'button';
      b.addEventListener('click', refreshReal);
      e.appendChild(b);
      box.appendChild(e);
    }
    if (lastGood) drawBoard(box, lastGood.rows);
    else box.appendChild(trendSection());
  }

  /* ───────── 기준일 선택 + 최근 7일 선 그래프(순수 SVG) ───────── */
  const SVG_NS = 'http://www.w3.org/2000/svg';
  function svg(tag, attrs, text) {
    const e = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, String(v));
    if (text != null) e.textContent = text;
    return e;
  }
  const currentBase = () => baseDate || Core.latestCompleteDay(nowIso());
  const dayDetail = (p) => (p.state === 'recorded'
    ? `${p.date} (${p.weekday}) 승하차 ${fmt(p.value)}명 · 날씨 ${Core.weatherText(p.weather)}`
    : `${p.date} (${p.weekday}) ${p.label} · ${p.state === 'pending' ? '아직 집계 전(오류 아님)' : '집계 완료일이지만 이 파일에 값이 없음'}`);

  // 그래프를 그려 반환한다. detail 은 포커스·호버 때 상세를 보여 줄 요소.
  function drawChart(series, detail) {
    const L = Core.chartLayout(series);
    const H = L.bottom + 96;
    const root = svg('svg', { class: 't04-chart', viewBox: `0 0 ${L.width} ${H}`, role: 'img', 'aria-label': Core.trendSummary(series), preserveAspectRatio: 'xMidYMid meet' });
    root.appendChild(svg('title', {}, '기준일을 포함한 최근 7일 승하차 인원 선 그래프'));
    // 세로축: 눈금선과 값
    for (const t of L.yTicks) {
      root.appendChild(svg('line', { class: 't04-grid-line', x1: L.left, x2: L.width - L.right, y1: t.y, y2: t.y }));
      root.appendChild(svg('text', { class: 't04-axis-text', x: L.left - 6, y: t.y + 4, 'text-anchor': 'end' }, fmt(t.value)));
    }
    root.appendChild(svg('text', { class: 't04-axis-text', x: 4, y: 14 }, '승하차 인원(명)'));
    root.appendChild(svg('line', { class: 't04-axis-line', x1: L.left, x2: L.width - L.right, y1: L.bottom, y2: L.bottom }));
    // 선: 값이 이어지는 구간만. 미집계·자료 없는 날에서 끊는다.
    for (const d of L.paths) root.appendChild(svg('path', { class: 't04-line', d, fill: 'none' }));
    // 가로축 라벨, 미집계 표시, 날씨 띠
    const bandY = L.bottom + 40;
    root.appendChild(svg('rect', { class: 't04-weather-band', x: L.left, y: bandY, width: L.plotW, height: 52 }));
    root.appendChild(svg('text', { class: 't04-axis-text', x: 4, y: bandY + 20 }, '날씨'));
    for (const p of L.points) {
      root.appendChild(svg('text', { class: 't04-axis-text t04-tick-date', x: p.x, y: L.bottom + 16, 'text-anchor': 'middle' }, p.mmdd));
      root.appendChild(svg('text', { class: 't04-axis-text', x: p.x, y: L.bottom + 31, 'text-anchor': 'middle' }, `(${p.weekday})`));
      const lines = Core.weatherLines(p.weather);
      const wt = svg('text', { class: `t04-weather-text${p.weather ? '' : ' t04-weather-none'}`, x: p.x, y: bandY + (lines.length > 1 ? 20 : 30), 'text-anchor': 'middle' });
      lines.forEach((ln, i) => wt.appendChild(svg('tspan', { x: p.x, dy: i ? 15 : 0 }, ln)));
      root.appendChild(wt);
      if (p.state !== 'recorded') {
        root.appendChild(svg('text', { class: 't04-gap-text', x: p.x, y: L.bottom - 8, 'text-anchor': 'middle' }, p.label));
      }
    }
    // 점(마커)과 값. 포커스·호버 때 상세를 보인다.
    for (const p of L.points.filter((q) => q.state === 'recorded')) {
      const g = svg('g', { class: 't04-point', tabindex: 0, role: 'img', 'aria-label': dayDetail(p) });
      g.appendChild(svg('circle', { class: 't04-hit', cx: p.x, cy: p.y, r: 14 }));
      g.appendChild(svg('circle', { class: 't04-dot', cx: p.x, cy: p.y, r: 5 }));
      g.appendChild(svg('text', { class: 't04-value-text', x: p.x, y: p.y - 11, 'text-anchor': 'middle' }, fmt(p.value)));
      const show = () => { detail.textContent = dayDetail(p); };
      g.addEventListener('focus', show); g.addEventListener('mouseenter', show);
      root.appendChild(g);
    }
    return root;
  }

  function trendTable(series) {
    const t = el('table', 't04-table t04-days');
    t.appendChild(el('caption', null, '기준일을 포함한 최근 7일 운행일별 총 승하차와 날씨(그래프와 같은 값)'));
    const hr = el('tr');
    ['운행일', '요일', '총 승하차', '날씨'].forEach((h) => { hr.appendChild(el('th', null, h)).scope = 'col'; });
    t.appendChild(el('thead')).appendChild(hr);
    const tb = el('tbody');
    for (const p of series) {
      const tr = el('tr', `t04-day-${p.state}`);
      tr.appendChild(el('th', null, p.date)).scope = 'row';
      tr.appendChild(el('td', null, p.weekday));
      const td = el('td');
      if (p.state === 'recorded') td.textContent = `${fmt(p.value)} 명`;
      else if (p.state === 'pending') td.append(pendingBadge(), ' 데이터 공개 전');
      else td.appendChild(el('span', 't04-none', '자료 없음'));
      tr.appendChild(td);
      tr.appendChild(el('td', null, p.state === 'recorded' ? Core.weatherText(p.weather) : '—'));
      tb.appendChild(tr);
    }
    t.appendChild(tb);
    return scrollWrap(t, '최근 7일 표');
  }

  function trendSection() {
    const sec = el('div', 't04-trend');
    sec.id = 't04Trend';
    sec.appendChild(el('h3', null, '기준일 선택 · 최근 7일 승하차'));
    if (daysError) {
      const info = Core.ERROR_INFO[daysError];
      const e = el('div', 't04-errbox');
      e.appendChild(el('h3', null, `일별 자료 조회 실패: ${info.label} (${daysError})`));
      e.appendChild(el('p', null, `원인: ${info.cause}`));
      e.appendChild(el('p', null, `조치: ${info.action}`));
      e.appendChild(el('p', 't04-note', KIND_NOTE));
      e.appendChild(el('p', 't04-stale', daysGood
        ? `오래된 값(stale): 아래는 ${toKst(daysGood.at)}에 마지막으로 정상 조회한 자료입니다.`
        : '정상 조회한 일별 자료가 아직 없어 보여 줄 값이 없습니다.'));
      const b = el('button', 't04-btn t04-btn-primary', '다시 시도');
      b.type = 'button'; b.addEventListener('click', refreshReal);
      e.appendChild(b);
      sec.appendChild(e);
    }
    const days = daysGood ? daysGood.days : [];
    if (!days.length) {
      if (!daysError) sec.appendChild(el('p', 't04-msg', '자료 없음: 운행일별 승하차·날씨 자료가 아직 없습니다. 자료가 쌓이면 여기에 그래프가 표시됩니다.'));
      return sec;
    }

    const controls = el('div', 't04-controls t04-datepick');
    const prev = el('button', 't04-btn', '◀ 이전 날');
    const next = el('button', 't04-btn', '다음 날 ▶');
    prev.type = 'button'; next.type = 'button';
    const label = el('label', 't04-sel');
    label.appendChild(el('span', null, '기준일 '));
    const input = el('input'); input.type = 'date'; input.id = 't04BaseDate';
    input.min = days[0].business_day; // max 는 두지 않는다: 미집계 날짜도 고를 수 있다
    label.appendChild(input);
    controls.append(prev, label, next);
    sec.appendChild(controls);
    sec.appendChild(el('p', 't04-note', '기준일을 포함한 7일의 그래프와 표만 바뀝니다. 위의 대표값·전일 대비·원본 대조는 그대로입니다. 최근 완성 운행일 이후 날짜는 “미집계”로 보입니다.'));

    const out = el('div', 't04-trend-out');
    sec.appendChild(out);
    const redraw = () => {
      const series = Core.trendSeries(days, currentBase(), nowIso());
      out.textContent = '';
      input.value = currentBase();
      prev.disabled = currentBase() <= input.min;
      const detail = el('p', 't04-detail', '점에 마우스를 올리거나 Tab 으로 이동하면 날짜·인원·날씨가 여기에 표시됩니다.');
      detail.setAttribute('role', 'status');
      const wrap = el('div', 't04-chart-scroll');
      wrap.appendChild(drawChart(series, detail));
      out.append(wrap, detail, trendTable(series));
      out.appendChild(el('p', 't04-note',
        '날씨는 운행일 05~23시 합입니다. 비는 눈이 오지 않은 시각의 강수(mm), 눈은 적설량(cm)입니다. 끊긴 선은 그 날 값이 없다는 뜻입니다(보간하지 않음). 요일에 따라 값이 크게 다릅니다.'));
    };
    const set = (v) => { const d = Core.parseDateInput(v); if (d) { baseDate = d; redraw(); } };
    input.addEventListener('change', () => set(input.value));
    prev.addEventListener('click', () => set(Core.addDaysStr(currentBase(), -1)));
    next.addEventListener('click', () => set(Core.addDaysStr(currentBase(), 1)));
    redraw();
    return sec;
  }

  function pendingBadge() {
    const s = el('span', 't04-pending', '미집계');
    s.title = '정상 상태: 데이터가 아직 공개되기 전입니다. 오류가 아닙니다.';
    return s;
  }

  function drawBoard(box, rows) {
    const now = nowIso();
    const list = Core.businessRows(rows);
    const last = list[list.length - 1];

    // ── 대표값
    if (!last) {
      box.appendChild(el('p', 't04-msg', '기록 없음: 아직 저장된 운행일 총 승하차 기록이 없습니다. 기록이 쌓이면 여기에 표시됩니다.'));
    } else {
      const r = last.reading;
      box.appendChild(el('p', 't04-note', `운행일 ${last.business_day} (${Core.weekdayKo(last.business_day)}) 총 승하차 합계`));
      const value = el('p', 't04-bigvalue');
      const vSpan = el('span', null, fmt(r.normalized_value)); vSpan.id = 't04ScreenVal';
      const uSpan = el('span', 't04-unit', r.unit); uSpan.id = 't04ScreenUnit';
      value.append(vSpan, ' ', uSpan);
      box.appendChild(value);
      box.appendChild(el('p', 't04-note',
        '합계 = 승차+하차, 모든 권종·모든 역. 운행일 05~23시 + 다음 날 00시(운행일 자신의 00시는 제외). 실측 집계입니다.'));
      box.appendChild(table([
        ['출처', r.source_name],
        ['운행일(출처 시각)', `${last.business_day} (${Core.weekdayKo(last.business_day)}) · 자료 마지막 시각 ${r.source_time ? toKst(r.source_time) : '원천이 시각을 주지 않음'}`],
        ['조회 시각(fetched_at)', `${r.fetched_at} (UTC) = ${toKst(r.fetched_at)}`],
        ['기준 시간대', r.record_timezone],
        ['조회 날짜(record_date)', r.record_date],
        ['출처 URL(키 없음)', link(r.source_url)]
      ]));
    }

    // ── 기준일 + 최근 7일 그래프·표
    box.appendChild(trendSection());

    // ── 전일 대비
    box.appendChild(el('h3', null, '전일 대비 변화'));
    const c = Core.dayOverDay(rows);
    if (c.state === 'no_previous') {
      box.appendChild(el('p', 't04-msg', '비교할 이전 기록 없음(저장된 운행일이 2일 이상 쌓이면 표시됩니다).'));
    } else if (c.state === 'unit_mismatch') {
      box.appendChild(el('p', 't04-msg', '단위가 달라 비교하지 않음'));
    } else {
      const sign = c.delta > 0 ? '+' : c.delta < 0 ? '−' : '';
      const rowsCmp = [
        ['변화', c.delta === 0 ? '0 명 (변화 없음)' : `${sign}${fmt(Math.abs(c.delta))} ${c.unit} (${c.direction === 'increase' ? '증가' : '감소'})`],
        ['계산식', `${fmt(c.last.value)} − ${fmt(c.prev.value)} = ${c.delta < 0 ? '−' : ''}${fmt(Math.abs(c.delta))}`],
        ['입력값 1(이전)', `${c.prev.business_day} (${c.prev.weekday}) ${fmt(c.prev.value)} ${c.unit}`],
        ['입력값 2(최근)', `${c.last.business_day} (${c.last.weekday}) ${fmt(c.last.value)} ${c.unit}`]
      ];
      if (!c.consecutive) rowsCmp.push(['일수 차이', `연속된 운행일이 아닙니다: ${c.days_apart}일 차이`]);
      if (c.prev.weekday !== c.last.weekday) rowsCmp.push(['요일 주의', `${c.prev.weekday}요일과 ${c.last.weekday}요일을 비교합니다. 요일 효과가 클 수 있습니다.`]);
      box.appendChild(table(rowsCmp));
    }

    if (!last) return;

    // ── 시간별·역별(접이식)
    const hourDet = el('details', 't04-details');
    hourDet.appendChild(el('summary', null, '시간별 합계 (5시~24시)'));
    const hourRows = Core.BUSINESS_HOUR_KEYS.map((k) => [k === '24' ? '24시 (익일 00시)' : `${k}시`, fmt(last.hourly?.[k] ?? 0)]);
    hourRows.push(['합계', fmt(Core.BUSINESS_HOUR_KEYS.reduce((a, k) => a + (last.hourly?.[k] ?? 0), 0))]);
    hourDet.appendChild(scrollWrap(gridTable(`${last.business_day} 시간별 승하차(명)`, ['시각', '승하차(명)'], hourRows), '시간별 합계 표'));
    box.appendChild(hourDet);

    const stDet = el('details', 't04-details');
    stDet.appendChild(el('summary', null, '역별 합계'));
    const stEntries = Object.entries(last.stations || {}).sort(([x], [y]) => x.localeCompare(y));
    const stRows = stEntries.map(([no, v]) => [Core.stationLabel(no), fmt(v.boardings), fmt(v.alightings), fmt(v.boardings + v.alightings)]);
    stRows.push(['합계', fmt(stEntries.reduce((a, [, v]) => a + v.boardings, 0)), fmt(stEntries.reduce((a, [, v]) => a + v.alightings, 0)),
      fmt(stEntries.reduce((a, [, v]) => a + v.boardings + v.alightings, 0))]);
    stDet.appendChild(scrollWrap(gridTable(`${last.business_day} 역별(역번호·역 이름)`, ['역', '승차', '하차', '합계'], stRows), '역별 합계 표'));
    box.appendChild(stDet);

    // ── 원본 XML 링크와 대조
    const rawBox = el('div', 't04-rawbox');
    rawBox.appendChild(el('h3', null, '원본 XML과 값 대조'));
    const refs = Array.isArray(last.raw_xml) ? last.raw_xml.filter((x) => /^data\/t04\/raw\/\d{4}-\d{2}-\d{2}\.xml$/.test(x)) : [];
    const ul = el('ul', 't04-rawlinks');
    refs.forEach((ref) => {
      const li = el('li'); const a = el('a', null, ref);
      a.href = ref; a.target = '_blank'; a.rel = 'noopener noreferrer';
      li.appendChild(a); ul.appendChild(li);
    });
    rawBox.appendChild(refs.length ? ul : el('p', 't04-msg', '이 기록에는 원본 XML 경로가 없습니다.'));
    const status = el('p', 't04-note', '원본 XML을 불러와 다시 계산하는 중…');
    rawBox.appendChild(status);
    box.appendChild(rawBox);
    verify(rawBox, status, last, refs);
  }

  async function verify(rawBox, status, row, refs) {
    const r = row.reading;
    let sums = null;
    let why = '';
    try {
      if (refs.length !== 2) throw new Error('raw_xml');
      const texts = [];
      for (const ref of refs) {
        const res = await fetch(ref, { cache: 'no-store' });
        if (!res.ok) throw new Error(String(res.status));
        texts.push(await res.text());
      }
      sums = Core.sumBusinessDayXml(texts[0], texts[1], row.business_day);
      if (!sums) why = '원본 XML이 비어 있어 계산할 수 없습니다.';
    } catch (_) { why = '원본 XML을 불러오거나 해석하지 못해 대조할 수 없습니다(불일치와는 다릅니다).'; }
    if (!rawBox.isConnected) return;
    const screenVal = Number($('t04ScreenVal')?.textContent.replace(/,/g, ''));
    const screenUnit = $('t04ScreenUnit')?.textContent;
    const rawText = sums ? `${fmt(sums.total)} 명` : '대조 불가';
    const t = el('table', 't04-table t04-three');
    t.appendChild(el('caption', null, '값 대조(원본 · 저장값 · 화면값)'));
    const hr = el('tr');
    ['원본(XML을 다시 계산)', '저장값(reading.normalized_value, unit)', '화면값(DOM에 그려진 숫자를 다시 읽은 값)']
      .forEach((h) => hr.appendChild(el('th', null, h)).scope = 'col');
    t.appendChild(el('thead')).appendChild(hr);
    const tr = el('tr');
    [rawText, `${fmt(r.normalized_value)} ${r.unit}`, `${fmt(screenVal)} ${screenUnit}`].forEach((v) => tr.appendChild(el('td', null, v)));
    t.appendChild(el('tbody')).appendChild(tr);
    status.replaceWith(scrollWrap(t, '값 대조 표'));
    if (!sums) { rawBox.appendChild(el('p', 't04-msg', why)); return; }
    const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
    const totalSame = sums.total === r.normalized_value && screenVal === r.normalized_value && screenUnit === r.unit;
    const partsSame = same(sums.hourly, row.hourly) && same(sums.stations, row.stations);
    rawBox.appendChild(el('p', `t04-verdict ${totalSame ? 't04-ok' : 't04-bad'}`, `합계 대조: 세 값 ${totalSame ? '일치' : '불일치'}`));
    rawBox.appendChild(el('p', `t04-verdict ${partsSame ? 't04-ok' : 't04-bad'}`, `시간별·역별 저장값과 원본 재계산 대조: ${partsSame ? '일치' : '불일치'}`));
  }

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

  /* ───────── ② 합성 재생: #t04-lab 일 때만 나타난다. 실제 기록과 별도 메모리 상태를 쓴다. ───────── */
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
    if (!labMounted) return;
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

  let labMounted = false;
  function mountLab() {
    const mount = $('t04LabMount');
    const tpl = $('t04LabTemplate');
    if (labMounted || !mount || !tpl) return;
    mount.appendChild(tpl.content.cloneNode(true));
    labMounted = true;
    $('t04Reset').addEventListener('click', () => manual(async () => reset()));
    $('t04D1A').addEventListener('click', () => manual(() => playStage(1, SHORT.D1A)));
    $('t04D1B').addEventListener('click', () => manual(() => playStage(2, SHORT.D1B)));
    $('t04D2').addEventListener('click', () => manual(() => playStage(3, SHORT.D2)));
    $('t04Fail').addEventListener('click', () => manual(async () => { compare = null; await play($('t04FailKind').value); }));
    $('t04AutoOk').addEventListener('click', () => manual(() => auto(Core.FIXTURE_ORDER.success, 3)));
    $('t04AutoFail').addEventListener('click', () => manual(() => auto([...Core.FIXTURE_ORDER.baseline, ...Core.FIXTURE_ORDER.failures], 2)));
    $('t04AutoRec').addEventListener('click', () => manual(() => auto(Core.FIXTURE_ORDER.recovery, 3)));
    render();
  }
  function unmountLab() {
    if (!labMounted) return;
    $('t04LabMount').textContent = '';
    labMounted = false;
  }
  function syncLab() {
    if (Core.isLabHash(location.hash)) mountLab(); else unmountLab();
  }
  function openFromHash() {
    if (location.hash === '#t04' || Core.isLabHash(location.hash)) {
      document.querySelector('.tab-nav-btn[data-tab="t04"]')?.click();
    }
    syncLab();
  }
  function init() {
    if (!$('t04Real')) return;
    refreshReal();
    openFromHash();
    window.addEventListener('hashchange', openFromHash);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
