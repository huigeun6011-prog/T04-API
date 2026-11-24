(function () {
  'use strict';

  const RAIN_MM = 1;    // 하루 강수 합계가 이 값 이상이면 비 아이콘
  const SNOW_CM = 0.1;  // 하루 적설 합계가 이 값 이상이면 눈 아이콘(비보다 우선)
  const Core = window.T04Core;
  const Weather = window.DailyWeather;
  const card = document.getElementById('dailyWeather');
  const panel = card.closest('.query-more');
  const status = document.getElementById('dailyWeatherStatus');
  const values = document.getElementById('dailyWeatherValues');
  const saved = document.getElementById('dailyWeatherSaved');
  const retry = document.getElementById('dailyWeatherRetry');
  const lab = document.getElementById('dailyWeatherLab');
  const fixtureList = document.getElementById('dailyWeatherFailure');
  const historyButton = document.getElementById('dailyWeatherLive');
  const legacyBox = document.getElementById('weatherBox');
  const kst = new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit'
  });
  const number = (value, unit) => `${value.toFixed(1)} ${unit}`;
  // weather-daily.js 의 공개 함수가 없으면 같은 규칙의 대체 계산을 쓴다.
  const dataDateOf = (row) => (typeof Weather.dataDateOf === 'function' ? Weather.dataDateOf(row) : row.reading.source_time.slice(0, 10));
  const kindOf = (row) => (typeof Weather.kindOf === 'function' ? Weather.kindOf(row) : /관측|archive/.test(row.reading.source_name) ? 'observed' : 'forecast');
  const latestRow = (rows) => (typeof Weather.latestRow === 'function' ? Weather.latestRow(rows)
    : rows.reduce((best, row) => (!best || row.reading.record_date > best.reading.record_date ? row : best), undefined));
  const korDay = (date) => `${Number(date.slice(5, 7))}월 ${Number(date.slice(8, 10))}일`;
  const savedNote = (row) => (kindOf(row) === 'observed'
    ? `저장된 관측 · 자료 ${korDay(dataDateOf(row))} · 조회 ${korDay(row.reading.record_date)}`
    : `저장된 예보 · ${korDay(row.reading.record_date)}`);
  const fallbackRow = () => (realLive ? undefined : realError ? latestRow(realRows) : undefined);
  let realLive; // 이번 실행에서 실시간으로 조회한 오늘 예보(브라우저 저장소는 쓰지 않는다)
  let realRows = [];
  let recordsError = false;
  let realError;
  let realBusy = false;
  let labMode = false;
  let labBusy = false;
  let labRows = [];
  let labLive;
  let labError;
  let fixtureManifest;
  let loaded = false;
  let selection; // { src: 'real' | 'lab', date }
  let shownLab = false;
  let recordsRequested = false;
  let lastStatusKey;
  retry.classList.add('weather-retry');

  const svg = (d) => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${d}</svg>`;
  const CLOUD = '<path d="M7 18h10a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 7.1 9.2 4.4 4.4 0 0 0 7 18z"/>';
  const ICONS = {
    snow: svg(`${CLOUD}<path d="M9 21h.01M12 21h.01M15 21h.01"/>`),
    rain: svg(`${CLOUD}<path d="M9 20.5l-.7 1.5M13 20.5l-.7 1.5M17 20.5l-.7 1.5"/>`),
    mixed: svg('<circle cx="8" cy="8" r="2.6"/><path d="M8 2.5v1M2.5 8h1M3.9 3.9l.7.7M12.1 3.9l-.7.7"/><path d="M9 20h8.5a3.5 3.5 0 0 0 .4-6.97A4.8 4.8 0 0 0 9.4 12.2 3.9 3.9 0 0 0 9 20z"/>'),
    none: svg('<circle cx="8" cy="8" r="2.6"/><path d="M9 20h8.5a3.5 3.5 0 0 0 .4-6.97A4.8 4.8 0 0 0 9.4 12.2 3.9 3.9 0 0 0 9 20z"/>')
  };
  // 하루 대표 날씨: 방문일(state.weather)의 24시간 합계, 없으면 오늘 저장 기록. 아이콘은 창을 닫아도 갱신된다.
  function updateIcon() {
    const sum = document.getElementById('weatherSummary');
    if (!sum) return;
    const day = typeof state !== 'undefined' && state.weather?.available ? state.weather : null;
    let rain, snow, mean, stale = false, failed = false, failLabel = '', savedInfo = '';
    const failure = typeof state !== 'undefined' ? state.weatherFailure : null;
    if (day) {
      const idx = day.hourly.time.map((t, i) => (t.startsWith(state.date) ? i : -1)).filter((i) => i >= 0);
      const total = (key) => idx.reduce((a, i) => a + (Number.isFinite(day.hourly[key][i]) ? day.hourly[key][i] : 0), 0);
      rain = total('precipitation'); snow = total('snowfall');
      const temps = idx.map((i) => day.hourly.temperature_2m[i]).filter(Number.isFinite);
      mean = temps.length ? temps.reduce((a, b) => a + b, 0) / temps.length : undefined;
    } else if (realLive || fallbackRow()) {
      const row = realLive || fallbackRow();
      ({ precipitation: rain, snowfall: snow, mean } = row.summary);
      stale = !realLive || Boolean(failure);
      if (!realLive) savedInfo = ` — ${savedNote(row)}`;
    }
    if (!day && !realLive && !fallbackRow() && (failure || realError)) {
      failed = true;
      const kind = failure?.kind || realError?.kind || 'schema_error';
      failLabel = kind === 'out_of_range' ? '제공 범위 밖 날짜' : Core.ERROR_INFO[kind]?.label || '조회 실패';
    }
    const known = rain !== undefined;
    const kind = !known ? 'none' : snow >= SNOW_CM ? 'snow' : rain >= RAIN_MM ? 'rain' : 'mixed';
    const name = { snow: '눈', rain: '비', mixed: '구름·해', none: '' }[kind];
    const text = failed ? (failure?.kind === 'out_of_range' ? `날씨: ${failLabel}` : `날씨: 오류 — ${failLabel}`) : known ? `날씨: ${name}${Number.isFinite(mean) ? `, 평균 ${mean.toFixed(1)}°C` : ''}${stale ? ` (오래된 값${savedInfo})` : ''}` : '날씨: 불러오는 중';
    sum.querySelector('.weather-ico').innerHTML = ICONS[kind] + (failed ? `<span class="weather-stale-dot${failure?.kind === 'out_of_range' ? '' : ' weather-dot--fail'}">!</span>` : stale ? '<span class="weather-stale-dot">!</span>' : '');
    sum.classList.toggle('weather-ico-faint', !known && !failed);
    sum.setAttribute('aria-label', text);
    sum.title = text;
  }
  window.updateWeatherIcon = updateIcon;

  const WARN = svg('<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18h.01"/>');

  function recordMeta(record, sourceOpen) {
    const { reading } = record;
    const observed = kindOf(record) === 'observed', dataDate = dataDateOf(record);
    const name = reading.source_name;
    const source = shownLab ? name : `<a href="${reading.source_url}" target="_blank" rel="noopener">${name}</a>`;
    return `<details class="weather-source"${sourceOpen ? ' open' : ''}><summary>출처·조회 시각·기준 시간대</summary><ul class="weather-meta">
      <li>출처 ${source}${observed ? ` · 자료 날짜 ${dataDate}` : ''}</li>
      <li>출처 시각 ${dataDate} 00:00~23:00 KST 시간별 ${observed ? '관측' : '예보'}</li>
      <li>${record.time_basis === 'file_mtime' ? '파일 수정 시각 (조회 시각 대용)' : '조회 시각'} ${kst.format(new Date(reading.fetched_at))} KST</li>
      <li>기준 시간대 ${reading.record_timezone}</li>
    </ul></details>`;
  }

  function renderValues(record, tag) {
    if (!record) { values.replaceChildren(); return; }
    const { summary, raw: { hourly } } = record;
    const stats = [
      ['평균기온', summary.mean, '°C'], ['최저기온', summary.min, '°C'],
      ['최고기온', summary.max, '°C'], ['총강수량', summary.precipitation, 'mm'], ['총적설량', summary.snowfall, 'cm']
    ];
    const hours = hourly.time.map((time, i) =>
      `<tr><th scope="row">${time.slice(11)}</th><td>${number(hourly.temperature_2m[i], '°C')}</td><td>${number(hourly.precipitation[i], 'mm')}</td><td>${number(hourly.snowfall[i], 'cm')}</td></tr>`).join('');
    const wasOpen = values.querySelector('.weather-hourly-details')?.open;
    const sourceOpen = values.querySelector('.weather-source')?.open;
    values.innerHTML = `${tag ? `<p class="weather-kind-tag">${tag}</p>` : ''}<dl class="daily-weather__stats">${stats.map(([label, value, unit]) =>
      `<div><dt>${label}</dt><dd>${number(value, unit)}</dd></div>`).join('')}</dl>
      <details class="weather-hourly-details" ${wasOpen ? 'open' : ''}><summary>24시간 날씨</summary><div class="weather-hourly">
      <table><thead><tr><th scope="col">KST</th><th scope="col">기온</th><th scope="col">강수</th><th scope="col">적설</th></tr></thead><tbody>${hours}</tbody></table></div></details>
      ${recordMeta(record, sourceOpen)}`;
  }

  function compareText(rows) {
    const [older, latest] = rows.slice(-2);
    if (!latest) return '비교하려면 서로 다른 KST 날짜의 기록이 필요합니다.';
    const change = Core.roundToTenth(latest.summary.mean - older.summary.mean);
    const [a, b] = [dataDateOf(older), dataDateOf(latest)];
    const gap = Core.daysBetween(a, b);
    const label = gap === 1 ? `자료 ${a.slice(5)} → ${b.slice(5)} 변화` : `최근 두 기록 비교 (자료 ${a.slice(5)} → ${b.slice(5)}, ${gap}일 차이)`;
    return `${label} ${number(latest.summary.mean, '°C')} − ${number(older.summary.mean, '°C')} = ${change > 0 ? '+' : ''}${number(change, '°C')}`;
  }
  const rowLabel = (row) => (kindOf(row) === 'observed'
    ? `조회 ${row.reading.record_date.slice(5)} · 자료 ${dataDateOf(row).slice(5)}` : `조회 ${row.reading.record_date.slice(5)} · 예보`);

  // 일반 화면에는 기록 영역을 그리지 않는다. 테스트 화면에서만 실제 기록과 합성 기록을 따로 보여 준다.
  function renderRecords() {
    saved.hidden = !labMode;
    if (!labMode) { saved.replaceChildren(); return; }
    const section = (src, title, rows, note) => `<section class="weather-records weather-records--${src}"><h5>${title}</h5>
      <p>${note}</p>
      ${rows.map((row) => `<button type="button" class="update-retry" data-record-src="${src}" data-record-date="${row.reading.record_date}" aria-pressed="${selection?.src === src && selection.date === row.reading.record_date}">${rowLabel(row)} · ${number(row.summary.mean, '°C')}</button>`).join('')}</section>`;
    saved.innerHTML = section('real', `실제 기록 ${realRows.length}건`, realRows, recordsError ? '저장 기록을 읽지 못했습니다.' : compareText(realRows))
      + section('lab', `합성 기록 ${labRows.length}건(시험용)`, labRows, compareText(labRows));
  }

  function render() {
    const error = labMode ? labError : realError;
    const busy = labMode ? labBusy : realBusy;
    const selected = selection && (selection.src === 'lab' ? labMode && labRows : realRows).find((row) => row.reading.record_date === selection.date);
    const live = labMode ? labLive : realLive || fallbackRow();
    const usingSaved = !labMode && !realLive && Boolean(live);
    shownLab = labMode && !(selected && selection.src === 'real');
    const shown = selected || live;
    const stale = Boolean(!selected && live && error);
    const info = error && Core.ERROR_INFO[error.kind || 'schema_error'];
    const delay = Number(error?.retryAfter);
    const detail = info ? `${info.cause} ${info.action}${delay > 0 ? ` ${delay}초 뒤에 재시도하세요.` : ''}` : '';
    const severity = error ? (labMode || shown ? 'stale' : 'fail') : (stale && !labMode ? 'stale' : '');
    const title = error ? (info ? `${info.label} (${error.kind || 'schema_error'})` : '날씨 오류') : '오래된 값 (stale)';
    const selectedNote = !selected ? '' : selection.src === 'lab' ? '저장된 합성 응답(시험용)' : '저장된 실제 응답 · 원본에서 재계산한 값과 일치';
    const key = [severity, title, detail, labMode, usingSaved && live && live.reading.record_date, busy && !selected, !busy && !shown && !error, selectedNote, live && labMode && !error].join('|');
    if (key !== lastStatusKey) {
      lastStatusKey = key;
      const nodes = [];
      const line = (text, cls) => { const p = document.createElement('p'); p.className = cls; p.textContent = text; return p; };
      if (labMode) nodes.push(line('합성 테스트 · 실제 기록과 분리', 'weather-lab-badge'));
      if (busy && !selected) nodes.push(line('날씨를 불러오는 중입니다…', 'weather-status-line'));
      if (severity) {
        const block = document.createElement('div');
        block.className = `weather-alert weather-alert--${severity}${labMode ? ' weather-alert--synthetic' : ''}`;
        const ico = document.createElement('span');
        ico.className = 'weather-alert__icon';
        ico.setAttribute('aria-hidden', 'true');
        ico.innerHTML = WARN;
        const body = document.createElement('div');
        body.className = 'weather-alert__body';
        const strong = document.createElement('strong');
        strong.className = 'weather-alert__title';
        strong.textContent = title;
        body.append(strong);
        if (severity === 'stale' && error) {
          const badge = document.createElement('span');
          badge.className = 'weather-alert__badge';
          badge.textContent = '오래된 값';
          body.append(badge);
        }
        const text = [detail, severity === 'stale' ? (usingSaved ? savedNote(live) : '마지막 정상 응답을 표시합니다.') : ''].filter(Boolean).join(' ');
        if (text) body.append(line(text, 'weather-alert__text'));
        block.append(ico, body);
        nodes.push(block);
      }
      if (!severity && live && labMode) nodes.push(line('정상 (fresh / none)', 'weather-status-line'));
      if (selectedNote) nodes.push(line(selectedNote, 'weather-status-line'));
      if (!busy && !shown && !error) nodes.push(line('아직 날씨가 없습니다.', 'weather-status-line'));
      status.replaceChildren(...nodes);
    }
    // 값이 없는 실패만 alert(한 번만 읽힘), 나머지는 status. 포커스는 옮기지 않는다.
    status.setAttribute('role', severity === 'fail' ? 'alert' : 'status');
    if (severity === 'fail') status.removeAttribute('aria-live'); else status.setAttribute('aria-live', 'polite');
    const block = status.querySelector('.weather-alert__body');
    if (error && block) block.append(retry); else if (!error && retry.parentNode !== status.parentNode) status.after(retry);
    status.classList.toggle('weather-error', Boolean(error));
    retry.hidden = !error;
    retry.disabled = busy;
    historyButton.hidden = !selected;
    historyButton.textContent = labMode ? '최신 합성 값으로 돌아가기' : '오늘 예보로 돌아가기';
    lab.querySelectorAll('button, select').forEach((control) => { control.disabled = busy; });
    const tag = selected ? (selection.src === 'real' ? savedNote(selected) : '') : !labMode && realLive && !error ? '실시간 오늘 예보' : '';
    const badge = card.querySelector('#dailyWeatherTitle .weather-badge');
    if (badge) badge.textContent = usingSaved && !selected ? '저장된 관측' : '대전 예보';
    renderValues(shown, tag);
    renderRecords();
    updateIcon();
  }

  async function loadRecords() {
    recordsRequested = true;
    try {
      const response = await fetch(Weather.recordPath, { cache: 'no-store' });
      if (!response.ok && response.status !== 404) throw new Error('weather records unavailable');
      if (response.ok) realRows = Weather.readRows(await response.json());
      recordsError = false;
    } catch (_) {
      recordsError = true;
    }
    render();
  }

  async function loadReal() {
    if (realBusy) return;
    realBusy = true;
    loaded = true;
    render();
    try {
      realLive = await Weather.requestToday({ signal: AbortSignal.timeout(15000) });
      realError = null;
    } catch (error) {
      realError = error;
    } finally {
      realBusy = false;
      render();
    }
  }

  async function replay(id) {
    if (!labMode || labBusy) return;
    selection = undefined;
    labBusy = true;
    render();
    try {
      if (!fixtureManifest) {
        const response = await fetch('data/t04/fixture-manifest.json');
        if (!response.ok) throw new TypeError('fixture manifest unavailable');
        fixtureManifest = (await response.json()).fixtures;
      }
      const entry = fixtureManifest.find((item) => item.fixture_id === id);
      if (!entry) throw new TypeError('fixture unavailable');
      const response = await fetch(`data/t04/fixtures/${entry.file}`);
      if (!response.ok) throw new TypeError('fixture unavailable');
      const fixture = await response.json();
      if (fixture.fixture_id !== id) throw new TypeError('fixture id mismatch');
      const reading = Weather.fromFixture(fixture);
      labRows = Weather.upsert(labRows, reading);
      labLive = reading;
      labError = null;
    } catch (error) {
      labError = error;
    } finally {
      labBusy = false;
      render();
    }
  }

  function openMode() {
    const wasLab = labMode;
    labMode = Core.isLabHash(location.hash);
    if (wasLab !== labMode) selection = undefined;
    lab.hidden = !labMode;
    legacyBox.classList.toggle('synthetic-weather-active', labMode);
    if (labMode) {
      panel.open = true;
      render();
      if (!recordsRequested) void loadRecords();
    } else if (panel.open && !loaded) {
      void loadReal();
      void loadRecords();
    } else {
      render();
    }
  }

  for (const id of Core.FIXTURE_ORDER.failures) {
    const kind = ['timeout', 'auth', 'rate_limit', 'offline', 'schema_error'][fixtureList.length];
    fixtureList.add(new Option(Core.ERROR_INFO[kind].label, id));
  }
  lab.addEventListener('click', (event) => {
    const action = event.target.closest('button')?.dataset.replay;
    if (!action) return;
    if (action === 'reset') {
      labRows = [];
      labLive = undefined;
      labError = null;
      if (selection?.src === 'lab') selection = undefined;
      render();
      return;
    }
    void replay(action === 'failure' ? fixtureList.value : action);
  });
  retry.addEventListener('click', () => {
    if (labMode) void replay('T04-RECOVER-D2');
    else void loadReal();
  });
  saved.addEventListener('click', (event) => {
    const { recordDate: date, recordSrc: src } = event.target.closest('button')?.dataset || {};
    if (date && (labMode || src === 'real')) { selection = { src: labMode ? src : 'real', date }; render(); historyButton.focus(); }
  });
  historyButton.addEventListener('click', () => { selection = undefined; render(); card.querySelector('h4').focus(); });
  panel.addEventListener('toggle', () => {
    if (panel.open) panel.scrollTop = 0;
    if (panel.open && !labMode && (!loaded || (realLive && realLive.reading.record_date !== Core.kstDate(new Date())))) {
      void loadReal();
      void loadRecords();
    }
  });
  panel.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && panel.open && !labMode) { panel.open = false; panel.querySelector('summary').focus(); }
  });
  window.addEventListener('hashchange', openMode);
  openMode();
})();
