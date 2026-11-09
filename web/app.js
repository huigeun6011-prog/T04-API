/* ==============================================
   대전 한적 나들이 — app.js
   TODO 항목은 개발 예정 기능을 표시합니다.
   ============================================== */

'use strict';

// ══════════════════════════════════════════════
// 1. 정적 데이터
// ══════════════════════════════════════════════

/** 대전 도시철도 1호선 22개 역 (판암 idx=0 ~ 반석 idx=21) */
const STATIONS = [
  { name: '판암',         idx: 0,  lat: 36.3225, lng: 127.4542 },
  { name: '신흥',         idx: 1,  lat: 36.3253, lng: 127.4461 },
  { name: '대동',         idx: 2,  lat: 36.3310, lng: 127.4356 },
  { name: '대전',         idx: 3,  lat: 36.3326, lng: 127.4318 },
  { name: '중앙로',       idx: 4,  lat: 36.3277, lng: 127.4253 },
  { name: '중구청',       idx: 5,  lat: 36.3237, lng: 127.4181 },
  { name: '서대전네거리', idx: 6,  lat: 36.3209, lng: 127.4096 },
  { name: '오룡',         idx: 7,  lat: 36.3262, lng: 127.4030 },
  { name: '용문',         idx: 8,  lat: 36.3317, lng: 127.3961 },
  { name: '탄방',         idx: 9,  lat: 36.3346, lng: 127.3877 },
  { name: '시청',         idx: 10, lat: 36.3496, lng: 127.3843 },
  { name: '정부청사',     idx: 11, lat: 36.3604, lng: 127.3773 },
  { name: '갈마',         idx: 12, lat: 36.3540, lng: 127.3691 },
  { name: '월평',         idx: 13, lat: 36.3528, lng: 127.3608 },
  { name: '갑천',         idx: 14, lat: 36.3503, lng: 127.3519 },
  { name: '유성온천',     idx: 15, lat: 36.3627, lng: 127.3458 },
  { name: '구암',         idx: 16, lat: 36.3684, lng: 127.3384 },
  { name: '현충원',       idx: 17, lat: 36.3686, lng: 127.3272 },
  { name: '월드컵경기장', idx: 18, lat: 36.3695, lng: 127.3179 },
  { name: '노은',         idx: 19, lat: 36.3800, lng: 127.3068 },
  { name: '지족',         idx: 20, lat: 36.3942, lng: 127.3030 },
  { name: '반석',         idx: 21, lat: 36.4029, lng: 127.2990 },
];

