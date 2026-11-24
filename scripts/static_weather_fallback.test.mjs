import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import Engine from '../static_src/static-engine.js';
import Daily from '../static_src/weather-daily.js';
import vm from 'node:vm';

const day = '2026-11-24';
const hourly = d => ({
  time: Array.from({length:24}, (_,h) => `${d}T${String(h).padStart(2,'0')}:00`),
  temperature_2m: Array.from({length:24}, (_,h) => h - 5),
  precipitation: Array.from({length:24}, (_,h) => h / 10),
  snowfall: Array.from({length:24}, (_,h) => h / 100)
});
const raw = d => ({timezone:'Asia/Seoul', hourly_units:{temperature_2m:'°C',precipitation:'mm',snowfall:'cm'},hourly:hourly(d)});
const observation = (d, fetched) => Daily.normalize(raw(d), fetched, {dataDate:d});
const older = observation('2026-11-21','2026-11-22T01:00:00Z');
const newer = observation('2026-11-22','2026-11-23T01:00:00Z');
const offline = async () => { throw new Error('offline'); };
const defaults = {weather:offline, fallbackRows:async()=>({rows:[]}),getLastSuccessfulForecast:()=>undefined};
const create = o => Engine.createEngine({...defaults,...o});
const stations = [{name:'A',idx:0,lat:36,lng:127},{name:'B',idx:1,lat:36.1,lng:127}];
const schedules = ['평일','휴일'].map(day_type=>({day_type,direction:'상행',stops:[{station:'A',time:'23:00'},{station:'B',time:'24:00'}]}));
const resources = {model:{format:'hgb-squared-v1',base:1,trees:[],input_order:[],ordinal_categories:[]},
  runtime:{stations,station_names:['A','B'],schedules:{20260330:schedules,20250930:schedules},holidays:[],change:'2026-03-30',pois:[],meta:{},walk_min_per_km:10}};
const request = {date:day,origin:stations[0],start_hour:23,end_hour:24};

test('latest observation supplies hourly pattern without changing original records', async()=>{
  const rows = {rows:[newer,older]}, before = JSON.stringify(rows);
  const engine = create({fallbackRows:async()=>rows});
  const w = await engine.fetchWeatherForDate(day);
  assert.equal(w.fallback.source_date,'2026-11-22');
  assert.equal(w.fallback.kind,'observed');
  assert.equal(w.fallback.fetched_at,newer.reading.fetched_at);
  assert.equal(w.fallback.source_url,newer.reading.source_url);
  assert.deepEqual(w.hourly.temperature_2m,newer.raw.hourly.temperature_2m);
  assert.equal(w.hourly.time[23],`${day}T23:00`);
  assert.equal(JSON.stringify(rows),before);
});

test('expired same-day forecast takes precedence, fallback is not cached, recovery is normal', async()=>{
  let fail = false, reads = 0;
  const engine = create({cacheTtlMs:0,weather:async d=>{
    reads++; if(fail) throw new Error('offline');
    return {available:true,date:d,source:'forecast',fetched_at:'2026-11-24T01:00:00Z',source_url:'https://api.open-meteo.com/v1/forecast',hourly:hourly(d)};
  }});
  assert.equal((await engine.fetchWeatherForDate(day)).fallback,undefined);
  fail = true;
  assert.equal((await engine.fetchWeatherForDate(day)).fallback.source_date,day);
  assert.equal((await engine.fetchWeatherForDate('2026-11-25')).fallback.source_date,day);
  fail = false;
  assert.equal((await engine.fetchWeatherForDate(day)).fallback,undefined);
  assert.equal(reads,4);
});

test('no data and malformed dates remain errors; incomplete values use observations',async()=>{
  assert.equal((await create().fetchWeatherForDate(day)).available,false);
  let reads = 0;
  const engine = create({weather:async d=>{reads++; return hourly(d);}});
  assert.equal((await engine.fetchWeatherForDate('2026-02-30')).available,false);
  assert.equal(reads,0);
  for(const value of [null,NaN]) {
    const partial = hourly(day); partial.temperature_2m[12] = value;
    const w = await create({weather:async()=>partial,fallbackRows:async()=>({rows:[newer]})}).fetchWeatherForDate(day);
    assert.equal(w.fallback.source_date,'2026-11-22');
  }
});

test('subscriber abort does not cancel another subscriber or expose fallback to cancelled caller',async()=>{
  let finish, reads=0;
  const engine = create({weather:async d=>{reads++;await new Promise(r=>finish=r);return hourly(d);}});
  const controller = new AbortController();
  const first = engine.fetchWeatherForDate(day,{signal:controller.signal});
  const second = engine.fetchWeatherForDate(day);
  controller.abort(); finish();
  await assert.rejects(first,{name:'AbortError'});
  assert.equal((await second).available,true); assert.equal(reads,1);
});

