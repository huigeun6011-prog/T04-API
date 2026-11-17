/* 혼잡도 분석 탭: 장소×시간 히트맵, 선택 경로의 시간별 예상 재차인원, 실제 평균 승하차.
   app.js 의 전역(state, escapeHtml, requestRecommendations 등)을 사용한다. 외부 라이브러리 없음. */
(function () {
  const HOURS = Array.from({ length: 20 }, (_, i) => i + 5);
  const profileCache = new Map();
  let stationProfile = null;      // web/data/station_profile.json (실제 평균 승하차)
  let stationProfilePromise = null;
  let profileItem = null;         // 마지막으로 선택된 추천 카드
  let profileDirty = false;
  let profileRequestId = 0;

  const $ = id => document.getElementById(id);
  const vizActive = () => $('tab-visualize')?.classList.contains('active');

  // ───────── 히트맵 ─────────
  const LIGHT = [238, 243, 232], DARK = [38, 62, 36];
  function lum([r, g, b]) {
    const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  }
  function cellColor(t) {
    const rgb = LIGHT.map((c, i) => Math.round(c + (DARK[i] - c) * t));
    const white = 1.05 / (lum(rgb) + 0.05), black = (lum(rgb) + 0.05) / 0.05;
    return { bg: `rgb(${rgb.join(',')})`, fg: white >= black ? '#fff' : '#000' };
  }

  function renderHeatmap() {
    const box = $('heatmapBox');
    if (!box) return;
    const m = state.matrix;
    if (!m || !m.rows?.length) {
      box.innerHTML = '<p class="viz-empty" role="status">추천을 실행하면 장소별·시간별 예상 재차인원이 여기에 표시됩니다. (장소별 최적 시간 모드에서 검색할 때 만들어집니다.)</p>';
      return;
    }
    const loads = m.rows.flatMap(r => r.cells.map(c => c.mean_load)).filter(v => typeof v === 'number');
    if (!loads.length) {
      box.innerHTML = '<p class="viz-empty">선택한 시간 범위에 이용할 수 있는 열차가 없습니다.</p>';
      return;
    }
    const lo = Math.min(...loads), hi = Math.max(...loads), span = hi - lo || 1;
    const head = m.hours.map(h => `<th scope="col" class="${state.activeHour === h ? 'is-active' : ''}">${h}시</th>`).join('');
    const body = m.rows.map(row => {
      const own = row.cells.map(c => c.mean_load).filter(v => typeof v === 'number');
      const best = own.length ? Math.min(...own) : null;
      const cells = row.cells.map(c => {
        if (typeof c.mean_load !== 'number') {
          return `<td><span class="heat-cell heat-empty" role="img" aria-label="${escapeHtml(row.name)} ${c.hour}시 열차 없음" title="열차 없음">–</span></td>`;
        }
        const col = cellColor((c.mean_load - lo) / span);
        const isBest = c.mean_load === best;
        const label = `${row.name} ${c.hour}시 ${formatTrainTime(c.departure_time)} 출발 예상 ${Math.round(c.mean_load)}명${isBest ? ' (이 장소에서 가장 한산한 시간)' : ''}`;
        return `<td><button type="button" class="heat-cell${isBest ? ' heat-best' : ''}" style="background:${col.bg};color:${col.fg}" data-hour="${c.hour}" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}">${Math.round(c.mean_load)}</button></td>`;
      }).join('');
      const name = row.no_train ? `${row.name} (도보)` : row.name;
      return `<tr><th scope="row" class="heat-name" title="${escapeHtml(row.name)}">${escapeHtml(name)}</th>${cells}</tr>`;
    }).join('');
    const stops = [0, .25, .5, .75, 1].map(t => cellColor(t).bg).join(',');
    box.innerHTML = `
      <div class="heat-scroll" tabindex="0" role="region" aria-label="장소별 시간대 예상 재차인원 표 (가로로 스크롤)">
        <table class="heat"><caption class="sr-only">장소와 시간대별 예상 재차인원(명). 칸을 누르면 그 시간대 기준으로 추천 순위를 다시 계산합니다.</caption>
          <thead><tr><th scope="col" class="heat-corner">장소</th>${head}</tr></thead><tbody>${body}</tbody></table>
      </div>
      <div class="heat-legend"><span>한산 ${Math.round(lo)}명</span><i style="background:linear-gradient(90deg,${stops})" aria-hidden="true"></i><span>붐빔 ${Math.round(hi)}명</span></div>
      <p class="viz-note">칸 안의 숫자는 승차 후 이용 구간의 예상 평균 재차인원(명)입니다. 굵은 테두리는 그 장소에서 가장 한산한 시간, “–”는 해당 시간에 맞는 열차가 없음을 뜻합니다. 칸을 누르면 그 시간 기준으로 순위를 다시 계산합니다.</p>`;
    box.querySelectorAll('button.heat-cell').forEach(btn => btn.addEventListener('click', () => {
      const hour = Number(btn.dataset.hour);
      document.querySelector('.tab-nav-btn[data-tab="recommend"]')?.click();
      requestRecommendations({ hour });
    }));
  }

  // ───────── 선택 경로 프로필 ─────────
  function loadStationProfile() {
    if (!stationProfilePromise) {
      stationProfilePromise = fetch('./data/station_profile.json').then(r => (r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)))).then(d => { stationProfile = d; return d; }).catch(() => { stationProfile = null; return null; });
    }
    return stationProfilePromise;
  }

  const niceMax = v => { const steps = [40, 80, 120, 160, 200, 240, 280, 320, 400, 480, 600, 800, 1000, 1200, 1600, 2000, 2400, 3200, 4000, 6000]; return steps.find(s => s >= v) || Math.ceil(v / 1000) * 1000; };

  function renderProfileChart(data, item, real, kind) {
    const W = 760, H = 320, L = 52, R = 62, T = 22, B = 44;
    const pw = W - L - R, ph = H - T - B;
    const step = pw / HOURS.length, bw = step * 0.56;
    const maxLoad = niceMax(Math.max(10, ...data.hours.map(h => h.max || 0)));
    const realVals = real ? HOURS.map((_, i) => (real.boardings[i] ?? 0) + (real.alightings[i] ?? 0)) : null;
    const maxReal = realVals ? niceMax(Math.max(10, ...realVals)) : 1;
    const y = v => T + ph - (v / maxLoad) * ph;
    const yr = v => T + ph - (v / maxReal) * ph;
    const x = i => L + step * i + step / 2;
    const withTrains = data.hours.filter(h => h.median !== null);
    const bestHour = withTrains.length ? withTrains.reduce((a, b) => (b.median < a.median ? b : a)).hour : null;
    const selHour = item?.hour ?? null;

    let svg = `<svg viewBox="0 0 ${W} ${H}" class="prof-svg" role="img" aria-labelledby="profTitle profDesc"><title id="profTitle">시간별 예상 재차인원과 실제 평균 승하차</title><desc id="profDesc">${escapeHtml(data.boarding)}역에서 ${escapeHtml(data.alighting)}역까지 05시부터 24시까지 시간대별 예상 재차인원 중앙값 막대와 최소·최대 범위, 같은 역의 실제 평균 승차와 하차 합계 선. 아래 숫자 표에서 같은 값을 볼 수 있습니다.</desc>`;
    for (let k = 0; k <= 4; k++) {
      const v = (maxLoad / 4) * k, yy = y(v);
      svg += `<line x1="${L}" x2="${W - R}" y1="${yy}" y2="${yy}" class="prof-grid"/><text x="${L - 6}" y="${yy + 4}" text-anchor="end" class="prof-tick">${Math.round(v)}</text>`;
      if (realVals) svg += `<text x="${W - R + 6}" y="${yr((maxReal / 4) * k) + 4}" class="prof-tick prof-tick-r">${Math.round((maxReal / 4) * k)}</text>`;
    }
    svg += `<text x="${L - 40}" y="${T + ph / 2}" transform="rotate(-90 ${L - 40} ${T + ph / 2})" text-anchor="middle" class="prof-axis">예상 재차인원 (명)</text>`;
    if (realVals) svg += `<text x="${W - 12}" y="${T + ph / 2}" transform="rotate(90 ${W - 12} ${T + ph / 2})" text-anchor="middle" class="prof-axis prof-axis-r">실제 평균 승하차 (최근 2년, ${kind}) 명/시간</text>`;
    data.hours.forEach((h, i) => {
      const cx = x(i);
      svg += `<text x="${cx}" y="${H - B + 16}" text-anchor="middle" class="prof-tick${h.hour === selHour ? ' prof-sel-t' : ''}">${h.hour}</text>`;
      if (h.median === null) return;
      const isSel = h.hour === selHour;
      svg += `<rect x="${cx - bw / 2}" y="${y(h.median)}" width="${bw}" height="${Math.max(1, T + ph - y(h.median))}" class="prof-bar${isSel ? ' prof-bar-sel' : ''}${h.hour === bestHour ? ' prof-bar-best' : ''}"><title>${h.hour}시 · 열차 ${h.count}대 · 중앙값 ${Math.round(h.median)}명 (${Math.round(h.min)}~${Math.round(h.max)})</title></rect>`;
      svg += `<line x1="${cx}" x2="${cx}" y1="${y(h.min)}" y2="${y(h.max)}" class="prof-whisk"/><line x1="${cx - 4}" x2="${cx + 4}" y1="${y(h.max)}" y2="${y(h.max)}" class="prof-whisk"/><line x1="${cx - 4}" x2="${cx + 4}" y1="${y(h.min)}" y2="${y(h.min)}" class="prof-whisk"/>`;
    });
    if (bestHour !== null) {
      const bi = HOURS.indexOf(bestHour);
      const bm = data.hours[bi];
      svg += `<text x="${x(bi)}" y="${Math.max(12, y(bm.max) - 8)}" text-anchor="middle" class="prof-best-t">가장 한산 ${bestHour}시</text>`;
    }
    if (realVals) {
      svg += `<polyline class="prof-real" fill="none" points="${realVals.map((v, i) => `${x(i)},${yr(v)}`).join(' ')}"/>` + realVals.map((v, i) => `<circle cx="${x(i)}" cy="${yr(v)}" r="2.6" class="prof-real-dot"><title>${HOURS[i]}시 실제 평균 승하차 ${Math.round(v)}명</title></circle>`).join('');
    }
    return svg + '</svg>';
  }

  function renderProfile(data, item) {
    const box = $('profileBox');
    const day = data.holiday ? '휴일' : '평일';
    const real = stationProfile?.stations?.[data.boarding]?.[day] || null;
    const span = stationProfile?.date_range ? `${stationProfile.date_range[0]} ~ ${stationProfile.date_range[1]}, ${stationProfile.days?.[day] ?? ''}일 평균` : '';
    const rows = data.hours.map((h, i) => `<tr><th scope="row">${h.hour}시</th><td>${h.count}</td><td>${h.median === null ? '–' : `${Math.round(h.median)} (${Math.round(h.min)}~${Math.round(h.max)})`}</td><td>${real ? Math.round((real.boardings[i] ?? 0) + (real.alightings[i] ?? 0)) : '–'}</td></tr>`).join('');
    box.innerHTML = `
      <p class="viz-sub">${escapeHtml(data.boarding)}역 승차 → ${escapeHtml(data.alighting)}역 하차 · ${escapeHtml(data.service_date)} (${day})${item?.poi?.name ? ` · ${escapeHtml(item.poi.name)}` : ''}</p>
      ${renderProfileChart(data, item, real, day)}
      <ul class="prof-legend">
        <li><i class="lg-bar"></i>막대: 시간대별 예상 재차인원(열차별 구간 평균의 중앙값)</li>
        <li><i class="lg-whisk"></i>가는 선: 같은 시간대 열차의 최소~최대</li>
        <li><i class="lg-real"></i>선: 실제 평균 ${escapeHtml(data.boarding)}역 승차+하차 인원 (최근 2년 ${day} 평균${span ? `, ${escapeHtml(span)}` : ''}) — 오른쪽 축</li>
        <li><i class="lg-sel"></i>진한 막대: 선택한 추천의 시간</li>
      </ul>
      <p class="viz-caveat">예상 재차인원은 평균적인 열차에 대한 추정값입니다. 실제 혼잡 열차 19대와 비교했을 때 추정값은 실제값의 약 절반 수준이었으므로, 절대 숫자보다 시간대 사이의 상대적 차이로 읽어 주세요.</p>
      <details class="viz-details"><summary>숫자로 보기</summary><div class="analysis-scroll"><table class="num-table"><thead><tr><th scope="col">시간</th><th scope="col">열차 수</th><th scope="col">예상 재차 중앙값 (최소~최대)</th><th scope="col">실제 평균 승+하차</th></tr></thead><tbody>${rows}</tbody></table></div></details>`;
  }

  async function refreshProfile() {
    const box = $('profileBox');
    if (!box) return;
    const item = profileItem;
    if (!item) {
      box.innerHTML = '<p class="viz-empty" role="status">추천 카드를 선택하면 그 경로의 시간별 예상 재차인원이 표시됩니다.</p>';
      return;
    }
    if (item.no_train || !item.boarding_station?.name || !item.alighting_station?.name || item.boarding_station.name === item.alighting_station.name) {
      box.innerHTML = '<p class="viz-empty" role="status">선택한 장소는 열차를 타지 않는 도보 후보라 시간별 재차인원이 없습니다.</p>';
      return;
    }
    if (!vizActive()) { profileDirty = true; return; }
    profileDirty = false;
    const id = ++profileRequestId;
    const url = `/api/profile?${new URLSearchParams({ date: state.date, boarding: item.boarding_station.name, alighting: item.alighting_station.name })}`;
    const base = (window.RECOMMENDATION_API_BASE || '').replace(/\/$/, '');
    box.innerHTML = '<p class="viz-empty" role="status">시간별 예상 재차인원을 계산하고 있습니다. 처음에는 몇 초 걸릴 수 있습니다.</p>';
    try {
      let data = profileCache.get(url);
      if (!data) {
        const [response] = await Promise.all([fetch(base + url), loadStationProfile()]);
        data = await response.json();
        if (!response.ok) throw new Error(typeof data.error === 'string' ? data.error : '프로필을 불러오지 못했습니다.');
        profileCache.set(url, data);
      } else {
        await loadStationProfile();
      }
      if (id !== profileRequestId) return;
      renderProfile(data, item);
    } catch (error) {
      if (id !== profileRequestId) return;
      box.innerHTML = `<p class="viz-empty is-error" role="alert">${escapeHtml(error.message === 'Failed to fetch' ? '예측 서비스에 연결할 수 없습니다.' : error.message)}</p>`;
    }
  }

  window.Analysis = {
    setMatrix(matrix) { state.matrix = matrix || state.matrix || null; renderHeatmap(); },
    refreshHeatmap: renderHeatmap,
    setSelected(item) { profileItem = item; profileDirty = true; if (vizActive()) refreshProfile(); },
    reset() { state.matrix = null; profileItem = null; renderHeatmap(); refreshProfile(); },
  };

  document.addEventListener('DOMContentLoaded', () => {
    renderHeatmap();
    refreshProfile();
    document.querySelector('.tab-nav-btn[data-tab="visualize"]')?.addEventListener('click', () => { if (profileDirty) refreshProfile(); });
  });
})();