/** 대전 한적 목적지 후보군 (더미) */
const DESTINATIONS = [
  {
    id: 1, name: '한밭수목원',
    category: 'park',
    station: '정부청사', stationIdx: 11,
    walkMinutes: 10,
    desc: '도심 속 대규모 자연 수목원. 사계절 무료입장.',
    tags: ['무료입장', '반려동물 가능', '그늘'],
    mockLoad: 58,
  },
  {
    id: 2, name: '갈마도서관',
    category: 'library',
    station: '갈마', stationIdx: 12,
    walkMinutes: 6,
    desc: '자연채광이 아름다운 구립 도서관. 조용한 열람실.',
    tags: ['열람실', '와이파이', '북카페'],
    mockLoad: 83,
  },
  {
    id: 3, name: '갑천변 생태산책로',
    category: 'trail',
    station: '갑천', stationIdx: 14,
    walkMinutes: 3,
    desc: '갑천을 따라 조성된 자연형 생태 산책로. 왕복 4km.',
    tags: ['자연', '자전거 가능', '야경'],
    mockLoad: 45,
  },
  {
    id: 4, name: '이응노미술관',
    category: 'museum',
    station: '정부청사', stationIdx: 11,
    walkMinutes: 12,
    desc: '대전 출신 세계적 화가 이응노의 미술관. 사계절 전시.',
    tags: ['유료입장', '상설전시', '기획전'],
    mockLoad: 61,
  },
  {
    id: 5, name: '유성도서관',
    category: 'library',
    station: '유성온천', stationIdx: 15,
    walkMinutes: 8,
    desc: '유성 도심의 조용한 공공도서관. 넓은 열람 공간.',
    tags: ['열람실', '어린이실', '무료'],
    mockLoad: 74,
  },
  {
    id: 6, name: '계룡문고',
    category: 'bookstore',
    station: '중앙로', stationIdx: 4,
    walkMinutes: 5,
    desc: '대전 대표 로컬 서점. 1~4층 책의 세계로.',
    tags: ['로컬서점', '문화공간', '책 추천'],
    mockLoad: 92,
  },
  {
    id: 7, name: '국립대전현충원 보훈둘레길',
    category: 'trail',
    station: '현충원', stationIdx: 17,
    walkMinutes: 5,
    desc: '울창한 숲속 고요한 산책로. 사계절 야생화 풍경.',
    tags: ['무료', '솔밭', '야생화'],
    mockLoad: 38,
  },
  {
    id: 8, name: '한밭도서관',
    category: 'library',
    station: '시청', stationIdx: 10,
    walkMinutes: 14,
    desc: '대전시립 도서관. 대형 열람실과 디지털자료실 보유.',
    tags: ['디지털자료실', '전시', '무료'],
    mockLoad: 110,
  },
  {
    id: 9, name: '월평공원',
    category: 'park',
    station: '월평', stationIdx: 13,
    walkMinutes: 7,
    desc: '도심 가까운 자연 녹지. 가족 산책 최적 코스.',
    tags: ['놀이터', '운동시설', '그늘'],
    mockLoad: 55,
  },
  {
    id: 10, name: '대전시립미술관',
    category: 'museum',
    station: '정부청사', stationIdx: 11,
    walkMinutes: 15,
    desc: '대전 대표 미술관. 현대미술 기획전 상시 운영.',
    tags: ['무료/유료 혼합', '상설전', '뮤지엄샵'],
    mockLoad: 68,
  },
];


// ══════════════════════════════════════════════
// 2. 앱 상태
// ══════════════════════════════════════════════
const state = {
  departure: null,          // { lat, lng } | null
  date: null,               // 'YYYY-MM-DD'
  selectedCategory: 'all',
  quietWeight: 50,          // 0=거리 100% ↔ 100=한적함 100%
  map: null,
  departureMarker: null,
  currentTab: 'recommend',
  loadChart: null,
  vizDirection: 'up',
  vizDaytype: 'weekday',
  vizStationIdx: 10,
};


// ══════════════════════════════════════════════
// 3. 유틸리티
// ══════════════════════════════════════════════

/** Haversine 거리 (km) */
function distKm(lat1, lng1, lat2, lng2) {
  const R = 6371, r = Math.PI / 180;
  const dLat = (lat2 - lat1) * r;
  const dLng = (lng2 - lng1) * r;
  const a = Math.sin(dLat / 2) ** 2
          + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/** km → 도보 분 (약 70m/min) */
function kmToWalk(km) { return Math.round(km / 0.07); }

/** 재차인원 → 혼잡도 정보 */
function congestionInfo(load) {
  if (load <  80) return { label: '여유',     cls: 'cong-quiet',   pct: load / 450 * 100 };
  if (load < 180) return { label: '보통',     cls: 'cong-normal',  pct: load / 450 * 100 };
  if (load < 300) return { label: '약간 혼잡', cls: 'cong-busy',    pct: load / 450 * 100 };
  return               { label: '혼잡',       cls: 'cong-crowded', pct: load / 450 * 100 };
}

function catEmoji(cat)  { return { library:'📚', park:'🌳', bookstore:'📖', museum:'🖼', trail:'👟' }[cat] ?? '📌'; }
function catLabel(cat)  { return { library:'도서관', park:'공원', bookstore:'서점', museum:'전시관', trail:'산책로' }[cat] ?? cat; }


// ══════════════════════════════════════════════
// 4. 탭 전환
// ══════════════════════════════════════════════
function initTabs() {
  document.querySelectorAll('.tab-nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;
      document.querySelectorAll('.tab-nav-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(`tab-${tab}`).classList.add('active');
      state.currentTab = tab;
      if (tab === 'visualize') initViz();
    });
  });
}