test('recommendation metadata separates requested dates including next midnight, then clears on recovery',async()=>{
  let fail = true;
  const engine = create({resources,cacheTtlMs:0,fallbackRows:async()=>({rows:[newer]}),weather:async d=>fail?offline():hourly(d)});
  const first = await engine.recommend(request);
  assert.deepEqual(first.meta.weather_fallbacks.map(f=>f.requested_date),[day,'2026-11-25']);
  assert.ok(first.meta.weather_fallbacks.every(f=>f.source_date==='2026-11-22'));
  assert.deepEqual(first.meta.weather_source,['fallback']);
  const midnight = await engine.fetchWeatherForDate('2026-11-25');
  assert.equal(midnight.hourly.time[0],'2026-11-25T00:00');
  assert.equal(midnight.hourly.temperature_2m[0],newer.raw.hourly.temperature_2m[0]);
  fail=false;
  assert.equal((await engine.recommend(request)).meta.weather_fallbacks,undefined);
  await assert.rejects(engine.recommend({...request,date:'oops'}));
});

test('requestToday shares only a successful real forecast; synthetic records and failures cannot replace it',async()=>{
  const fixture = JSON.parse(await readFile(new URL('../static-web/data/t04/fixtures/normal-d1-a.json',import.meta.url),'utf8'));
  const synthetic = Daily.fromFixture(fixture);
  assert.equal((await create({getLastSuccessfulForecast:()=>synthetic,fallbackRows:async()=>({rows:[synthetic]})}).fetchWeatherForDate(day)).available,false);
  const record = await Daily.requestToday({now:()=>new Date('2026-11-24T01:00:00Z'),fetchImpl:async()=>new Response(JSON.stringify(raw(day)))});
  const engine = create({getLastSuccessfulForecast:Daily.getLastSuccessfulForecast});
  assert.equal((await engine.fetchWeatherForDate('2026-12-01')).fallback.source_date,day);
  Daily.fromFixture(fixture);
  await assert.rejects(Daily.requestToday({fetchImpl:offline}));
  assert.deepEqual(Daily.getLastSuccessfulForecast(),record);
  const returned = Daily.getLastSuccessfulForecast(); returned.raw.hourly.temperature_2m[0]=999;
  assert.deepEqual(Daily.getLastSuccessfulForecast(),record);
});

test('initial fallback reads stored observations before weather card opens; remote timeout is eligible',async()=>{
  const paths=[];
  const engine = Engine.createEngine({getLastSuccessfulForecast:()=>undefined,minRequestIntervalMs:0,timeoutMs:5,fetch:async(url,{signal})=>{
    paths.push(url);
    if(url.endsWith('weather-daily.json')) return {ok:true,json:async()=>({rows:[older,newer]})};
    if(url.startsWith('http://localhost/')) return {ok:false,status:404};
    return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(Object.assign(new Error('timeout'),{name:'AbortError'}))));
  }});
  const w = await engine.fetchWeatherForDate(day);
  assert.equal(w.fallback.error_kind,'timeout');
  assert.equal(w.fallback.source_date,'2026-11-22');
  assert.ok(paths.some(p=>p.endsWith('data/t04/weather-daily.json')));
});

test('a latest observation from 30 days ago remains eligible with its actual source date',async()=>{
  const old = observation('2026-10-25','2026-10-26T01:00:00Z');
  const result = await create({fallbackRows:async()=>({rows:[old]})}).fetchWeatherForDate(day);
  assert.equal(result.fallback.source_date,'2026-10-25');
  assert.equal(result.fallback.requested_date,day);
  assert.equal(result.fallback.fetched_at,old.reading.fetched_at);
  assert.deepEqual(result.hourly.precipitation,old.raw.hourly.precipitation);
});

test('visible notices disclose provenance in results and analysis, and clear for normal results',async()=>{
  const app = await readFile(new URL('../static_src/app.js',import.meta.url),'utf8');
  const start = app.indexOf('function renderWeatherFallbackNotice(');
  const end = app.indexOf('\nfunction renderRecommendations(',start);
  const notices=[];
  const cards={prepend:el=>notices.push(el)}, analysis={before:el=>notices.push(el)};
  const document={
    getElementById:id=>id==='resultsCards'?cards:analysis,
    querySelectorAll:()=>[...notices],
    createElement:()=>({children:[],append(el){this.children.push(el);},setAttribute(){},remove(){notices.splice(notices.indexOf(this),1);}})
  };
  const context=vm.createContext({document});
  vm.runInContext(app.slice(start,end),context);
  context.renderWeatherFallbackNotice({weather_fallbacks:[{requested_date:day,source_date:'2026-10-25',kind:'observed',reason:'<offline>',source_url:'https://archive-api.open-meteo.com/v1/archive',fetched_at:'2026-10-26T01:00:00Z'}]});
  assert.equal(notices.length,2);
  assert.ok(notices.every(n=>n.className==='recommend-weather-fallback' && n.textContent.includes('2026-10-25') && !n.textContent.includes('<offline>') && n.innerHTML===undefined));
  assert.ok(notices.every(n=>n.children[0].children[1].textContent.includes('<offline>')));
  context.renderWeatherFallbackNotice({});
  assert.equal(notices.length,0);
  assert.ok(app.includes('renderWeatherFallbackNotice();'));
});
