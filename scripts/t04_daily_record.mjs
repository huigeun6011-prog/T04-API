// T04 일별 기록: Open-Meteo 대전 다음 날 24시간 예보를 조회해 KST 날짜 키로 저장한다.
// 같은 날짜는 갱신, 다음 날짜는 새 행. 조회가 실패하면 파일을 건드리지 않는다(마지막 정상값 보존).
import { readFile, writeFile, rename, mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const { kstDate, validateNormalizedReading, hasCompleteHourly, roundToTenth } =
  createRequire(import.meta.url)('../static_src/t04-core.js');
export { kstDate };

export const SIGNAL_ID = 'daejeon-forecast-mean-temp-2m';
export const SOURCE_URL = 'https://api.open-meteo.com/v1/forecast?latitude=36.35&longitude=127.38&hourly=temperature_2m,precipitation,snowfall&timezone=Asia%2FSeoul';
const HOURLY_METRICS = ['temperature_2m', 'precipitation', 'snowfall'];

function nextDate(recordDate) {
  const date = new Date(`${recordDate}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

function forecastUrl(targetDate) {
  return `${SOURCE_URL}&start_date=${targetDate}&end_date=${targetDate}`;
}

function validateRow(row) {
  validateNormalizedReading(row?.reading);
  if (row.reading.signal_id !== SIGNAL_ID) return;
  if (row.target_date !== nextDate(row.reading.record_date) || !hasCompleteHourly(row) ||
      row.reading.unit !== row.hourly_units.temperature_2m) {
    throw new TypeError('forecast row must contain the next day and all 24 hours with matching units');
  }
}

// 아홉 필드로 정규화한 평균과 그 값을 계산한 시간별 예보, 원본을 함께 반환한다.
export function normalize(raw, fetchedAt) {
  try {
    const recordDate = kstDate(fetchedAt);
    const targetDate = nextDate(recordDate);
    const times = raw?.hourly?.time;
    if (!Array.isArray(times)) throw new TypeError('forecast times must be an array');
    const indices = [];
    for (const [index, time] of times.entries()) {
      if (typeof time === 'string' && time.startsWith(`${targetDate}T`)) indices.push(index);
    }
    indices.sort((left, right) => times[left].localeCompare(times[right]));

    const hourly = { time: indices.map((index) => times[index]) };
    const units = {};
    for (const metric of HOURLY_METRICS) {
      const values = raw.hourly[metric];
      if (!Array.isArray(values) || values.length !== times.length) {
        throw new TypeError(`${metric} must align with forecast times`);
      }
      hourly[metric] = indices.map((index) => values[index]);
      units[metric] = raw.hourly_units?.[metric];
    }
    const row = { target_date: targetDate, hourly, hourly_units: units, raw };
    if (!hasCompleteHourly(row)) throw new TypeError('expected 24 numeric forecast hours with units');

    const mean = hourly.temperature_2m.reduce((total, value) => total + value, 0) / 24;
    row.reading = {
      signal_id: SIGNAL_ID,
      normalized_value: roundToTenth(mean),
      unit: units.temperature_2m,
      source_name: 'Open-Meteo 대전 내일 시간별 예보(평균 기온)',
      source_url: forecastUrl(targetDate),
      source_time: new Date(`${targetDate}T00:00:00+09:00`).toISOString(),
      fetched_at: new Date(fetchedAt).toISOString(),
      record_timezone: 'Asia/Seoul',
      record_date: recordDate
    };
    validateNormalizedReading(row.reading);
    return row;
  } catch (cause) {
    throw new Error('schema_error', { cause });
  }
}

export function upsert(rows, row) {
  try {
    const { reading } = row;
    validateRow(row);
    const next = rows.filter((existing) => existing?.reading?.signal_id !== reading.signal_id ||
      existing.reading.record_date !== reading.record_date);
    for (const existing of next) validateRow(existing);
    next.push(row);
    return next.sort((a, b) => a.reading.record_date.localeCompare(b.reading.record_date));
  } catch (cause) {
    throw new Error('schema_error', { cause });
  }
}

export async function record(file, fetchImpl = fetch, now = () => new Date().toISOString()) {
  // Capture the request time once so a response crossing KST midnight uses the same window.
  const fetchedAt = now();
  const res = await fetchImpl(forecastUrl(nextDate(kstDate(fetchedAt))), { signal: AbortSignal.timeout(10000) });
  if (!res.ok) throw new Error(`http_${res.status}`);
  const raw = await res.json();
  const row = normalize(raw, fetchedAt);
  let doc = { rows: [] };
  try { doc = JSON.parse(await readFile(file, 'utf8')); } catch (e) { if (e.code !== 'ENOENT') throw e; }
  doc.rows = upsert(doc.rows, row);
  await mkdir(dirname(file), { recursive: true });
  await writeFile(`${file}.tmp`, JSON.stringify(doc, null, 2) + '\n');
  await rename(`${file}.tmp`, file); // 원자적 교체
  return doc;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  const file = process.argv[2] ?? 'static-web/data/t04/daily.json';
  record(file).then((doc) => {
    const { reading, target_date, hourly } = doc.rows.filter((row) => row.reading.signal_id === SIGNAL_ID).at(-1);
    console.log(`rows=${doc.rows.length} last=${reading.record_date} target=${target_date} mean=${reading.normalized_value}${reading.unit} hours=${hourly.time.length}`);
  })
    .catch(e => { console.error(`FAILED: ${e.message}`); process.exit(1); });
}