// ══════════════════════════════════════════════
// 5. 카카오 지도 연동
// ══════════════════════════════════════════════
function tryInitMap(retries = 20) {
  if (typeof kakao !== 'undefined' && kakao.maps) {
    kakao.maps.load(() => {
      initMap();
    });
  } else if (retries > 0) {
    setTimeout(() => tryInitMap(retries - 1), 300);
  } else {
    console.warn('[지도] Kakao Maps API를 불러오지 못했습니다. 키 및 허용 도메인 설정을 확인하세요.');
    renderMetroSchematic();
  }
}

function initMap() {
  const fallback = document.getElementById('mapFallback');
  if (fallback) fallback.style.display = 'none';

  const container = document.getElementById('kakaoMap');
  const centerPos = new kakao.maps.LatLng(36.3504, 127.3845); // 대전시청/중심부
  const options = {
    center: centerPos,
    level: 6, // 확대 레벨 (숫자가 클수록 축소)
  };

  state.map = new kakao.maps.Map(container, options);

  // 일반 지도와 스카이뷰로 지도 타입을 전환할 수 있는 지도타입 컨트롤
  const mapTypeControl = new kakao.maps.MapTypeControl();
  state.map.addControl(mapTypeControl, kakao.maps.ControlPosition.TOPRIGHT);

  // 줌 컨트롤
  const zoomControl = new kakao.maps.ZoomControl();
  state.map.addControl(zoomControl, kakao.maps.ControlPosition.RIGHT);

  // 역 마커 (커스텀 오버레이 또는 마커 표시)
  STATIONS.forEach(stn => {
    const pos = new kakao.maps.LatLng(stn.lat, stn.lng);

    // 작은 점 모양의 커스텀 오버레이 생성
    const content = document.createElement('div');
    content.style.cssText = `
      width: 10px; height: 10px; border-radius: 50%;
      background: #5C6E4A; border: 2px solid white;
      box-shadow: 0 1px 4px rgba(0,0,0,.35); cursor: pointer;
    `;
    content.title = `${stn.name}역`;
    content.addEventListener('click', () => {
      setDeparture(stn.lat, stn.lng, `${stn.name}역`);
    });

    const overlay = new kakao.maps.CustomOverlay({
      position: pos,
      content: content,
      yAnchor: 0.5,
      xAnchor: 0.5,
    });
    overlay.setMap(state.map);
  });

  // 지도 클릭 이벤트 -> 출발지 좌표 설정
  kakao.maps.event.addListener(state.map, 'click', function(mouseEvent) {
    const latlng = mouseEvent.latLng;
    setDeparture(latlng.getLat(), latlng.getLng());
  });
}

function setDeparture(lat, lng, label = null) {
  state.departure = { lat, lng };

  if (state.map) {
    if (state.departureMarker) {
      state.departureMarker.setMap(null);
    }

    const pos = new kakao.maps.LatLng(lat, lng);
    
    // 출발지 핀 모양 커스텀 오버레이
    const markerContent = document.createElement('div');
    markerContent.style.cssText = `
      width: 18px; height: 18px; border-radius: 50%;
      background: #A07845; border: 3px solid white;
      box-shadow: 0 2px 8px rgba(0,0,0,.4);
      transform: translate(-50%, -50%);
    `;
    markerContent.title = '선택한 출발지';

    state.departureMarker = new kakao.maps.CustomOverlay({
      position: pos,
      content: markerContent,
      zIndex: 10,
    });
    state.departureMarker.setMap(state.map);
  }

  // 위치 박스 갱신
  const box = document.getElementById('locationBox');
  box.innerHTML = `
    <div class="loc-addr">📍 ${label ?? '출발지 지정됨'}</div>
    <div class="loc-coords">위도 ${lat.toFixed(5)} · 경도 ${lng.toFixed(5)}</div>
  `;

  // 가까운 역 Top-5 계산 및 표시
  const sorted = [...STATIONS]
    .map(s => ({ ...s, km: distKm(lat, lng, s.lat, s.lng) }))
    .sort((a, b) => a.km - b.km)
    .slice(0, 5);

  document.getElementById('stationDistList').innerHTML = sorted.map(s => `
    <div class="stn-row">
      <span class="stn-row-name">${s.name}역</span>
      <span class="stn-row-dist">도보 약 ${kmToWalk(s.km)}분 (${(s.km * 1000).toFixed(0)}m)</span>
    </div>`).join('');
}

