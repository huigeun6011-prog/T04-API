// T04 일별 기록: Open-Meteo 대전 현재 기온 1건을 조회해 KST 날짜 키로 저장한다.
// 같은 날짜는 갱신, 다음 날짜는 새 행. 조회가 실패하면 파일을 건드리지 않는다(마지막 정상값 보존).
import { readFile, writeFile, rename, mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const { kstDate, validateNormalizedReading } = createRequire(import.meta.url)('../static_src/t04-core.js');
export { kstDate };

export const SIGNAL_ID = 'daejeon-temperature-2m';
export const SOURCE_URL = 'https://api.open-meteo.com/v1/forecast?latitude=36.35&longitude=127.38&current=temperature_2m&timezone=Asia%2FSeoul';

// 응답 원본(raw)에서 값 하나를 뽑아 아홉 필드로 정규화한다. 형식이 다르면 던진다(schema_error).
export function normalize(raw, fetchedAt) {
  const value = raw?.current?.temperature_2m;
  const unit = raw?.current_units?.temperature_2m;
  const time = raw?.current?.time;
  if (!Number.isFinite(value) || typeof unit !== 'string' ||
      typeof time !== 'string' || !/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(time)) {
    throw new Error('schema_error');
  }
  const sourceTime = new Date(`${time}:00+09:00`); // timezone=Asia/Seoul
  if (!Number.isFinite(sourceTime.getTime())) throw new Error('schema_error');
  return {
    signal_id: SIGNAL_ID, normalized_value: value, unit, source_name: 'Open-Meteo 대전 현재 기온', source_url: SOURCE_URL,
    source_time: sourceTime.toISOString(),
    fetched_at: fetchedAt, record_timezone: 'Asia/Seoul', record_date: kstDate(fetchedAt),
  };
}

export function upsert(rows, row) {
  try {
    const { reading } = row;
    validateNormalizedReading(reading);
    const next = rows.filter((existing) => existing?.reading?.signal_id !== reading.signal_id ||
      existing.reading.record_date !== reading.record_date);
    for (const existing of next) validateNormalizedReading(existing?.reading);
    next.push(row);
    return next.sort((a, b) => a.reading.record_date.localeCompare(b.reading.record_date));
  } catch (cause) {
    throw new Error('schema_error', { cause });
  }
}

export async function record(file, fetchImpl = fetch, now = () => new Date().toISOString()) {
  const res = await fetchImpl(SOURCE_URL, { signal: AbortSignal.timeout(10000) });
  if (!res.ok) throw new Error(`http_${res.status}`);
  const raw = await res.json();
  const reading = normalize(raw, now());
  let doc = { rows: [] };
  try { doc = JSON.parse(await readFile(file, 'utf8')); } catch (e) { if (e.code !== 'ENOENT') throw e; }
  doc.rows = upsert(doc.rows, { reading, raw });
  await mkdir(dirname(file), { recursive: true });
  await writeFile(`${file}.tmp`, JSON.stringify(doc, null, 2) + '\n');
  await rename(`${file}.tmp`, file); // 원자적 교체
  return doc;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  const file = process.argv[2] ?? 'static-web/data/t04/daily.json';
  record(file).then(d => console.log(`rows=${d.rows.length} last=${d.rows.at(-1).reading.record_date} value=${d.rows.at(-1).reading.normalized_value}${d.rows.at(-1).reading.unit}`))
    .catch(e => { console.error(`FAILED: ${e.message}`); process.exit(1); });
}
