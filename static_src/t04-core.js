(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else if (typeof define === 'function' && define.amd) {
    define([], factory);
  } else {
    root.T04Core = factory();
  }
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  const NORMALIZED_KEYS = [
    'signal_id', 'normalized_value', 'unit', 'source_name', 'source_url',
    'source_time', 'fetched_at', 'record_timezone', 'record_date'
  ].sort();
  const HOURLY_METRICS = ['temperature_2m', 'precipitation', 'snowfall'];
  const ERROR_INFO = Object.freeze({
    timeout: Object.freeze({
      label: '제한시간 초과',
      cause: '제한시간 안에 외부 원천이 응답하지 않았습니다.',
      action: '잠시 후 다시 시도하세요.'
    }),
    auth: Object.freeze({
      label: '외부 원천 401/403 거절',
      cause: '외부 데이터 원천이 요청을 거절했습니다. 앱 로그인과는 관계없습니다.',
      action: '원천의 접근 상태를 확인한 뒤 다시 시도하세요.'
    }),
    rate_limit: Object.freeze({
      label: '호출 제한',
      cause: '외부 원천이 요청 횟수를 제한했습니다.',
      action: 'Retry-After가 표시되면 그 시간만큼 기다린 뒤 다시 시도하세요.'
    }),
    offline: Object.freeze({
      label: '연결 끊김',
      cause: '네트워크 연결이 끊겼습니다.',
      action: '연결을 확인한 뒤 다시 시도하세요.'
    }),
    schema_error: Object.freeze({
      label: '응답 형식 변경',
      cause: '외부 응답의 형식이 달라 새 값을 저장하지 않았습니다.',
      action: '원천 응답 형식과 정규화 규칙을 확인하세요.'
    })
  });
  const baseline = Object.freeze(['T04-NORMAL-D1-A', 'T04-NORMAL-D1-B']);
  const FIXTURE_ORDER = Object.freeze({
    success: Object.freeze([...baseline, 'T04-NORMAL-D2']),
    baseline,
    failures: Object.freeze([
      'T04-TIMEOUT', 'T04-AUTH-401', 'T04-RATE-429', 'T04-OFFLINE', 'T04-SCHEMA-BREAK'
    ]),
    recovery: Object.freeze([...baseline, 'T04-TIMEOUT', 'T04-RECOVER-D2'])
  });
  const kstFormatter = new Intl.DateTimeFormat('en', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit'
  });

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function kstDate(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) {
      throw new TypeError('fetched_at must be a valid ISO-8601 date-time');
    }
    const parts = Object.fromEntries(kstFormatter.formatToParts(date).map(({ type, value }) => [type, value]));
    return `${parts.year}-${parts.month}-${parts.day}`;
  }

  function validateNormalizedReading(reading) {
    if (!reading || typeof reading !== 'object' || Array.isArray(reading)) {
      throw new TypeError('normalized reading must be an object');
    }
    const keys = Object.keys(reading).sort();
    if (keys.length !== NORMALIZED_KEYS.length || keys.some((key, index) => key !== NORMALIZED_KEYS[index])) {
      throw new TypeError(`normalized reading keys must be exactly: ${NORMALIZED_KEYS.join(', ')}`);
    }
    if (typeof reading.signal_id !== 'string' ||
        !/^[a-z0-9][a-z0-9._-]*$/.test(reading.signal_id) || reading.signal_id.length > 100) {
      throw new TypeError('signal_id is invalid');
    }
    if (!Number.isFinite(reading.normalized_value)) {
      throw new TypeError('normalized_value must be a finite number');
    }
    for (const [field, maxLength] of [['unit', 24], ['source_name', 120]]) {
      const value = reading[field];
      if (typeof value !== 'string' || value.trim() === '' || [...value].length > maxLength) {
        throw new TypeError(`${field} must be a non-empty string of at most ${maxLength} characters`);
      }
    }
    if (typeof reading.source_url !== 'string' || !reading.source_url.startsWith('https://')) {
      throw new TypeError('source_url must use HTTPS');
    }
    try {
      new URL(reading.source_url);
    } catch {
      throw new TypeError('source_url must be an absolute URL');
    }
    if (reading.source_time !== null && !isDateTime(reading.source_time)) {
      throw new TypeError('source_time must be a valid date-time or null');
    }
    if (!isDateTime(reading.fetched_at)) {
      throw new TypeError('fetched_at must be a valid date-time');
    }
    if (reading.record_timezone !== 'Asia/Seoul') {
      throw new TypeError('record_timezone must be Asia/Seoul');
    }
    if (reading.record_date !== kstDate(reading.fetched_at)) {
      throw new TypeError('record_date must be the Asia/Seoul date derived from fetched_at');
    }
    return true;
  }

  function isDateTime(value) {
    return typeof value === 'string' &&
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i.test(value) &&
      Number.isFinite(Date.parse(value));
  }

  function emptyComparison(state) {
    return { state, direction: null, magnitude: null, unit: null };
  }

  function resetState() {
    return {
      schema_version: 'aleph-t04-evaluation-state-v1',
      daily_readings: [],
      current_reading: null,
      status: null,
      last_delta: null,
      last_comparison: emptyComparison('insufficient'),
      last_run: null,
      sequence: 0
    };
  }

  function comparisonFor(rows, current) {
    const previous = rows
      .filter((row) => row.signal_id === current.signal_id && row.record_date < current.record_date)
      .sort((left, right) => right.record_date.localeCompare(left.record_date))[0];
    if (!previous) return emptyComparison('insufficient');
    if (previous.unit !== current.unit) return emptyComparison('unit_mismatch');

    const signed = current.normalized_value - previous.normalized_value;
    let direction = 'unchanged';
    if (signed > 0) direction = 'increase';
    if (signed < 0) direction = 'decrease';
    return { state: 'comparable', direction, magnitude: Math.abs(signed), unit: current.unit };
  }

  function latestSignalRows(rows) {
    const latest = rows.at(-1)?.reading;
    if (!latest) return [];
    return rows.filter((row) => row.reading.signal_id === latest.signal_id)
      .sort((left, right) => left.reading.record_date.localeCompare(right.reading.record_date));
  }

  function previousRow(rows, current) {
    const { signal_id, record_date } = current.reading;
    let previous = null;
    for (const row of rows) {
      if (row.reading.signal_id === signal_id && row.reading.record_date < record_date &&
          (!previous || row.reading.record_date > previous.reading.record_date)) {
        previous = row;
      }
    }
    return previous;
  }

  function hasCompleteHourly({ target_date: date, hourly, hourly_units: units }) {
    if (typeof date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(date) ||
        !Array.isArray(hourly?.time) || hourly.time.length !== 24) {
      return false;
    }
    for (const metric of HOURLY_METRICS) {
      if (typeof units?.[metric] !== 'string' || units[metric].trim() === '' ||
          !Array.isArray(hourly[metric]) || hourly[metric].length !== 24) {
        return false;
      }
    }
    for (let hour = 0; hour < 24; hour += 1) {
      if (hourly.time[hour] !== `${date}T${String(hour).padStart(2, '0')}:00` ||
          !HOURLY_METRICS.every((metric) => Number.isFinite(hourly[metric][hour]))) {
        return false;
      }
    }
    return true;
  }

  function roundToTenth(value) {
    // Round to tenths, with ties away from zero and a tolerance for binary arithmetic.
    const rounded = Math.round(Math.abs(value) * 10 + 1e-9) / 10;
    return rounded === 0 ? 0 : Math.sign(value) * rounded;
  }

  function roundDelta(value) {
    // Round to hundredths, with ties away from zero and a tolerance for binary arithmetic.
    const magnitude = Math.round(Math.abs(value) * 100 + 1e-9) / 100;
    return magnitude === 0 ? 0 : Math.sign(value) * magnitude;
  }

  function compareHourly(previous, current) {
    const unavailable = (reason) => ({ comparable: false, reason, hours: [], summary: null });
    if (!previous) return unavailable('no_previous');
    if (!previous.reading || !current?.reading ||
        previous.reading.signal_id !== current.reading.signal_id ||
        previous.reading.record_date === current.reading.record_date ||
        !hasCompleteHourly(previous) || !hasCompleteHourly(current)) {
      return unavailable('incomplete');
    }
    if (previous.reading.unit !== current.reading.unit ||
        HOURLY_METRICS.some((metric) => previous.hourly_units[metric] !== current.hourly_units[metric])) {
      return unavailable('unit_mismatch');
    }

    let temperatureDeltaTotal = 0;
    let maxAbsDelta = -1;
    let hourOfMax = null;
    const hours = current.hourly.time.map((_, hour) => {
      const prev = {};
      const curr = {};
      const delta = {};
      for (const metric of HOURLY_METRICS) {
        prev[metric] = previous.hourly[metric][hour];
        curr[metric] = current.hourly[metric][hour];
        delta[metric] = roundDelta(curr[metric] - prev[metric]);
      }
      temperatureDeltaTotal += curr.temperature_2m - prev.temperature_2m;
      const absDelta = Math.abs(delta.temperature_2m);
      if (absDelta > maxAbsDelta) {
        maxAbsDelta = absDelta;
        hourOfMax = hour;
      }
      return { hour, prev, curr, delta };
    });
    return {
      comparable: true,
      reason: null,
      hours,
      summary: {
        mean_delta: roundDelta(temperatureDeltaTotal / hours.length),
        max_abs_delta_temperature: maxAbsDelta,
        hour_of_max_abs: hourOfMax
      }
    };
  }

  function applySuccessfulReading(inputState, reading, meta = {}) {
    validateNormalizedReading(reading);
    const state = clone(inputState);
    const index = state.daily_readings.findIndex(
      (row) => row.signal_id === reading.signal_id && row.record_date === reading.record_date
    );
    const existing = state.daily_readings[index];
    const row = {
      record_id: existing?.record_id ?? `demo-${reading.signal_id}-${reading.record_date}`,
      signal_id: reading.signal_id,
      record_date: reading.record_date,
      normalized_value: reading.normalized_value,
      unit: reading.unit,
      first_fetched_at: existing?.first_fetched_at ?? reading.fetched_at,
      last_fetched_at: reading.fetched_at,
      reading: clone(reading)
    };
    if (index >= 0) state.daily_readings[index] = row;
    else state.daily_readings.push(row);
    state.daily_readings.sort((left, right) => left.record_date.localeCompare(right.record_date));

    state.current_reading = clone(reading);
    state.status = { freshness: 'fresh', error_code: 'none' };
    state.last_comparison = comparisonFor(state.daily_readings, row);
    state.last_delta = state.last_comparison.magnitude;
    state.sequence += 1;
    state.last_run = {
      fixture_id: meta.fixture_id || null,
      virtual_now: meta.virtual_now || reading.fetched_at,
      outcome: 'success',
      error_code: 'none',
      retry_after_seconds: null
    };
    return state;
  }

  function applyError(inputState, code, meta = {}) {
    if (!Object.prototype.hasOwnProperty.call(ERROR_INFO, code)) {
      throw new TypeError(`unsupported error code: ${code}`);
    }
    const state = clone(inputState);
    state.status = { freshness: 'stale', error_code: code };
    state.sequence += 1;
    state.last_run = {
      fixture_id: meta.fixture_id || null,
      virtual_now: meta.virtual_now || null,
      outcome: 'error',
      error_code: code,
      retry_after_seconds: meta.retry_after_seconds ?? null
    };
    return state;
  }

  function runFixture(state, fixture) {
    const { mode, status, headers } = fixture.transport;
    const retryAfter = headers?.['retry-after'];
    const retrySeconds = retryAfter ? Number(retryAfter) : null;
    const meta = {
      fixture_id: fixture.fixture_id,
      virtual_now: fixture.virtual_now,
      retry_after_seconds: Number.isFinite(retrySeconds) ? retrySeconds : null
    };
    if (mode === 'timeout') return applyError(state, 'timeout', meta);
    if (mode === 'offline') return applyError(state, 'offline', meta);
    if (status === 401 || status === 403) return applyError(state, 'auth', meta);
    if (status === 429) return applyError(state, 'rate_limit', meta);
    if (status >= 200 && status < 300) {
      try {
        return applySuccessfulReading(state, fixture.payload, meta);
      } catch (error) {
        if (!(error instanceof TypeError)) throw error;
      }
    }
    return applyError(state, 'schema_error', meta);
  }

  function describe(state) {
    const current = state.current_reading;
    const stored = current && state.daily_readings.find(
      (row) => row.signal_id === current.signal_id && row.record_date === current.record_date
    );
    return {
      freshness: state.status?.freshness ?? null,
      error_code: state.status?.error_code ?? null,
      row_count: state.daily_readings.length,
      stored_value: stored?.normalized_value ?? null,
      last_good_value: current?.normalized_value ?? null,
      record_date: current?.record_date ?? null,
      delta: state.last_delta,
      comparison: { ...state.last_comparison },
      retry_after_seconds: state.last_run?.retry_after_seconds ?? null
    };
  }

  /* ───────── 운행일 총 승하차 정보판 (순수 함수: 화면과 node 테스트가 함께 쓴다) ───────── */
  const BUSINESS_SIGNAL_ID = 'daejeon-metro-business-day-total-passengers';
  const WEEKDAYS_KO = ['일', '월', '화', '수', '목', '금', '토'];
  const BUSINESS_HOUR_KEYS = [...Array.from({ length: 19 }, (_, i) => String(i + 5)), '24'];
  // 날짜 T 14시(KST) 이후 T-1일 자료가 열린다. 완성(05~23시 + 다음 날 00시)되는 최신 운행일은
  // T 15시 이후 T-2, 그 전에는 T-3 이다. 그보다 최근 운행일(오늘·어제 등)은 '미집계'다.
  const PUBLISH_HOUR_KST = 15;

  function addDaysStr(date, count) {
    const d = new Date(`${date}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() + count);
    return d.toISOString().slice(0, 10);
  }
  function daysBetween(from, to) {
    return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86400000);
  }
  function weekdayKo(date) { return WEEKDAYS_KO[new Date(`${date}T00:00:00Z`).getUTCDay()]; }

  function latestCompleteDay(nowIso) {
    const kst = new Date(Date.parse(nowIso) + 9 * 3600000);
    return addDaysStr(kst.toISOString().slice(0, 10), kst.getUTCHours() >= PUBLISH_HOUR_KST ? -2 : -3);
  }

  // 운행일 행만 골라 운행일마다 가장 최근에 조회한 행 하나만 남기고 운행일 순으로 정렬한다.
  function businessRows(rows) {
    const byDay = new Map();
    for (const row of Array.isArray(rows) ? rows : []) {
      const r = row?.reading;
      if (!r || r.signal_id !== BUSINESS_SIGNAL_ID || !/^\d{4}-\d{2}-\d{2}$/.test(row.business_day ?? '') ||
          !Number.isFinite(r.normalized_value)) continue;
      const old = byDay.get(row.business_day);
      if (!old || old.reading.record_date <= r.record_date) byDay.set(row.business_day, row);
    }
    return [...byDay.values()].sort((a, b) => a.business_day.localeCompare(b.business_day));
  }

  // 오늘부터 거꾸로 count 일. state: pending(미집계, 정상) | recorded(숫자) | not_recorded(완성됐지만 우리 기록 없음)
  function recentDays(rows, nowIso, count = 7) {
    const today = kstDate(nowIso);
    const complete = latestCompleteDay(nowIso);
    const byDay = new Map(businessRows(rows).map((row) => [row.business_day, row]));
    return Array.from({ length: count }, (_, i) => {
      const date = addDaysStr(today, -i);
      const base = { date, weekday: weekdayKo(date) };
      if (date > complete) return { ...base, state: 'pending' };
      const row = byDay.get(date);
      return row ? { ...base, state: 'recorded', value: row.reading.normalized_value, unit: row.reading.unit }
        : { ...base, state: 'not_recorded' };
    });
  }

  // 저장된 운행일 행 중 가장 최근 두 개의 총합 차이. 계산식과 두 입력값을 함께 돌려준다.
  function dayOverDay(rows) {
    const list = businessRows(rows);
    if (list.length < 2) return { state: 'no_previous' };
    const [prevRow, lastRow] = list.slice(-2);
    const pick = (row) => ({ business_day: row.business_day, weekday: weekdayKo(row.business_day), value: row.reading.normalized_value });
    const prev = pick(prevRow);
    const last = pick(lastRow);
    const unit = lastRow.reading.unit;
    if (prevRow.reading.unit !== unit) return { state: 'unit_mismatch' };
    const delta = last.value - prev.value;
    const gap = daysBetween(prev.business_day, last.business_day);
    return {
      state: 'ok', prev, last, unit, delta, days_apart: gap, consecutive: gap === 1,
      direction: delta > 0 ? 'increase' : delta < 0 ? 'decrease' : 'unchanged',
      formula: `${last.value} − ${prev.value} = ${delta}`
    };
  }

  const isLabHash = (hash) => hash === '#t04-lab';

  // 정보판이 daily.json 을 불러올 때의 실패를 ERROR_INFO 의 다섯 유형으로 분류한다.
  function classifyLoadError(error) {
    const status = error?.status;
    if (status === 401 || status === 403) return 'auth';
    if (status === 429) return 'rate_limit';
    if (status === 408 || status === 504) return 'timeout';
    if (typeof status === 'number' && status >= 500) return 'offline';
    if (typeof status === 'number') return 'schema_error';
    if (error?.name === 'AbortError' || error?.name === 'TimeoutError') return 'timeout';
    if (error instanceof TypeError) return 'offline'; // fetch 가 네트워크 오류로 던지는 TypeError
    return 'schema_error';
  }

  // 원본 XML 두 개로 운행일 합계를 다시 계산한다(백엔드 scripts/t04_daily_record.mjs 와 같은 규칙).
  // D일 05~23시 + D+1일 00시, 승차·하차·모든 권종·모든 역. 자료가 비었으면 null.
  function sumBusinessDayXml(xmlD, xmlNext, day) {
    const tag = (text, name) => text.match(new RegExp(`<${name}>([^<]*)</${name}>`))?.[1];
    const parse = (xml, date) => [...String(xml).matchAll(/<item>[\s\S]*?<\/item>/g)].map(([item]) => {
      const flag = tag(item, 'entryFlag');
      const station = tag(item, 'stationNo');
      if (tag(item, 'businessDay') !== date.replaceAll('-', '') || !station || !['0', '1'].includes(flag)) {
        throw new TypeError('XML item is invalid');
      }
      const hours = Array.from({ length: 24 }, (_, h) => {
        const value = Number(tag(item, `cnt${String(h).padStart(2, '0')}`));
        if (!Number.isInteger(value) || value < 0) throw new TypeError('XML hour is invalid');
        return value;
      });
      return { station, flag, hours };
    });
    const itemsD = parse(xmlD, day);
    const itemsNext = parse(xmlNext, addDaysStr(day, 1));
    const empty = (items) => items.length === 0 || items.every((i) => i.hours.every((v) => v === 0));
    if (empty(itemsD) || empty(itemsNext)) return null;
    const hourly = Object.fromEntries(BUSINESS_HOUR_KEYS.map((k) => [k, 0]));
    const stations = {};
    const add = (item, hour, key) => {
      hourly[key] += item.hours[hour];
      const st = (stations[item.station] ??= { boardings: 0, alightings: 0 });
      st[item.flag === '0' ? 'boardings' : 'alightings'] += item.hours[hour];
    };
    for (const item of itemsD) for (let h = 5; h <= 23; h += 1) add(item, h, String(h));
    for (const item of itemsNext) add(item, 0, '24');
    return { total: Object.values(hourly).reduce((a, b) => a + b, 0), hourly, stations };
  }


  /* ───────── 기준일 선택 + 7일 선 그래프 (순수 함수) ───────── */
  // 역 번호 → 이름. 근거: 저장소 관행 stationNo = 101 + 역 순번(scripts/build_web_station_profile.py,
  // scripts/data_prep/diagnose_feasibility_bound.py)이고 순번·이름은 web/app.js STATIONS 와 같다(판암 0 ~ 반석 21).
  const STATION_NAMES = Object.freeze(['판암', '신흥', '대동', '대전', '중앙로', '중구청', '서대전네거리', '오룡',
    '용문', '탄방', '시청', '정부청사', '갈마', '월평', '갑천', '유성온천', '구암', '현충원', '월드컵경기장', '노은', '지족', '반석']);
  function stationName(no) {
    const n = Number(no);
    return Number.isInteger(n) && n >= 101 && n < 101 + STATION_NAMES.length ? STATION_NAMES[n - 101] : null;
  }
  function stationLabel(no) {
    const name = stationName(no);
    return name ? `${no}번 ${name}` : `${no}번`;
  }

  const isDateStr = (v) => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) &&
    new Date(`${v}T00:00:00Z`).toISOString().slice(0, 10) === v;

  // business_days.json 검증. 형식이 틀리면 TypeError(+status 200 → 화면에서 schema_error). 통과하면 days 배열을 돌려준다.
  function validateBusinessDays(doc) {
    if (!doc || typeof doc !== 'object' || !Array.isArray(doc.days)) throw new TypeError('days must be an array');
    for (const d of doc.days) {
      if (!d || !isDateStr(d.business_day) || !Number.isFinite(d.total) || d.total < 0) throw new TypeError('day entry is invalid');
      if (d.weather != null && (typeof d.weather !== 'object' || Array.isArray(d.weather))) throw new TypeError('weather is invalid');
    }
    return doc.days;
  }

  // 기준일 포함 count 일(기준일-(count-1) ~ 기준일), 오름차순.
  function weekWindow(baseDate, count = 7) {
    return Array.from({ length: count }, (_, i) => addDaysStr(baseDate, i - (count - 1)));
  }

  const fixed1 = (v) => Number(v).toFixed(1);
  // 날씨 문구를 줄 단위로: 비 3.2mm / 눈 1.5cm / 비·눈 둘 다 / 강수 없음 / null → 날씨 자료 없음.
  function weatherLines(weather) {
    if (!weather || typeof weather !== 'object') return ['날씨 자료 없음'];
    const rain = Number.isFinite(weather.rain_mm) ? weather.rain_mm : Number.isFinite(weather.precip_mm) ? weather.precip_mm : null;
    const snow = Number.isFinite(weather.snow_cm) ? weather.snow_cm : null;
    switch (weather.kind) {
      case 'none': return ['강수 없음'];
      case 'rain': return rain == null ? ['날씨 자료 없음'] : [`비 ${fixed1(rain)}mm`];
      case 'snow': return snow == null ? ['날씨 자료 없음'] : [`눈 ${fixed1(snow)}cm`];
      case 'rain_snow': return rain == null || snow == null ? ['날씨 자료 없음'] : [`비 ${fixed1(rain)}mm`, `눈 ${fixed1(snow)}cm`];
      default: return ['날씨 자료 없음'];
    }
  }
  function weatherText(weather) { return weatherLines(weather).join('·'); }

  // 창의 각 날짜 상태. pending: 아직 집계 전(정상) | recorded: 값 있음 | no_data: 집계 완료일이지만 파일에 없음.
  function trendSeries(days, baseDate, nowIso, count = 7) {
    const complete = latestCompleteDay(nowIso);
    const byDay = new Map((Array.isArray(days) ? days : []).map((d) => [d.business_day, d]));
    return weekWindow(baseDate, count).map((date) => {
      const base = { date, mmdd: date.slice(5), weekday: weekdayKo(date) };
      if (date > complete) return { ...base, state: 'pending', weather: null, label: '미집계' };
      const d = byDay.get(date);
      if (!d) return { ...base, state: 'no_data', weather: null, label: '자료 없음' };
      return { ...base, state: 'recorded', value: d.total, weather: d.weather ?? null, label: null };
    });
  }

  // 0부터 시작하는 눈금. 최대값을 덮는 1·2·2.5·5×10^k 단계, 눈금 약 3~5개.
  function niceTicks(maxValue, target = 4) {
    const max = Number.isFinite(maxValue) && maxValue > 0 ? maxValue : 100000;
    const raw = max / target;
    const pow = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((c) => c >= raw);
    const top = Math.ceil(max / step - 1e-9) * step;
    const ticks = [];
    for (let v = 0; v <= top + step / 1e6; v += step) ticks.push(Math.round(v * 100) / 100);
    return { step, max: top, ticks };
  }

  // 그래프 좌표. 값이 없는 날(pending/no_data)은 점이 없고 선을 끊는다: segments 는 연속한 값 구간의 점 목록.
  function chartLayout(series, o = {}) {
    const g = { width: 640, left: 68, right: 16, top: 28, plotH: 190, ...o };
    const plotW = g.width - g.left - g.right;
    const colW = plotW / series.length;
    const { max, ticks } = niceTicks(Math.max(0, ...series.filter((p) => p.state === 'recorded').map((p) => p.value)));
    const bottom = g.top + g.plotH;
    const xAt = (i) => Math.round((g.left + colW * (i + 0.5)) * 100) / 100;
    const yAt = (v) => Math.round((bottom - (v / max) * g.plotH) * 100) / 100;
    const points = series.map((p, i) => ({ ...p, index: i, x: xAt(i), y: p.state === 'recorded' ? yAt(p.value) : null }));
    const segments = [];
    let run = [];
    for (const p of points) {
      if (p.state === 'recorded') run.push(p);
      else { if (run.length) segments.push(run); run = []; }
    }
    if (run.length) segments.push(run);
    const paths = segments.filter((s) => s.length >= 2).map((s) => s.map((p, i) => `${i ? 'L' : 'M'}${p.x} ${p.y}`).join(' '));
    return {
      ...g, plotW, colW, bottom, max, points, segments, paths,
      yTicks: ticks.map((v) => ({ value: v, y: yAt(v) }))
    };
  }

  // 그래프(role=img)용 요약 문장.
  function trendSummary(series) {
    const rec = series.filter((p) => p.state === 'recorded');
    const range = `${series[0].date}부터 ${series[series.length - 1].date}까지 7일`;
    if (!rec.length) return `${range}: 집계된 승하차 인원이 없습니다.`;
    const hi = rec.reduce((a, b) => (b.value > a.value ? b : a));
    const lo = rec.reduce((a, b) => (b.value < a.value ? b : a));
    const n = (v) => Number(v).toLocaleString('ko-KR');
    return `${range} 승하차 인원 선 그래프. 집계 ${rec.length}일, 미집계·자료 없음 ${series.length - rec.length}일. ` +
      `최대 ${hi.mmdd} ${n(hi.value)}명, 최소 ${lo.mmdd} ${n(lo.value)}명.`;
  }

  function parseDateInput(v) { return isDateStr(v) ? v : null; }

  return {
    resetState, runFixture, applySuccessfulReading, applyError, comparisonFor,
    validateNormalizedReading, kstDate, FIXTURE_ORDER, ERROR_INFO, describe,
    compareHourly, latestSignalRows, previousRow, hasCompleteHourly, roundToTenth,
    BUSINESS_SIGNAL_ID, BUSINESS_HOUR_KEYS, weekdayKo, addDaysStr, daysBetween, latestCompleteDay,
    businessRows, recentDays, dayOverDay, isLabHash, classifyLoadError, sumBusinessDayXml,
    STATION_NAMES, stationName, stationLabel, validateBusinessDays, weekWindow, weatherLines, weatherText,
    trendSeries, niceTicks, chartLayout, trendSummary, parseDateInput
  };
});