/** API 키 미설정 시: 1호선 역 텍스트 노선도 */
function renderMetroSchematic() {
  const wrap = document.getElementById('metroSchematic');
  if (!wrap) return;
  wrap.innerHTML = STATIONS.map(s =>
    `<span class="metro-stn" title="${s.name}역 클릭 → 출발지 설정"
      onclick="setDeparture(${s.lat}, ${s.lng}, '${s.name}역')">${s.name}</span>`
  ).join('→');
}


// ══════════════════════════════════════════════
// 6. 날짜 & 날씨 (TODO: 실제 API 연동)
// ══════════════════════════════════════════════
function initDateInput() {
  const input = document.getElementById('dateInput');
  const today = new Date().toISOString().split('T')[0];
  input.min = today;
  input.value = today;
  state.date = today;
  loadWeather(today);

  input.addEventListener('change', e => {
    state.date = e.target.value;
    loadWeather(e.target.value);
  });
}

function loadWeather(dateStr) {
  // TODO: 기상청 단기예보 API 또는 Open-Meteo 연동
  //   endpoint: https://api.open-meteo.com/v1/forecast?latitude=36.35&longitude=127.38&...
  const mock = mockWeather(dateStr);
  renderWeather(mock);
}

function mockWeather(dateStr) {
  const d = new Date(dateStr);
  const m = d.getMonth() + 1;
  const temp = m >= 6 && m <= 8  ? 28 + Math.floor(Math.random() * 5)
             : m >= 12 || m <= 2 ?  2 + Math.floor(Math.random() * 6)
             :                      14 + Math.floor(Math.random() * 9);
  const precip = Math.random() > 0.8 ? +(Math.random() * 12).toFixed(1) : 0;
  const snow   = temp < 2 && Math.random() > 0.85 ? +(Math.random() * 5).toFixed(1) : 0;
  const isWE   = d.getDay() === 0 || d.getDay() === 6;
  return { temp, precip, snow, isWeekend: isWE };
}

function renderWeather(w) {
  const icon = w.snow > 0 ? '❄️' : w.precip > 0 ? '🌧️' : '☀️';
  document.getElementById('weatherBox').innerHTML = `
    <div class="weather-inner">
      <div class="weather-temp">${icon} ${w.temp}°C</div>
      <div class="weather-detail">
        <div class="weather-row">강수 ${w.precip}mm · 적설 ${w.snow}cm</div>
        <div><span class="weather-badge">${w.isWeekend ? '🏖 주말/공휴일' : '💼 평일'}</span></div>
      </div>
    </div>
    <div class="weather-mock-note">⚠ 더미 데이터 · 실제 날씨 API 연동 예정</div>`;
}


// ══════════════════════════════════════════════
// 7. 카테고리 필터 & 슬라이더
// ══════════════════════════════════════════════
function initFilters() {
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.selectedCategory = btn.dataset.cat;
    });
  });
}

function initSlider() {
  const slider = document.getElementById('weightSlider');
  slider.addEventListener('input', () => {
    state.quietWeight = +slider.value;
    document.getElementById('distPct').textContent  = 100 - state.quietWeight;
    document.getElementById('quietPct').textContent = state.quietWeight;
  });
}


// ══════════════════════════════════════════════
// 8. 추천 스코어링 & 렌더링
// ══════════════════════════════════════════════
function computeRecommendations() {
  let list = [...DESTINATIONS];
  if (state.selectedCategory !== 'all') {
    list = list.filter(d => d.category === state.selectedCategory);
  }

  const MAX_LOAD = 450;
  const MAX_WALK = 60; // 분

  return list.map(dest => {
    const stn = STATIONS[dest.stationIdx];
    let walkMin = dest.walkMinutes;

    if (state.departure) {
      const km = distKm(state.departure.lat, state.departure.lng, stn.lat, stn.lng);
      walkMin = kmToWalk(km);
    }

    // TODO: mockLoad → ONNX 모델 추론값으로 교체
    const quietScore = Math.max(0, 1 - dest.mockLoad / MAX_LOAD);
    const distScore  = Math.max(0, 1 - walkMin / MAX_WALK);

    const wQ = state.quietWeight / 100;
    const wD = 1 - wQ;
    const totalScore = wQ * quietScore + wD * distScore;

    return { ...dest, walkMin, quietScore, distScore, totalScore };
  }).sort((a, b) => b.totalScore - a.totalScore);
}

