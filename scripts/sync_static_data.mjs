// 원본(data/raw/...)에서 static-web 쪽 공개 사본을 만든다. 사본은 생성물이라 커밋하지 않는다(.gitignore).
//   1) data/raw/weather/*.json -> static-web/data/weather/ (scripts/build_static_web.py 와 같은 형식)
//   2) static-web/data/t04/daily.json 행의 raw_xml 이 가리키는 XML 만 data/raw/subway/ -> static-web/data/t04/raw/
//      (이력용 전체 XML 은 공개하지 않는다. 참조되지 않는 기존 사본은 지운다.)
// 멱등: 내용이 같으면 다시 쓰지 않는다. 오류가 하나라도 있으면 종료 코드 1.
// 사용: node scripts/sync_static_data.mjs
import { readFile, writeFile, rename, mkdir, readdir, unlink } from 'node:fs/promises';
import { dirname, resolve, join, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { weatherStaticText } from './t04_daily_record.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

const readOrNull = async (file) => {
  try { return await readFile(file); } catch (e) { if (e.code === 'ENOENT') return null; throw e; }
};

async function writeIfChanged(file, data) {
  const buf = Buffer.isBuffer(data) ? data : Buffer.from(data, 'utf8');
  const prior = await readOrNull(file);
  if (prior && prior.equals(buf)) return false;
  await mkdir(dirname(file), { recursive: true });
  await writeFile(`${file}.tmp`, buf);
  await rename(`${file}.tmp`, file);
  return true;
}

export async function syncStaticData({
  root = ROOT,
  weatherSrc = join(root, 'data/raw/weather'),
  weatherDst = join(root, 'static-web/data/weather'),
  dailyFile = join(root, 'static-web/data/t04/daily.json'),
  xmlSrc = join(root, 'data/raw/subway'),
  xmlDst = join(root, 'static-web/data/t04/raw')
} = {}) {
  const result = { weather: { written: 0, same: 0 }, xml: { written: 0, same: 0, removed: 0 }, errors: [] };

  let names = [];
  try { names = (await readdir(weatherSrc)).filter((n) => /^\d{4}-\d{2}-\d{2}\.json$/.test(n)).sort(); } catch (e) {
    if (e.code !== 'ENOENT') throw e;
    result.errors.push(`weather source missing: ${weatherSrc}`);
  }
  for (const name of names) {
    try {
      const hourly = JSON.parse(await readFile(join(weatherSrc, name), 'utf8')).hourly;
      const changed = await writeIfChanged(join(weatherDst, name), weatherStaticText(hourly));
      result.weather[changed ? 'written' : 'same'] += 1;
    } catch (e) {
      result.errors.push(`weather ${name}: ${e.message}`);
    }
  }

  let rows = [];
  const dailyBuf = await readOrNull(dailyFile);
  if (dailyBuf) {
    try { rows = JSON.parse(dailyBuf.toString('utf8')).rows ?? []; } catch (e) { result.errors.push(`daily.json: ${e.message}`); }
  }
  const wanted = new Set();
  for (const row of rows) {
    for (const ref of row?.raw_xml ?? []) {
      const name = basename(String(ref));
      if (!/^\d{4}-\d{2}-\d{2}\.xml$/.test(name)) { result.errors.push(`invalid raw_xml reference: ${ref}`); continue; }
      wanted.add(name);
    }
  }
  for (const name of [...wanted].sort()) {
    const data = await readOrNull(join(xmlSrc, name));
    if (!data) { result.errors.push(`raw xml missing in source: ${name}`); continue; }
    const changed = await writeIfChanged(join(xmlDst, name), data);
    result.xml[changed ? 'written' : 'same'] += 1;
  }
  try {
    for (const name of await readdir(xmlDst)) {
      if (name.endsWith('.xml') && !wanted.has(name)) { await unlink(join(xmlDst, name)); result.xml.removed += 1; }
    }
  } catch (e) { if (e.code !== 'ENOENT') throw e; }
  return result;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  syncStaticData().then((r) => {
    console.log(`SYNC weather written=${r.weather.written} same=${r.weather.same}; xml written=${r.xml.written} same=${r.xml.same} removed=${r.xml.removed}`);
    for (const err of r.errors) console.error(`ERROR ${err}`);
    process.exit(r.errors.length ? 1 : 0);
  }).catch((e) => { console.error(`FAILED ${e.message}`); process.exit(1); });
}
