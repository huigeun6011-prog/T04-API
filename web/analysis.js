/* 혼잡도 분석 탭: 장소별 시간대 순위 히트맵과 선택 경로의 시간대 순위 막대(사람 수 없음, D-028).
   app.js 의 전역(state, escapeHtml, requestRecommendations 등)을 사용한다. 외부 라이브러리 없음. */
(function () {
  let profileItem = null;         // 마지막으로 선택된 추천 카드

  const $ = id => document.getElementById(id);

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

  // 구간 묶음마다 자기 시간대끼리만 매긴 서버 순위(hour_ranks)를 그대로 그린다. 줄 사이·시간 사이 비교는 하지 않는다(D-028).
  function renderHeatmap() {
    const box = $('heatmapBox');
    if (!box) return;
    const groups = visibleGroups().filter(g => g.kind === 'route' && g.hour_ranks?.length);
    const tbl = $('predictionAnalysis');
    if (tbl && visibleGroups().length) {
      tbl.innerHTML = `<div class="analysis-scroll"><table><thead><tr><th>구간</th><th>이동 구간</th><th>장소</th></tr></thead><tbody>${visibleGroups().map(g => `<tr><td>${escapeHtml(groupTitle(g).split(' · ')[0])}</td><td>${g.kind === 'walk' ? '–' : `${g.stops}구간`}</td><td>${escapeHtml(g.categories.flatMap(c => c.places.map(p => p.poi?.name)).join(', '))}</td></tr>`).join('')}</tbody></table></div>`;
    }
    if (!groups.length) {
      box.innerHTML = '<p class="viz-empty" role="status">추천을 실행하면 구간별 시간대 순서가 여기에 표시됩니다.</p>';
      return;
    }
    const hours = windowHours();
    const head = hours.map(h => `<th scope="col">${h}시</th>`).join('');
    const body = groups.map(g => {
      const byHour = new Map(g.hour_ranks.map(c => [c.hour, c])), span = Math.max(1, g.rank_n - 1), name = groupTitle(g).split(' · ')[0];
      const cells = hours.map(h => {
        const c = byHour.get(h);
        if (!c) return `<td><span class="heat-cell heat-empty" role="img" aria-label="${escapeHtml(name)} ${h}시 열차 없음" title="열차 없음">–</span></td>`;
        const col = cellColor((c.rank - 1) / span);
        const label = `${name} ${h}시: ${c.rank}번째로 한산`;
        return `<td><span class="heat-cell${c.rank === 1 ? ' heat-best' : ''}" role="img" style="background:${col.bg};color:${col.fg}" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}">${c.rank}위</span></td>`;
      }).join('');
      return `<tr><th scope="row" class="heat-name" title="${escapeHtml(name)}">${escapeHtml(name)}</th>${cells}</tr>`;
    }).join('');
    const stops = [0, .25, .5, .75, 1].map(t => cellColor(t).bg).join(',');
    box.innerHTML = `
      <p class="viz-note"><strong>장소 간 비교가 아니라 각 구간의 시간대 순서</strong>입니다. 각 줄은 그 구간에서 고른 시간 범위 안의 시간대끼리만 순위를 매겼습니다.</p>
      <div class="heat-scroll" tabindex="0" role="region" aria-label="구간별 시간대 순위 표 (가로로 스크롤)">
        <table class="heat"><caption class="sr-only">구간별 시간대 순위. 1위가 가장 한산한 시간대이며 줄마다 따로 매긴 순위입니다.</caption>
          <thead><tr><th scope="col" class="heat-corner">구간</th>${head}</tr></thead><tbody>${body}</tbody></table>
      </div>
      <div class="heat-legend"><span>앞 순위(한산)</span><i style="background:linear-gradient(90deg,${stops})" aria-hidden="true"></i><span>뒤 순위</span></div>
      <p class="viz-note">칸의 “k위”는 그 줄 안의 순서이고 사람 수가 아닙니다. 순위는 묶지 않고 그대로 보여 주며, 순위 차이가 2 이하인 시간대는 실제 차이로 보지 않습니다. 굵은 테두리는 1위 시간대, “–”는 맞는 열차가 없음을 뜻합니다.</p>`;
  }

  // ───────── 선택 경로의 시간대 순위 (사람 수 없음) ─────────
  function renderProfileChart(item) {
    const W = 760, H = 260, L = 40, R = 16, T = 22, B = 36;
    const pw = W - L - R, ph = H - T - B;
    const hours = windowHours();
    const byHour = new Map(item.hour_ranks.map(c => [c.hour, c]));
    const best = 1, step = pw / hours.length, bw = Math.min(step * 0.56, 40), span = Math.max(1, item.rank_n - 1);
    const selHour = state.groupHours?.[item.groupId] ?? null;
    let svg = `<svg viewBox="0 0 ${W} ${H}" class="prof-svg" role="img" aria-labelledby="profTitle profDesc"><title id="profTitle">시간대별 순서</title><desc id="profDesc">${escapeHtml(stationName(item.boarding_station))}역에서 ${escapeHtml(stationName(item.alighting_station))}역까지 고른 시간 범위의 시간대 순서. 막대가 낮을수록 한산하며 높이는 순서이지 사람 수가 아닙니다.</desc>`;
    svg += `<line x1="${L}" x2="${W - R}" y1="${T + ph}" y2="${T + ph}" class="prof-grid"/><text x="${L - 14}" y="${T + ph / 2}" transform="rotate(-90 ${L - 14} ${T + ph / 2})" text-anchor="middle" class="prof-axis">낮을수록 한산 (순서)</text>`;
    hours.forEach((h, i) => {
      const cx = L + step * i + step / 2, c = byHour.get(h);
      svg += `<text x="${cx}" y="${H - B + 16}" text-anchor="middle" class="prof-tick${h === selHour ? ' prof-sel-t' : ''}">${h}</text>`;
      if (!c) return;
      const bh = 8 + ((c.rank - 1) / span) * (ph - 8), yy = T + ph - bh;
      svg += `<rect x="${cx - bw / 2}" y="${yy}" width="${bw}" height="${bh}" class="prof-bar${h === selHour ? ' prof-bar-sel' : ''}${c.rank === best ? ' prof-bar-best' : ''}"><title>${h}시 · ${item.rank_n}개 시간대 중 ${c.rank}번째로 한산</title></rect><text x="${cx}" y="${yy - 4}" text-anchor="middle" class="prof-best-t">${c.rank}</text>`;
    });
    return svg + '</svg>';
  }

  function renderProfile(item) {
    const box = $('profileBox');
    const rows = item.hour_ranks.map(c => `<tr><th scope="row">${c.hour}시</th><td>${item.rank_n}개 중 ${c.rank}번째</td><td>${c.trains.map(x => escapeHtml(formatTrainTime(x.departure_time))).join(', ')}</td></tr>`).join('');
    box.innerHTML = `
      <p class="viz-sub">${escapeHtml(stationName(item.boarding_station))}역 승차 → ${escapeHtml(stationName(item.alighting_station))}역 하차 · ${escapeHtml(state.date)}${item.poi?.name ? ` · ${escapeHtml(item.poi.name)}` : ''}</p>
      ${renderProfileChart(item)}
      <ul class="prof-legend">
        <li><i class="lg-bar"></i>막대 높이: 시간대 순서(낮을수록 한산, 사람 수 아님)</li>
        <li><i class="lg-sel"></i>진한 막대: 선택한 시간</li>
      </ul>
      <p class="viz-caveat">이 화면은 같은 구간 안에서 시간대 사이의 순서만 보여 줍니다. 몇 명이 타는지는 알려 주지 않으며, 순위는 그대로 보여 주며 순위 차이가 2 이하인 시간대는 실제 차이로 보지 않습니다. 피크 시간 사례로만 검증했습니다.</p>
      <details class="viz-details"><summary>순서로 보기</summary><div class="analysis-scroll"><table class="num-table"><thead><tr><th scope="col">시간</th><th scope="col">순서</th><th scope="col">승차역 출발 열차</th></tr></thead><tbody>${rows}</tbody></table></div></details>`;
  }

  function refreshProfile() {
    const box = $('profileBox');
    if (!box) return;
    const item = profileItem;
    if (!item) {
      box.innerHTML = '<p class="viz-empty" role="status">추천 카드를 선택하면 그 경로의 시간대 순서가 표시됩니다.</p>';
    } else if (item.no_train || !item.hour_ranks?.length) {
      box.innerHTML = '<p class="viz-empty" role="status">선택한 장소는 열차를 타지 않는 도보 후보라 시간대 순서가 없습니다.</p>';
    } else {
      renderProfile(item);
    }
  }

  window.Analysis = {
    refreshHeatmap: renderHeatmap,
    refreshProfile,
    setSelected(item) { profileItem = item; refreshProfile(); },
  };

  document.addEventListener('DOMContentLoaded', () => {
    renderHeatmap();
    refreshProfile();
  });
})();
