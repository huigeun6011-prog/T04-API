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

  return {
    resetState, runFixture, applySuccessfulReading, applyError, comparisonFor,
    validateNormalizedReading, kstDate, FIXTURE_ORDER, ERROR_INFO, describe,
    compareHourly, latestSignalRows, previousRow, hasCompleteHourly, roundToTenth
  };
});