function renderResults(results) {
  const section = document.getElementById('resultsSection');
  const cards   = document.getElementById('resultsCards');
  const meta    = document.getElementById('resultsMeta');

  const catText = state.selectedCategory === 'all' ? '전체 테마'
                : catLabel(state.selectedCategory);
  meta.textContent = `${state.date ?? '오늘'} · ${catText} · 더미 데이터 (ONNX 미연동)`;

  cards.innerHTML = results.map((d, i) => {
    const c = congestionInfo(d.mockLoad);
    return `
    <div class="result-card ${c.cls}"
         title="${d.desc}"
         onclick="alert('${d.name}\\n\\n상세 목적지 플랜은 개발 예정입니다.')">
      <div class="result-rank">#${i + 1} 추천</div>
      <div class="result-name">${d.name}</div>
      <div class="result-cat">${catEmoji(d.category)} ${catLabel(d.category)}</div>

      <div class="result-info">
        <span class="result-info-key">탑승역</span>
        <span class="result-info-val">${d.station}역</span>
      </div>
      <div class="result-info">
        <span class="result-info-key">역까지 도보</span>
        <span class="result-info-val">약 ${d.walkMin}분</span>
      </div>

      <div class="cong-wrap">
        <div class="cong-bar-label">
          <span>열차 혼잡도 (추정 ${d.mockLoad}명)</span>
        </div>
        <div class="cong-bar">
          <div class="cong-fill" style="width:${Math.min(100, c.pct).toFixed(1)}%"></div>
        </div>
        <div class="cong-text">${c.label}</div>
      </div>

      <div class="result-tags">
        ${d.tags.map(t => `<span class="result-tag">${t}</span>`).join('')}
      </div>

      <div class="score-row">
        <span class="score-label">추천 점수</span>
        <div class="score-bar-out">
          <div class="score-bar-in" style="width:${(d.totalScore * 100).toFixed(0)}%"></div>
        </div>
        <span class="score-num">${(d.totalScore * 100).toFixed(0)}점</span>
      </div>
    </div>`;
  }).join('');
}


// ══════════════════════════════════════════════
// 9. 검색 버튼
// ══════════════════════════════════════════════
function initSearchBtn() {
  document.getElementById('searchBtn').addEventListener('click', () => {
    const results = computeRecommendations();
    renderResults(results);
    document.getElementById('resultsSection').scrollIntoView({ behavior: 'smooth' });
  });
}


// ══════════════════════════════════════════════
// 10. 시각화 탭
// ══════════════════════════════════════════════
function initViz() {
  // 역 select 초기화 (최초 1회)
  const sel = document.getElementById('stationSelect');
  if (sel.options.length === 0) {
    STATIONS.forEach(s => {
      const o = document.createElement('option');
      o.value = s.idx;
      o.textContent = `${s.name}역`;
      if (s.idx === 10) o.selected = true;
      sel.appendChild(o);
    });
    sel.addEventListener('change', () => {
      state.vizStationIdx = +sel.value;
      updateLoadChart();
    });

    document.querySelectorAll('.toggle-btn[data-dir]').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.toggle-btn[data-dir]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.vizDirection = btn.dataset.dir;
        updateLoadChart();
      });
    });

    document.querySelectorAll('.toggle-btn[data-dtype]').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.toggle-btn[data-dtype]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.vizDaytype = btn.dataset.dtype;
        updateLoadChart();
      });
    });
  }

  updateLoadChart();
  renderHeatmap();
}

