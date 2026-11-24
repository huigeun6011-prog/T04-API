(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./t04-core.js'));
  else root.DailyWeather = factory(root.T04Core);
})(globalThis, function (Core) {
  'use strict';

  const timezone = 'Asia/Seoul';
  const units = { temperature_2m: '°C', precipitation: 'mm', snowfall: 'cm' };
  const fields = Object.keys(units);
  const signal = 'daejeon-daily-mean-temperature';
  const endpoint = 'https://api.open-meteo.com/v1/forecast';
  const archiveEndpoint = 'https://archive-api.open-meteo.com/v1/archive';
  const fixtureUrl = 'https://fixtures.aleph.invalid/t04/weather';
  const recordPath = 'data/t04/weather-daily.json';
  const dateHours = (date) => Array.from({ length: 24 }, (_, hour) => `${date}T${String(hour).padStart(2, '0')}:00`);

  function sourceUrl(date, url = endpoint) {
    const params = new URLSearchParams({
      latitude: '36.35', longitude: '127.38', hourly: fields.join(','),
      timezone, start_date: date, end_date: date
    });
    return `${url}?${params}`;
  }

  function archiveUrl(dataDate) {
    return sourceUrl(dataDate, archiveEndpoint);
  }

  function previousDate(date) {
    const midnight = new Date(`${date}T00:00:00Z`);
    midnight.setUTCDate(midnight.getUTCDate() - 1);
    return midnight.toISOString().slice(0, 10);
  }

  function dataDateOf(record) {
    return Core.kstDate(record.reading.source_time);
  }

  function kindOf(record) {
    return new URL(record.reading.source_url).hostname === 'archive-api.open-meteo.com' ? 'observed' : 'forecast';
  }

  function normalize(raw, fetchedAt, { synthetic = false, dataDate = Core.kstDate(fetchedAt), timeBasis } = {}) {
    const date = Core.kstDate(fetchedAt);
    const observed = dataDate !== date;
    const imported = timeBasis === 'file_mtime';
    if (timeBasis !== undefined && (!imported || synthetic || !observed || dataDate >= date)) {
      throw new TypeError('파일 수정 시각을 쓰는 기록은 조회일보다 앞선 관측 자료여야 합니다.');
    }
    if (observed && (synthetic || (!imported && dataDate !== previousDate(date)))) {
      throw new TypeError('관측 자료일은 조회일의 KST 전날이어야 합니다.');
    }
    const expectedTimes = dateHours(dataDate);
    const hourly = raw?.hourly;
    if (raw?.timezone !== timezone || !Array.isArray(hourly?.time) || hourly.time.length !== 24 ||
        !expectedTimes.every((time, i) => hourly.time[i] === time) ||
        !fields.every((field) => raw.hourly_units?.[field] === units[field] &&
          Array.isArray(hourly[field]) && hourly[field].length === 24 &&
          expectedTimes.every((_, i) => Number.isFinite(hourly[field][i]) &&
            (field === 'temperature_2m' || hourly[field][i] >= 0)))) {
      throw new TypeError('대전의 KST 00~23시 날씨 또는 단위 형식이 올바르지 않습니다.');
    }
    const sum = (values) => values.reduce((total, value) => total + value, 0);
    const round = Core.roundToTenth;
    const temperatures = hourly.temperature_2m;
    const summary = {
      mean: round(sum(temperatures) / 24),
      min: round(Math.min(...temperatures)),
      max: round(Math.max(...temperatures)),
      precipitation: round(sum(hourly.precipitation)),
      snowfall: round(sum(hourly.snowfall))
    };
    let source_name = 'Open-Meteo 대전 예보';
    let source_url = sourceUrl(dataDate);
    if (observed) {
      source_name = 'Open-Meteo 대전 관측(archive)';
      source_url = archiveUrl(dataDate);
    } else if (synthetic) {
      source_name = 'ALEPH 합성 날씨';
      source_url = fixtureUrl;
    }
    const reading = {
      signal_id: signal, normalized_value: summary.mean, unit: '°C',
      source_name, source_url,
      source_time: `${dataDate}T00:00:00+09:00`, fetched_at: new Date(fetchedAt).toISOString(),
      record_timezone: timezone, record_date: date
    };
    Core.validateNormalizedReading(reading);
    return { reading, summary, raw, ...(imported ? { time_basis: timeBasis } : {}) };
  }

  function validateRecord(record) {
    const reading = record?.reading;
    Core.validateNormalizedReading(reading);
    const dataDate = record.time_basis === 'file_mtime' ? dataDateOf(record)
      : kindOf(record) === 'observed' ? previousDate(reading.record_date) : reading.record_date;
    const normalized = normalize(record.raw, reading.fetched_at, {
      dataDate, synthetic: reading.source_url === fixtureUrl, timeBasis: record.time_basis
    });
    for (const field of ['reading', 'summary']) {
      if (!Object.entries(normalized[field]).every(([key, value]) => record[field]?.[key] === value)) {
        throw new TypeError('저장한 날씨 값과 원본 응답의 계산값이 다릅니다.');
      }
    }
    return normalized;
  }

  function readRows(doc) {
    if (!Array.isArray(doc?.rows)) throw new TypeError('일별 날씨 기록 형식이 올바르지 않습니다.');
    const rows = doc.rows.map(validateRecord).sort((a, b) => a.reading.record_date.localeCompare(b.reading.record_date));
    if (new Set(rows.map((row) => row.reading.record_date)).size !== rows.length) {
      throw new TypeError('일별 날씨 기록에 중복 날짜가 있습니다.');
    }
    return rows;
  }

  function upsert(rows, record) {
    const date = record.reading.record_date;
    return [...rows.filter((row) => row.reading.record_date !== date), record]
      .sort((a, b) => a.reading.record_date.localeCompare(b.reading.record_date));
  }

  function latestRow(rows) {
    let latest = null;
    for (const row of rows) {
      if (!latest || row.reading.record_date > latest.reading.record_date) latest = row;
    }
    return latest;
  }

  async function requestWeather(observed, { fetchImpl = fetch, now = () => new Date(), signal } = {}) {
    const date = Core.kstDate(now());
    const dataDate = observed ? previousDate(date) : date;
    const pending = () => Object.assign(new Error('Open-Meteo Archive 자료가 아직 완전하지 않습니다.'), {
      kind: 'pending', date, dataDate
    });
    let response;
    try {
      response = await fetchImpl(observed ? archiveUrl(dataDate) : sourceUrl(dataDate), { cache: 'no-store', signal });
    } catch (error) {
      if (signal?.aborted) throw Object.assign(new Error('요청이 취소되었습니다.'), { name: 'AbortError' });
      const kind = signal?.aborted || error.name === 'TimeoutError' ? 'timeout' : 'offline';
      throw Object.assign(new Error('날씨 API에 연결하지 못했습니다.'), { kind });
    }
    if (!response.ok) {
      if (observed && response.status === 400) {
        const body = await response.json().catch(() => null);
        if (typeof body?.reason === 'string' &&
            /(?:start_date|end_date).*(?:out of (?:the )?(?:allowed )?range)|no data available/i.test(body.reason)) {
          throw pending();
        }
      }
      const kind = {401: 'auth', 403: 'auth', 408: 'timeout', 429: 'rate_limit', 504: 'timeout'}[response.status]
        || (response.status >= 500 ? 'offline' : 'schema_error');
      throw Object.assign(new Error(`Open-Meteo HTTP ${response.status}`), { kind, retryAfter: response.headers.get('Retry-After') });
    }
    if (observed && response.status === 204) throw pending();
    const raw = await response.json();
    const fetchedAt = now();
    if (date !== Core.kstDate(fetchedAt)) throw Object.assign(new Error('조회 중 날짜가 바뀌었습니다. 다시 시도해 주세요.'), { kind: 'schema_error' });
    if (observed && (!Array.isArray(raw?.hourly?.time) || raw.hourly.time.length !== 24 ||
        !fields.every((field) => Array.isArray(raw.hourly[field]) && raw.hourly[field].length === 24 &&
          dateHours(dataDate).every((_, i) => Number.isFinite(raw.hourly[field][i]))))) {
      throw pending();
    }
    return normalize(raw, fetchedAt, { dataDate });
  }

  let lastSuccessfulForecast;
  async function requestToday(options) {
    const record = await requestWeather(false, options);
    if (options?.signal?.aborted) throw Object.assign(new Error('요청이 취소되었습니다.'), { name: 'AbortError' });
    lastSuccessfulForecast = structuredClone(record);
    return record;
  }

  function getLastSuccessfulForecast() {
    return lastSuccessfulForecast ? structuredClone(lastSuccessfulForecast) : undefined;
  }

  function requestObserved(options) {
    return requestWeather(true, options);
  }

  function fromFixture(fixture) {
    const replay = Core.runFixture(Core.resetState(), fixture);
    if (replay.status.error_code !== 'none') {
      const kind = replay.status.error_code;
      throw Object.assign(new Error(Core.ERROR_INFO[kind].label), { kind, retryAfter: replay.last_run.retry_after_seconds });
    }
    const source = fixture.payload;
    const date = Core.kstDate(source.fetched_at);
    const variant = source.normalized_value;
    // Translate the public fixture's successful signal into deterministic hourly weather.
    const time = dateHours(date);
    const base = 6 + (variant - 100) / 4;
    const hourly = {
      time,
      temperature_2m: time.map((_, i) => Core.roundToTenth(base + (i - 11.5) * (variant === 100 ? 0.2 : 0.24))),
      precipitation: time.map((_, i) => i < 3 ? Core.roundToTenth((variant - 95) / 25) : 0),
      snowfall: time.map((_, i) => i < 2 ? Core.roundToTenth((variant - 100) / 20) : 0)
    };
    return normalize({ timezone, hourly_units: units, hourly }, source.fetched_at, { synthetic: true });
  }

  return {
    recordPath, normalize, validateRecord, readRows, upsert, requestToday, fromFixture, getLastSuccessfulForecast,
    archiveUrl, requestObserved, latestRow, dataDateOf, kindOf
  };
});
