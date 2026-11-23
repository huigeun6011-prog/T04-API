(function () {
  'use strict';

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
  const cacheKey = 'daejeon-daily-weather-v1';
  const kst = new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit'
  });
  const number = (value, unit) => `${value.toFixed(1)} ${unit}`;
  let lastReal;
  try {
    const stored = localStorage.getItem(cacheKey);
    if (stored) lastReal = Weather.validateRecord(JSON.parse(stored));
  } catch (_) { /* The browser may block storage or contain an outdated response. */ }
  let realRows = [];
  let recordsError = false;
  let realError;
  let realBusy = false;
  let labMode = false;
  let labBusy = false;
  let labRows = [];
  let labError;
  let fixtureManifest;
  let loaded = false;
  let selection;

  function recordMeta(record) {
    const { reading } = record;
    const name = reading.source_name;
    const source = labMode ? name : `<a href="${reading.source_url}" target="_blank" rel="noopener">${name}</a>`;
    return `<ul class="weather-meta">
      <li>출처 ${source}</li>
      <li>출처 시각 ${reading.record_date} 00:00~23:00 KST 시간별 예보</li>
      <li>조회 시각 ${kst.format(new Date(reading.fetched_at))} KST</li>
      <li>기준 시간대 ${reading.record_timezone}</li>
    </ul>`;
  }

  function renderValues(record) {
    if (!record) { values.replaceChildren(); return; }
    const { summary, raw: { hourly } } = record;
    const stats = [
      ['평균기온', summary.mean, '°C'], ['최저기온', summary.min, '°C'],
      ['최고기온', summary.max, '°C'], ['총강수량', summary.precipitation, 'mm'], ['총적설량', summary.snowfall, 'cm']
    ];
    const hours = hourly.time.map((time, i) =>
      `<tr><th scope="row">${time.slice(11)}</th><td>${number(hourly.temperature_2m[i], '°C')}</td><td>${number(hourly.precipitation[i], 'mm')}</td><td>${number(hourly.snowfall[i], 'cm')}</td></tr>`).join('');
    const wasOpen = values.querySelector('details')?.open;
    values.innerHTML = `<dl class="daily-weather__stats">${stats.map(([label, value, unit]) =>
      `<div><dt>${label}</dt><dd>${number(value, unit)}</dd></div>`).join('')}</dl>
      ${recordMeta(record)}
      <details ${wasOpen ? 'open' : ''}><summary>24시간 날씨</summary><div class="weather-hourly">
      <table><thead><tr><th scope="col">KST</th><th scope="col">기온</th><th scope="col">강수</th><th scope="col">적설</th></tr></thead><tbody>${hours}</tbody></table></div></details>`;
  }

  function renderRecords(rows) {
    const [older, latest] = rows.slice(-2);
    const sameHeading = saved.querySelector('details')?.open;
    const type = labMode ? '합성' : '실제';
    const count = ` KST 날짜별 ${type} 기록 ${rows.length}건`;
    let comparison = '비교하려면 서로 다른 KST 날짜의 기록이 필요합니다.';
    if (latest) {
      const change = Core.roundToTenth(latest.summary.mean - older.summary.mean);
      const gap = Core.daysBetween(older.reading.record_date, latest.reading.record_date);
      comparison = `${gap === 1 ? '전일 대비' : `최근 두 기록 비교 (${gap}일 차이)`} ${number(latest.summary.mean, '°C')} − ${number(older.summary.mean, '°C')} = ${change > 0 ? '+' : ''}${number(change, '°C')}`;
    }
    saved.innerHTML = `<details ${sameHeading || labMode ? 'open' : ''}><summary>${count}</summary>
      <p>${recordsError && !labMode ? '저장 기록을 읽지 못했습니다.' : comparison}</p>
      ${rows.map((row) => `<button type="button" class="update-retry" data-record-date="${row.reading.record_date}" aria-pressed="${selection === row.reading.record_date}">${row.reading.record_date} · ${number(row.summary.mean, '°C')}</button>`).join('')}
      </details>`;
  }

  function render() {
    const rows = labMode ? labRows : realRows;
    const error = labMode ? labError : realError;
    const busy = labMode ? labBusy : realBusy;
    const selected = !labMode && rows.find((row) => row.reading.record_date === selection);
    const live = labMode ? rows.at(-1) : lastReal;
    const shown = selected || live;
    const priorDay = !labMode && live && live.reading.record_date !== Core.kstDate(new Date());
    const stale = Boolean(!selected && live && (error || priorDay));
    const info = error && Core.ERROR_INFO[error.kind || 'schema_error'];
    const delay = Number(error?.retryAfter);
    const message = info ? `${info.label} (${error.kind || 'schema_error'}). ${info.cause} ${info.action}${delay > 0 ? ` ${delay}초 뒤에 재시도하세요.` : ''}` : '';
    const summary = selected ? '저장된 실제 응답 · 원본에서 재계산한 값과 일치'
      : stale ? '오래된 값 (stale) · 마지막 정상 응답'
      : live && labMode ? '정상 (fresh / none)' : '';
    status.textContent = [labMode && '합성 테스트 · 실제 기록과 분리', busy && !selected && '날씨를 불러오는 중입니다…', message, summary,
      !busy && !shown && !message && '아직 날씨가 없습니다.'].filter(Boolean).join(' ');
    status.classList.toggle('weather-error', Boolean(error));
    retry.hidden = !error;
    retry.disabled = busy;
    historyButton.hidden = !selected;
    lab.querySelectorAll('button, select').forEach((control) => { control.disabled = busy; });
    renderValues(shown);
    renderRecords(rows);
  }

  async function loadRecords() {
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
      lastReal = await Weather.requestToday({ signal: AbortSignal.timeout(15000) });
      realError = null;
      try { localStorage.setItem(cacheKey, JSON.stringify(lastReal)); } catch (_) { /* Optional offline cache. */ }
    } catch (error) {
      realError = error;
    } finally {
      realBusy = false;
      render();
    }
  }

  async function replay(id) {
    if (!labMode || labBusy) return;
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
      labRows = Weather.upsert(labRows, Weather.fromFixture(fixture));
      labError = null;
    } catch (error) {
      labError = error;
    } finally {
      labBusy = false;
      render();
    }
  }

  function openMode() {
    labMode = Core.isLabHash(location.hash);
    lab.hidden = !labMode;
    legacyBox.classList.toggle('synthetic-weather-active', labMode);
    if (labMode) {
      panel.open = true;
      render();
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
    if (action === 'reset') { labRows = []; labError = null; render(); return; }
    void replay(action === 'failure' ? fixtureList.value : action);
  });
  retry.addEventListener('click', () => {
    if (labMode) void replay('T04-RECOVER-D2');
    else void loadReal();
  });
  saved.addEventListener('click', (event) => {
    const date = event.target.closest('button')?.dataset.recordDate;
    if (!labMode && date) { selection = date; render(); historyButton.focus(); }
  });
  historyButton.addEventListener('click', () => { selection = undefined; render(); card.querySelector('h4').focus(); });
  panel.addEventListener('toggle', () => {
    if (panel.open && !labMode && (!loaded || (lastReal && lastReal.reading.record_date !== Core.kstDate(new Date())))) {
      void loadReal();
      void loadRecords();
    }
  });
  window.addEventListener('hashchange', openMode);
  openMode();
})();