/** 더미 재차인원 (시간대별) — TODO: ONNX 추론으로 교체 */
function mockLoadByHour(stationIdx, direction, daytype) {
  const hours = [5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24];
  const isUp = direction === 'up';
  const isWE = daytype === 'weekend';

  // 중간 역일수록 승객이 많다 (sin 형태)
  const centralMod = 0.5 + Math.sin(stationIdx * Math.PI / 21);

  return hours.map(h => {
    let base = 60;
    if (h === 8)  base = isWE ? 110 : (isUp ? 185 : 235);
    if (h === 9)  base = isWE ?  90 : (isUp ? 150 : 175);
    if (h === 18) base = isWE ? 120 : (isUp ? 230 : 185);
    if (h === 19) base = isWE ? 100 : (isUp ? 165 : 145);
    if (h >= 11 && h <= 15) base = 85 + (h - 11) * 8;
    if (h >= 22) base = 30;
    if (h <= 6)  base = 22;
    return Math.max(8, Math.round(base * centralMod));
  });
}

function loadToColor(load) {
  if (load <  80) return `rgba(107,158, 94,${0.3 + load / 80 * 0.7})`;
  if (load < 180) return `rgba(196,168, 74,${0.4 + (load - 80) / 100 * 0.6})`;
  if (load < 300) return `rgba(196,126, 74,${0.5 + (load - 180) / 120 * 0.5})`;
  return                 `rgba(184, 90, 58,0.9)`;
}

function updateLoadChart() {
  const hours = [5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24];
  const loads = mockLoadByHour(state.vizStationIdx, state.vizDirection, state.vizDaytype);
  const colors = loads.map(l => loadToColor(l));

  const ctx = document.getElementById('loadChart');
  if (!ctx) return;
  if (state.loadChart) state.loadChart.destroy();

  state.loadChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: hours.map(h => `${h}시`),
      datasets: [{
        label: '재차인원 (명)',
        data: loads,
        backgroundColor: colors,
        borderRadius: 4,
        borderSkipped: false,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              const v = ctx.raw;
              const lbl = v < 80 ? '여유' : v < 180 ? '보통' : v < 300 ? '약간 혼잡' : '혼잡';
              return `${v}명 · ${lbl}`;
            },
          },
        },
      },
      scales: {
        y: {
          beginAtZero: true,
          suggestedMax: 460,
          grid: { color: '#EAE5DA' },
          ticks: { font: { size: 11 }, color: '#9B9080' },
        },
        x: {
          grid: { display: false },
          ticks: { font: { size: 11 }, color: '#9B9080' },
        },
      },
    },
  });
}

function renderHeatmap() {
  const hours = [5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23];
  const wrap  = document.getElementById('heatmapWrap');
  if (!wrap) return;

  let html = '<table class="heatmap-table"><thead><tr><th></th>';
  hours.forEach(h => { html += `<th>${h}</th>`; });
  html += '</tr></thead><tbody>';

  STATIONS.forEach(stn => {
    html += `<tr><th class="stn-th">${stn.name}</th>`;
    hours.forEach(h => {
      // 더미 값: 시각/역에 따라 결정론적 계산 (Math.sin 사용해 난수 없이 일관성 유지)
      let base = 60;
      if (h === 8 || h === 18) base = 220;
      if (h === 9 || h === 19) base = 160;
      if (h <= 6) base = 22;
      if (h >= 22) base = 30;
      const cm = 0.4 + Math.abs(Math.sin(stn.idx * 0.42 + h * 0.17));
      const load = Math.max(5, Math.round(base * cm));
      const title = `${stn.name}역 ${h}시 · 약 ${load}명`;
      html += `<td style="background:${loadToColor(load)}" title="${title}"></td>`;
    });
    html += '</tr>';
  });

  html += '</tbody></table>';
  wrap.innerHTML = html;
}


// ══════════════════════════════════════════════
// 11. 초기화
// ══════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initDateInput();
  initFilters();
  initSlider();
  initSearchBtn();

  // 최초 더미 결과 표시
  renderResults(computeRecommendations());

  // 지도 로드 시도 (Naver Maps script가 defer 로 늦게 로드될 수 있음)
  setTimeout(tryInitMap, 400);
});
