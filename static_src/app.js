'use strict';

// 대전 1호선 22개 역 사용자 제공 지도 좌표 (판암 0 ~ 반석 21)
const STATIONS = [
  { name: '판암',         idx: 0,  lat: 36.31696, lng: 127.45843 },
  { name: '신흥',         idx: 1,  lat: 36.31966, lng: 127.44880 },
  { name: '대동',         idx: 2,  lat: 36.32959, lng: 127.44284 },
  { name: '대전',         idx: 3,  lat: 36.33152, lng: 127.43367 },
  { name: '중앙로',       idx: 4,  lat: 36.32867, lng: 127.42583 },
  { name: '중구청',       idx: 5,  lat: 36.32480, lng: 127.41955 },
  { name: '서대전네거리', idx: 6,  lat: 36.32242, lng: 127.41258 },
  { name: '오룡',         idx: 7,  lat: 36.32869, lng: 127.40492 },
  { name: '용문',         idx: 8,  lat: 36.33817, lng: 127.39341 },
  { name: '탄방',         idx: 9,  lat: 36.34555, lng: 127.38457 },
  { name: '시청',         idx: 10, lat: 36.35153, lng: 127.38675 },
  { name: '정부청사',     idx: 11, lat: 36.35747, lng: 127.38127 },
  { name: '갈마',         idx: 12, lat: 36.35758, lng: 127.37280 },
  { name: '월평',         idx: 13, lat: 36.35826, lng: 127.36460 },
  { name: '갑천',         idx: 14, lat: 36.35475, lng: 127.35469 },
  { name: '유성온천',     idx: 15, lat: 36.35372, lng: 127.34145 },
  { name: '구암',         idx: 16, lat: 36.35670, lng: 127.33073 },
  { name: '현충원',       idx: 17, lat: 36.35909, lng: 127.32180 },
  { name: '월드컵경기장', idx: 18, lat: 36.36686, lng: 127.31700 },
  { name: '노은',         idx: 19, lat: 36.37415, lng: 127.31788 },
  { name: '지족',         idx: 20, lat: 36.38410, lng: 127.31950 },
  { name: '반석',         idx: 21, lat: 36.39218, lng: 127.31456 },
];

const state = {
  departure: null,
  date: null,
  selectedCategory: 'all',
  map: null,
  departureMarker: null,
  poiMarkers: [],
  poiInfoOverlay: null,
  routePolylines: [],
  metroSegments: null,
  pois: [],
  weatherRequestId: 0,
  weatherController: null,
  startHour: 5,
  endHour: 24,
  recommendationRequestId: 0,
  recommendationController: null,
  researchTimer: null,
  weather: null,
  nextWeather: null,
  results: [],
  lastMeta: null,
  selectedItem: null,
  chipRange: null,    // 마지막 '장소별 최적 시간' 검색의 시간 범위
  groupHours: {},      // 구간 묶음 id -> 그 묶음에서 고른 시간(막대). 순위·목록 순서는 바뀌지 않는다
  floatMode: false,    // 순위 막대를 떠 있는 창으로 보기(검색 화면 설정, localStorage 에 저장)
  floatGid: null,      // 떠 있는 창이 보여 주는 구간 묶음 id
  floatPos: null,      // 창의 마지막 위치(메모리에만 저장)
  open: null,          // 펼친 카테고리 구역 키 집합. null 이면 다음 그리기에서 첫 묶음만 펼친다
  listed: [],
  mapPickMode: false,
};

const WALK_KMH = 4.5, WALK_DETOUR = 1.3; // 추천 계산과 같은 도보 시간 어림값

function staticEngine() {
  const engine = window.StaticRecommendation;
  if (!engine || typeof engine.recommend !== 'function' || typeof engine.fetchWeatherForDate !== 'function') {
    throw new Error('추천 자료를 준비하지 못했습니다. 페이지를 새로고침한 뒤 다시 시도해 주세요.');
  }
  return engine;
}

function cancelPendingRecommendation() {
  if (!state.recommendationController) return;
  state.recommendationController.abort();
  state.recommendationController = null;
  state.recommendationRequestId++;
  const button = document.getElementById('searchBtn');
  button.disabled = false;
  button.removeAttribute('aria-busy');
  setSearchLabel('다시 찾기');
  setUpdating(false);
  if (state.results.length) {
    renderRecommendations({ meta: state.lastMeta });
    setStale(true);
  } else {
    renderEmptyState();
  }
  showUpdateNote('조건이 바뀌어 이전 계산을 중단했어요. 다시 찾기를 눌러 주세요.');
}

function nextDate(date) {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

function distKm(lat1, lng1, lat2, lng2) {
  const r = Math.PI / 180, dLat = (lat2 - lat1) * r, dLng = (lng2 - lng1) * r;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dLng / 2) ** 2;
  return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

const catLabel = c => ({ library: '도서관', park: '공원', bookstore: '서점' })[c] || c || '기타';
// 선 아이콘(stroke 1.7, currentColor). 장식용이라 aria-hidden, 뜻은 옆의 글자가 전달한다.
const svgIcon = d => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${d}</svg>`;
const ICON = {
  park: svgIcon('<path d="M12 21v-6"/><path d="M12 15a5 5 0 1 0-4-8 4 4 0 0 0 1 8z"/><path d="M12 15a5 5 0 1 1 4-8 4 4 0 0 1-1 8z"/>'),
  library: svgIcon('<path d="M4 5h6a2 2 0 0 1 2 2v13a2 2 0 0 0-2-2H4z"/><path d="M20 5h-6a2 2 0 0 0-2 2v13a2 2 0 0 1 2-2h6z"/>'),
  bookstore: svgIcon('<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 7h6"/>'),
  walk: svgIcon('<circle cx="13" cy="4" r="2"/><path d="M9 21l3-7M12 14l-2-4 4-2 3 4M12 14l3 7"/>'),
  train: svgIcon('<rect x="5" y="3" width="14" height="14" rx="3"/><path d="M5 12h14M9 21l2-4M15 21l-2-4"/>'),
  pin: svgIcon('<path d="M12 21s-6-5.6-6-10a6 6 0 0 1 12 0c0 4.4-6 10-6 10z"/><circle cx="12" cy="11" r="2"/>'),
  search: svgIcon('<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>'),
};
const catIcon = c => ICON[c] || ICON.pin;
const setSearchLabel = text => { document.getElementById('searchBtn').innerHTML = `${ICON.search}<span class="go-label">${text}</span>`; };
const hasCoords = p => p.latitude !== null && p.longitude !== null && p.latitude !== '' && p.longitude !== '' && Number.isFinite(Number(p.latitude)) && Number.isFinite(Number(p.longitude));

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function nearestStation(p) {
  const lat = Number(p.latitude ?? p.lat);
  const lng = Number(p.longitude ?? p.lng);
  return STATIONS.map(s => ({ station: s, km: distKm(lat, lng, s.lat, s.lng) })).sort((a, b) => a.km - b.km)[0];
}

function initTabs() {
  document.querySelectorAll('.tab-nav-btn').forEach(btn => btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-nav-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
    renderFloat();   // 추천 탭이 아니면 숨기고, 돌아오면 같은 자리에 다시 보인다(상태는 유지)
  }));
}

function tryInitMap() {
  try {
    if (!window.MapView || !window.MapViewProjection) throw new Error('Map unavailable');
    initMap();
  } catch (_) {
    state.map = null;
    document.getElementById('mapFallback').style.display = '';
    renderMetroSchematic();
  }
}

function initMap() {
  state.map = new MapView.Map(document.getElementById('kakaoMap'), { center: new MapView.LatLng(36.3515, 127.3867), level: 6 });
  document.getElementById('mapFallback').style.display = 'none';

  STATIONS.forEach(s => {
    const node = document.createElement('div');
    node.className = 'station-dot';
    node.title = `${s.name}역`;
    node.addEventListener('click', e => {
      e.stopPropagation();
      if (state.mapPickMode) setDeparture(s.lat, s.lng, `${s.name}역`);
    });
    new MapView.CustomOverlay({
      position: new MapView.LatLng(s.lat, s.lng),
      content: node,
      yAnchor: 0.5,
      xAnchor: 0.5,
      zIndex: 4,
    }).setMap(state.map);
  });

  MapView.event.addListener(state.map, 'click', e => {
    if (state.mapPickMode) setDeparture(e.latLng.getLat(), e.latLng.getLng());
  });

  renderPoiMarkers(state.listed);
}

function setDeparture(lat, lng, label = null) {
  if (state.mapPickMode) setMapPickMode(false);
  const previousDeparture = state.departure;
  const departureChanged = !!previousDeparture && (previousDeparture.lat !== lat || previousDeparture.lng !== lng);
  state.departure = { lat, lng };

  if (state.map) {
    if (state.departureMarker) state.departureMarker.setMap(null);
    const node = document.createElement('div');
    node.className = 'departure-dot';
    node.title = '선택한 출발지';
    // xAnchor: 0.5, yAnchor: 0.5로 정확히 클릭 커서 위치에 중심 배치
    state.departureMarker = new MapView.CustomOverlay({
      position: new MapView.LatLng(lat, lng),
      content: node,
      xAnchor: 0.5,
      yAnchor: 0.5,
      zIndex: 10,
    });
    state.departureMarker.setMap(state.map);
  }

  document.getElementById('locationBox').innerHTML = `<div class="loc-addr">${ICON.pin} ${escapeHtml(label || '출발지 지정됨')}</div><div class="loc-coords">위도 ${lat.toFixed(5)} · 경도 ${lng.toFixed(5)}</div>`;
  const slot = document.getElementById('slotOrigin');
  if (slot) slot.textContent = label || '지도에서 고른 위치';
  const near = STATIONS.map(s => ({ ...s, km: distKm(lat, lng, s.lat, s.lng) })).sort((a, b) => a.km - b.km).slice(0, 5);
  document.getElementById('stationDistList').innerHTML = near.map(s => `<div class="stn-row"><span class="stn-row-name">${escapeHtml(s.name)}역</span><span class="stn-row-dist">직선거리 ${(s.km * 1000).toFixed(0)}m</span></div>`).join('');

  if (departureChanged) {
    // 출발지를 바꾸면 이전 기준의 결과·경로·분석은 즉시 버리고, 사용자가 다시 찾기를 누를 때만 재계산한다.
    clearTimeout(state.researchTimer);
    state.researchTimer = null;
    state.recommendationController?.abort();
    state.recommendationController = null;
    state.recommendationRequestId++;
    const searchButton = document.getElementById('searchBtn');
    searchButton.disabled = false;
    searchButton.removeAttribute('aria-busy');
    setSearchLabel('찾기');
    setUpdating(false);
    setStale(false);
    state.results = [];
    state.lastMeta = null;
    state.selectedItem = null;
    state.listed = [];
    state.groupHours = {};
    state.open = null;
    state.floatGid = null;
    renderFloat();
    clearRoute();
    renderPoiMarkers([]);
    document.getElementById('resultsMeta').textContent = '출발지가 바뀌어 추천이 초기화되었습니다';
    document.getElementById('resultsCards').innerHTML = '<p class="empty-state" role="status">출발지가 바뀌었어요. 다시 찾기를 눌러 주세요.</p>';
    document.getElementById('predictionAnalysis').textContent = '출발지가 바뀌었어요. 다시 찾기를 누르면 분석 결과를 볼 수 있습니다.';
    const viewStatus = document.getElementById('viewStatus');
    if (viewStatus) viewStatus.textContent = '';
    showUpdateNote('출발지가 바뀌었어요. 다시 찾기를 눌러 주세요.');
    window.Analysis?.setSelected(null);
    window.Analysis?.refreshHeatmap();
  } else if (!previousDeparture) {
    // 첫 출발지 지정은 기존의 명확한 검색 전 안내를 유지한다.
    renderEmptyState();
  }
}

function renderMetroSchematic() {
  const wrap = document.getElementById('metroSchematic');
  if (!wrap) return;
  wrap.innerHTML = STATIONS.map(s => `<button class="metro-stn" onclick="setDeparture(${s.lat},${s.lng},'${escapeHtml(s.name)}역')">${escapeHtml(s.name)}</button>`).join(' → ');
}

// ─────────────────────────────────────────────
// 🗺 경로 시각화 (지하철 노선 + 보행 점선)
// ─────────────────────────────────────────────
function clearRoute() {
  state.routePolylines.forEach(p => p.setMap(null));
  state.routePolylines = [];
  if (state.poiInfoOverlay) {
    state.poiInfoOverlay.setMap(null);
    state.poiInfoOverlay = null;
  }
}

function getSubwayStationsAlong(bStation, aStation) {
  if (!bStation || !aStation) return [];
  const bIdx = bStation.idx ?? STATIONS.findIndex(s => s.name === bStation.name);
  const aIdx = aStation.idx ?? STATIONS.findIndex(s => s.name === aStation.name);
  if (bIdx === -1 || aIdx === -1 || bIdx === aIdx) return [];

  return bIdx < aIdx
    ? STATIONS.slice(bIdx, aIdx + 1)
    : STATIONS.slice(aIdx, bIdx + 1).reverse();
}

function metroPathFor(stationsAlong) {
  const fallback = () => stationsAlong.map(s => [s.lat, s.lng]);
  if (!state.metroSegments || stationsAlong.length < 2) return fallback();
  const points = [];
  for (let i = 0; i < stationsAlong.length - 1; i++) {
    const key = `${stationsAlong[i].idx}-${stationsAlong[i + 1].idx}`;
    const segment = state.metroSegments[key];
    if (!Array.isArray(segment) || segment.length < 2) return fallback();
    points.push(...(i ? segment.slice(1) : segment));
  }
  return points;
}

async function loadMetroLineGeometry() {
  try {
    const response = await fetch('./data/metro_line_geometry.json', { cache: 'no-cache' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (data.source !== 'OpenStreetMap' || !data.segments || Object.keys(data.segments).length !== 42) {
      throw new Error('선로 좌표 자료가 올바르지 않습니다.');
    }
    state.metroSegments = data.segments;
    if (state.selectedItem && state.map) showPlaceRoute(state.selectedItem, true, false);
  } catch (error) {
    console.warn('실제 선로 좌표를 불러오지 못해 역 좌표를 연결합니다.', error);
  }
}

function showPlaceRoute(item, isRecommendation = false, adjustBounds = true) {
  state.selectedItem = item;
  if (isRecommendation) window.Analysis?.setSelected(item);
  if (!state.map) return;
  clearRoute();

  const poi = isRecommendation ? (item.poi || {}) : item;
  const poiLat = Number(poi.latitude);
  const poiLng = Number(poi.longitude);
  if (!Number.isFinite(poiLat) || !Number.isFinite(poiLng)) return;

  const poiPos = new MapView.LatLng(poiLat, poiLng);
  const required = [{ pos: poiPos, isPlace: true }];  // side 는 카드 위치 결정 후 채운다

  // 💡 1. 출발지 및 목적지 기준 가장 가까운 역을 항상 현재 위치 기준으로 정확히 결정
  // (이전 검색 결과의 '예전 역'에 묶여 경로가 엉뚱한 곳으로 이어지는 문제 해결)
  const currentDepartureStation = state.departure ? nearestStation(state.departure).station : null;
  const currentPoiStation = nearestStation(poi).station;

  // 추천 항목은 추천 계산이 고른 승차·하차역을 그대로 그린다(화면이 따로 판단하지 않는다). 항목이 아닌 경우에만 현재 출발지의 가까운 역을 쓴다.
  const serverBoard = item.boarding_station ? (STATIONS.find(s => s.name === item.boarding_station.name) || item.boarding_station) : null;
  let bStation = (isRecommendation && serverBoard) ? serverBoard : (currentDepartureStation || serverBoard);
  let aStation = item.alighting_station ? (STATIONS.find(s => s.name === item.alighting_station.name) || item.alighting_station) : currentPoiStation;

  // 걷기만 할지 열차를 탈지는 추천 계산의 결정(열차 없는 후보 = no_train, 승·하차역이 같음)을 따른다. 지도·카드·길찾기 링크가 서로 어긋나지 않게 한다.
  const directDist = state.departure ? distKm(state.departure.lat, state.departure.lng, poiLat, poiLng) : 999;
  const walkToBoardDist = (state.departure && bStation) ? distKm(state.departure.lat, state.departure.lng, bStation.lat, bStation.lng) : 0;
  const walkFromAlightDist = aStation ? distKm(aStation.lat, aStation.lng, poiLat, poiLng) : 0;
  const hasRide = !!(bStation && aStation && bStation.name !== aStation.name) && !(isRecommendation && item.no_train);
  const isDirectWalk = !hasRide;
  // 참고용 안내: 승·하차역까지 걷는 거리의 합보다 출발지~장소 직선이 훨씬 짧으면 걸어가는 편이 나을 수 있다(점수는 바꾸지 않는다).
  const walkMayBeBetter = hasRide && !!state.departure && directDist < (walkToBoardDist + walkFromAlightDist) * 0.85;

  if (state.departure) {
    const depPos = new MapView.LatLng(state.departure.lat, state.departure.lng);
    required.push({ pos: depPos });

    if (isDirectWalk) {
      // 🚶 지하철 불필요: 출발지 → 목적지 직행 도보 점선
      const line = new MapView.Polyline({
        map: state.map,
        path: [depPos, poiPos],
        strokeWeight: 4,
        strokeColor: '#13201A',
        strokeOpacity: 0.85,
        strokeStyle: 'shortdash',
      });
      state.routePolylines.push(line);
    } else {
      // 🚇 지하철 이용 경로:
      // [1] 출발지 → 탑승역 보행 점선
      const bPos = new MapView.LatLng(bStation.lat, bStation.lng);
      required.push({ pos: bPos });
      const walkToBoardLine = new MapView.Polyline({
        map: state.map,
        path: [depPos, bPos],
        strokeWeight: 4,
        strokeColor: '#13201A',
        strokeOpacity: 0.85,
        strokeStyle: 'shortdash',
      });
      state.routePolylines.push(walkToBoardLine);

      // 탑승역 뱃지
      const bBadge = document.createElement('div');
      bBadge.className = 'route-station-badge';
      bBadge.innerHTML = `${ICON.train}<span>승차 ${escapeHtml(bStation.name)}역</span>`;
      const bOverlay = new MapView.CustomOverlay({
        position: bPos,
        content: bBadge,
        yAnchor: 1.6,
        zIndex: 16,
      });
      bOverlay.setMap(state.map);
      state.routePolylines.push(bOverlay);

      // [2] 지하철 노선 경로:
      // 지도 앱 공식 대중교통 노선 스타일 (흰색 외곽선 10px + 대전 1호선 녹색 6px 이중 레이어)
      const stationsAlong = getSubwayStationsAlong(bStation, aStation);
      if (stationsAlong.length > 1) {
        const metroPath = metroPathFor(stationsAlong).map(([lat, lng]) => new MapView.LatLng(lat, lng));

        // 2-1. 흰색 테두리 밑선
        const metroUnderlay = new MapView.Polyline({
          map: state.map,
          path: metroPath,
          strokeWeight: 10,
          strokeColor: '#FFFFFF',
          strokeOpacity: 0.95,
          strokeStyle: 'solid',
          zIndex: 5,
        });
        state.routePolylines.push(metroUnderlay);

        // 2-2. 대전 1호선 녹색 본선
        const metroLine = new MapView.Polyline({
          map: state.map,
          path: metroPath,
          strokeWeight: 6,
          strokeColor: '#0B8F4D', // 노선 초록(디자인 토큰 --line)
          strokeOpacity: 1.0,
          strokeStyle: 'solid',
          zIndex: 6,
        });
        state.routePolylines.push(metroLine);

        // 2-3. 경유하는 각 역마다 동그란 노선도 노드 마커 표시
        stationsAlong.forEach(stn => {
          const dot = document.createElement('div');
          dot.className = 'route-station-node';
          dot.title = `${stn.name}역`;
          const overlay = new MapView.CustomOverlay({
            position: new MapView.LatLng(stn.lat, stn.lng),
            content: dot,
            xAnchor: 0.5,
            yAnchor: 0.5,
            zIndex: 14,
          });
          overlay.setMap(state.map);
          state.routePolylines.push(overlay);
        });
      }

      // [3] 하차역 뱃지 & 하차역 → 목적지 보행 점선
      const aPos = new MapView.LatLng(aStation.lat, aStation.lng);
      required.push({ pos: aPos });

      const aBadge = document.createElement('div');
      aBadge.className = 'route-station-badge alight';
      aBadge.innerHTML = `${ICON.walk}<span>하차 ${escapeHtml(aStation.name)}역</span>`;
      const aOverlay = new MapView.CustomOverlay({
        position: aPos,
        content: aBadge,
        yAnchor: -0.6,       // 승차 뱃지는 위, 하차 뱃지는 아래: 1정거장처럼 두 역이 가까워도 겹치지 않는다
        zIndex: 16,
      });
      aOverlay.setMap(state.map);
      state.routePolylines.push(aOverlay);

      const walkToPoiLine = new MapView.Polyline({
        map: state.map,
        path: [aPos, poiPos],
        strokeWeight: 4,
        strokeColor: '#13201A',
        strokeOpacity: 0.85,
        strokeStyle: 'shortdash',
      });
      state.routePolylines.push(walkToPoiLine);
    }
  } else {
    // 출발지가 아직 없을 때: 목적지 및 인근 역 표시
    if (aStation) {
      const aPos = new MapView.LatLng(aStation.lat, aStation.lng);
      required.push({ pos: aPos });
      const line = new MapView.Polyline({
        map: state.map,
        path: [aPos, poiPos],
        strokeWeight: 4,
        strokeColor: '#13201A',
        strokeOpacity: 0.85,
        strokeStyle: 'shortdash',
      });
      state.routePolylines.push(line);
    }
  }

  // 목적지 핀: 다른 장소의 작은 점과 구별되는 큰 핀 (경로 위에 표시)
  const pin = document.createElement('div');
  pin.className = 'dest-pin';
  pin.setAttribute('role', 'img');
  pin.setAttribute('aria-label', `목적지 ${poi.name || ''}`);
  pin.innerHTML = '<svg viewBox="0 0 30 40" width="30" height="40" aria-hidden="true"><path d="M15 39C15 39 2 24 2 14a13 13 0 0 1 26 0C28 24 15 39 15 39z" fill="#13201A" stroke="#fff" stroke-width="2.5"/><circle cx="15" cy="14" r="5" fill="#fff"/></svg>';
  const pinOverlay = new MapView.CustomOverlay({ position: poiPos, content: pin, xAnchor: 0.5, yAnchor: 1, zIndex: 30 });
  pinOverlay.setMap(state.map);
  state.routePolylines.push(pinOverlay);

  // 정보 카드는 경로가 들어오는 쪽의 반대편에 둔다 (경로선·역·출발지를 가리지 않도록)
  let side = 'north';
  if (required.length > 1) {
    const prev = required[required.length - 1].pos;
    const dy = poiPos.getLat() - prev.getLat();
    const dx = (poiPos.getLng() - prev.getLng()) * Math.cos(poiPos.getLat() * Math.PI / 180);
    if (Math.abs(dy) >= Math.abs(dx)) side = dy >= 0 ? 'north' : 'south';
    else side = dx >= 0 ? 'east' : 'west';
  }
  const anchors = { north: [0.5, 1], south: [0.5, 0], east: [0, 0.5], west: [1, 0.5] };
  const wrap = document.createElement('div');
  wrap.className = `poi-card-wrap side-${side}`;
  const content = document.createElement('div');
  content.className = 'poi-info-card';
  wrap.appendChild(content);
  content.innerHTML = `
    <div class="poi-info-title">
      <span class="poi-info-name">${catIcon(poi.facility_type)}<span class="poi-info-name-text">${escapeHtml(poi.name)}</span></span>
      <span class="poi-info-category">${catLabel(poi.facility_type)}</span>
    </div>
    <div class="poi-info-route">
      ${isDirectWalk
        ? `${ICON.walk}<span class="poi-info-route-text">도보 직행 (약 ${(directDist * 1000).toFixed(0)}m · 지하철 불필요)</span>`
        : `${ICON.train}<span class="poi-info-route-text">${escapeHtml(bStation.name)}역 탑승 → ${escapeHtml(aStation.name)}역 하차</span>`}
    </div>
    ${walkMayBeBetter ? `<div class="poi-info-advice">걸어서 바로 가는 편이 더 가까울 수 있어요 (직선 약 ${(directDist * 1000).toFixed(0)}m)</div>` : ''}
    <div class="poi-info-link">${kakaoRouteLink(poi, isDirectWalk)}</div>
    ${hasRide ? '<div class="poi-info-attribution"><a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">선로 좌표 © OpenStreetMap</a></div>' : ''}
  `;
  ['click', 'mousedown', 'touchstart'].forEach(t => content.addEventListener(t, ev => ev.stopPropagation()));
  state.poiInfoOverlay = new MapView.CustomOverlay({
    position: poiPos,
    content: wrap,
    xAnchor: anchors[side][0],
    yAnchor: anchors[side][1],
    zIndex: 20,
  });
  state.poiInfoOverlay.setMap(state.map);

  // 카드나 마커를 직접 클릭했을 때: 필요한 지점이 이미 화면 안이면 지도를 건드리지 않고, 벗어난 경우에만 최소한으로 넓힌다.
  if (adjustBounds) {
    required[0].side = side;
    const wr = wrap.getBoundingClientRect();
    required[0].size = wr.width ? { w: wr.width, h: wr.height } : null;
    ensureVisible(required);
  }
}

// 목적지(핀 + 정보 카드)·출발지·승하차역이 지도 칸 안에 모두 들어오게 한다.
// 이미 들어와 있으면 아무것도 하지 않고, 아니면 (1) 들어갈 때까지만 축소하고 (2) 가장 적게 평행이동한다. 확대는 하지 않는다.
function ensureVisible(points) {
  const map = state.map;
  const el = document.getElementById('kakaoMap');
  if (!map || !el || !points.length) return;
  map.relayout(); // 결과 영역 때문에 지도 칸 크기가 바뀐 경우 카카오 내부 크기를 먼저 맞춘다
  const W = el.clientWidth, H = el.clientHeight;
  if (!W || !H) return;
  const pad = 14, padR = 54; // 오른쪽은 지도 확대/축소 컨트롤을 피한다
  const measure = () => {
    const proj = map.getProjection();
    let l = Infinity, t = Infinity, r = -Infinity, b = -Infinity;
    const add = (x0, y0, x1, y1) => { l = Math.min(l, x0); t = Math.min(t, y0); r = Math.max(r, x1); b = Math.max(b, y1); };
    points.forEach(({ pos, isPlace, side, size }) => {
      const c = proj.containerPointFromCoords(pos);
      if (!isPlace) { add(c.x - 8, c.y - 8, c.x + 8, c.y + 8); return; }
      const w = size?.w || 250, h = size?.h || 110;
      add(c.x - 15, c.y - 40, c.x + 15, c.y);                       // 핀
      if (side === 'north') add(c.x - w / 2, c.y - h, c.x + w / 2, c.y);
      else if (side === 'south') add(c.x - w / 2, c.y, c.x + w / 2, c.y + h);
      else if (side === 'east') add(c.x, c.y - h / 2, c.x + w, c.y + h / 2);
      else add(c.x - w, c.y - h / 2, c.x, c.y + h / 2);
    });
    return { l, t, r, b };
  };
  let rect = measure();
  const fits = q => q.l >= pad && q.t >= pad && q.r <= W - padR && q.b <= H - pad;
  if (fits(rect)) return;
  let guard = 0;
  while ((rect.r - rect.l > W - pad - padR || rect.b - rect.t > H - 2 * pad) && map.getLevel() < 14 && guard++ < 8) {
    map.setLevel(map.getLevel() + 1, { animate: false });
    rect = measure();
  }
  const dx = rect.l < pad ? rect.l - pad : (rect.r > W - padR ? rect.r - (W - padR) : 0);
  const dy = rect.t < pad ? rect.t - pad : (rect.b > H - pad ? rect.b - (H - pad) : 0);
  if (dx || dy) map.panBy(dx, dy);
}

// ─────────────────────────────────────────────
// POI 데이터 및 날씨
// ─────────────────────────────────────────────
async function loadPois() {
  const cards = document.getElementById('resultsCards');
  cards.innerHTML = '<p class="empty-state" role="status">장소 데이터를 불러오는 중입니다.</p>';
  try {
    const response = await fetch('./data/pois.json');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!Array.isArray(data)) throw new Error('POI 데이터 형식이 배열이 아닙니다.');
    // 유효한 장소(도서관, 공원, 서점)만 필터링
    state.pois = data.filter(p => p.facility_type === 'library' || p.facility_type === 'park' || p.facility_type === 'bookstore');
    renderEmptyState();
  } catch (error) {
    console.error('POI 데이터 로드 실패:', error);
    cards.innerHTML = '<p class="empty-state">장소 데이터를 불러오지 못했습니다. 페이지를 새로고침한 뒤 다시 시도해 주세요.</p>';
    document.getElementById('resultsMeta').textContent = '데이터 로드 실패';
  }
}

function initDateInput() {
  const input = document.getElementById('dateInput');
  const today = window.WeatherClient?.getToday?.() || new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' });
  input.value = today;
  state.date = today;
  loadWeather(today);
  input.addEventListener('change', e => {
    if (!e.target.value) return;
    state.date = e.target.value;
    cancelPendingRecommendation();
    loadWeather(state.date);
    if (state.results.length > 0) {
      setSearchLabel('다시 찾기');
      document.getElementById('predictionAnalysis').textContent = '날짜가 변경되었습니다. [다시 찾기]를 누르면 해당 날짜 예보와 시간표로 다시 계산합니다.';
    }
  });
}

async function loadWeather(date) {
  const box = document.getElementById('weatherBox'), id = ++state.weatherRequestId;
  state.weatherController?.abort();
  const controller = new AbortController();
  state.weatherController = controller;
  state.weather = null;
  state.nextWeather = null;
  box.setAttribute('aria-busy', 'true');
  box.innerHTML = '<span class="placeholder-text">날씨를 불러오는 중입니다…</span>';
  let timedOut = false;
  const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 45000);
  try {
    const engine = staticEngine();
    const result = await engine.fetchWeatherForDate(date, { signal: controller.signal });
    if (id !== state.weatherRequestId) return;
    controller.signal.throwIfAborted();
    if (!result?.available) throw new Error(result?.reason || '선택한 날짜의 날씨가 아직 제공되지 않거나 연결이 원활하지 않습니다.');
    state.weather = result;
    renderHourlyWeather();
    const following = await engine.fetchWeatherForDate(nextDate(date), { signal: controller.signal });
    if (id !== state.weatherRequestId) return;
    controller.signal.throwIfAborted();
    state.nextWeather = following || { available: false };
    renderHourlyWeather();
  } catch (error) {
    if (id !== state.weatherRequestId) return;
    if (state.weather?.available) {
      state.nextWeather = { available: false, date: nextDate(date) };
      renderHourlyWeather();
    } else {
      const message = timedOut ? '날씨 조회가 오래 걸리고 있습니다. 잠시 후 다시 시도해 주세요.'
        : error.name === 'AbortError' ? '날씨 조회를 중단했습니다. 다시 시도할 수 있습니다.'
        : '선택한 날짜의 날씨를 불러오지 못했습니다. 제공 범위나 연결 상태를 확인한 뒤 다시 시도해 주세요.';
      box.innerHTML = `<span class="placeholder-text" role="status">${escapeHtml(message)}</span>`;
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'update-retry';
      retry.textContent = '날씨 다시 불러오기';
      retry.addEventListener('click', () => loadWeather(state.date));
      box.appendChild(retry);
    }
  } finally {
    clearTimeout(timeout);
    if (id === state.weatherRequestId) {
      state.weatherController = null;
      box.removeAttribute('aria-busy');
    }
  }
}

function weatherNumber(value, unit) {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)}${unit}` : '자료 없음';
}

function renderHourlyWeather() {
  if (!state.weather?.available) return;
  const rows = [];
  for (let hour = state.startHour; hour <= state.endHour; hour++) {
    const day = hour === 24 ? state.nextWeather : state.weather, key = `${hour === 24 ? nextDate(state.date) : state.date}T${String(hour % 24).padStart(2, '0')}:00`;
    const h = day?.hourly, i = h?.time?.indexOf(key) ?? -1;
    rows.push(`<tr><th>${hour === 24 ? '24시 (익일 00시)' : `${hour}시`}</th><td>${weatherNumber(h?.temperature_2m?.[i], '°C')}</td><td>${weatherNumber(h?.precipitation?.[i], 'mm')}</td><td>${weatherNumber(h?.snowfall?.[i], 'cm')}</td></tr>`);
  }
  document.getElementById('weatherBox').innerHTML = `<div class="weather-badge">Open-Meteo · ${['archive', 'local_archive'].includes(state.weather.source) ? '과거 날씨' : '예보'}</div><div class="weather-hourly"><table><caption>선택한 시간대의 대전 날씨</caption><thead><tr><th>시간</th><th>기온</th><th>강수</th><th>적설</th></tr></thead><tbody>${rows.join('')}</tbody></table></div>${state.endHour === 24 && !state.nextWeather?.available ? `<p class="control-help">${state.nextWeather ? '익일 00시 날씨는 불러오지 못했거나 제공 범위 밖입니다.' : '익일 00시 날씨를 조회 중입니다…'}</p>` : ''}`;
}

function initRecommendationControls() {
  for (const [id, value] of [['startHour', state.startHour], ['endHour', state.endHour]]) {
    const input = document.getElementById(id);
    input.innerHTML = Array.from({ length: 20 }, (_, i) => i + 5).map(h => `<option value="${h}">${h === 24 ? '24시 (익일 00시)' : `${h}시`}</option>`).join('');
    input.value = value;
    input.addEventListener('change', () => {
      state.startHour = Number(document.getElementById('startHour').value);
      state.endHour = Number(document.getElementById('endHour').value);
      if (state.startHour > state.endHour) {
        if (id === 'startHour') state.endHour = state.startHour;
        else state.startHour = state.endHour;
        document.getElementById('startHour').value = state.startHour;
        document.getElementById('endHour').value = state.endHour;
      }
      cancelPendingRecommendation();
      renderHourlyWeather();
      if (state.results.length > 0) {
        setSearchLabel('다시 찾기');
        document.getElementById('predictionAnalysis').textContent = '시간 범위가 변경되었습니다. [다시 찾기]를 누르면 새 시간대 열차를 계산합니다.';
      }
    });
  }

}

function initFilters() {
  document.querySelectorAll('.filter-btn').forEach(btn => btn.addEventListener('click', () => {
    cancelPendingRecommendation();
    document.querySelectorAll('.filter-btn').forEach(b => { b.classList.remove('active'); b.setAttribute('aria-pressed', 'false'); });
    btn.classList.add('active');
    btn.setAttribute('aria-pressed', 'true');
    state.selectedCategory = btn.dataset.cat;
    const sel = document.getElementById('catSelect');
    if (sel) sel.value = state.selectedCategory;

    if (state.results && state.results.length > 0) {
      // 추천 결과 모드일 때: 현재 카테고리에 맞게 필터링 렌더링 (지도 마커도 함께 갱신)
      state.open = null;
      renderRecommendations({ meta: state.lastMeta });
    } else {
      // 검색 전: 장소를 지도에 쏟아내지 않고 안내만 유지
      renderEmptyState();
    }
  }));
  document.getElementById('catSelect')?.addEventListener('change', e => {
    document.querySelector(`.filter-btn[data-cat="${e.target.value}"]`)?.click();
  });
}

// ─────────────────────────────────────────────
// 검색 전 안내 (장소 마커/카드를 미리 보여주지 않음)
// ─────────────────────────────────────────────
function renderEmptyState() {
  renderPoiMarkers([]);
  state.results = state.results || [];
  document.getElementById('resultsMeta').textContent = '추천 결과 대기 중';
  document.getElementById('resultsCards').innerHTML = `<div class="empty-state empty-guide" role="status">
    <strong>추천을 받을 준비가 되었어요</strong>
    <ol>
      <li>출발지 선택을 눌러 지도 선택을 켠 뒤, 지도에서 위치를 고릅니다.</li>
      <li>방문 날짜와 이용할 시간 범위를 정합니다.</li>
      <li>[찾기] 버튼을 누르면 추천 장소가 지도와 목록에 나타납니다.</li>
    </ol>
  </div>`;
}

// 추천된 장소만 지도에 표시한다.
function renderPoiMarkers(results = state.listed) {
  state.poiMarkers.forEach(m => m.setMap(null));
  state.poiMarkers = [];
  if (!state.map) return;

  const seen = new Set();
  results.forEach(r => {
    const p = r.poi || {};
    if (!hasCoords(p)) return;
    const key = p.name || `${p.latitude},${p.longitude}`;
    if (seen.has(key)) return;
    seen.add(key);

    const node = document.createElement('button');
    node.className = 'poi-map-dot';
    node.type = 'button';
    node.title = p.name || '';
    node.setAttribute('aria-label', p.name || '장소');
    node.addEventListener('click', e => {
      e.stopPropagation();
      selectPlace(r, true);
    });

    const overlay = new MapView.CustomOverlay({
      position: new MapView.LatLng(Number(p.latitude), Number(p.longitude)),
      content: node,
      yAnchor: 0.5,
      xAnchor: 0.5,
      zIndex: 2,
    });
    overlay.setMap(state.map);
    state.poiMarkers.push(overlay);
  });
}

// 카카오맵 길찾기 링크 (공식 지도 URL 링크 형식: /link/by/{walk|traffic}/이름,위도,경도/이름,위도,경도, 출발지가 없으면 /link/to/이름,위도,경도)
// 링크를 누를 때만 장소 좌표와 출발 위치가 카카오로 전달된다.
function kakaoRouteUrl(poi, walk) {
  const lat = Number(poi.latitude), lng = Number(poi.longitude);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return '';
  const clean = t => encodeURIComponent(String(t || '장소').replace(/[,/\\]/g, ' ').trim() || '장소');
  const dest = `${clean(poi.name)},${lat.toFixed(6)},${lng.toFixed(6)}`;
  if (!state.departure) return `https://map.kakao.com/link/to/${dest}`;
  const origin = `${encodeURIComponent('출발 위치')},${state.departure.lat.toFixed(6)},${state.departure.lng.toFixed(6)}`;
  return `https://map.kakao.com/link/by/${walk ? 'walk' : 'traffic'}/${origin}/${dest}`;
}

function kakaoRouteLink(poi, walk) {
  const url = kakaoRouteUrl(poi, walk);
  return url ? `<a class="kakao-route" href="${url}" target="_blank" rel="noopener noreferrer">카카오맵 길찾기</a>` : '';
}

function stationName(station) {
  return typeof station === 'string' ? station : (station?.name || '역 정보 없음');
}

function formatTrainTime(time) {
  if (!time) return '시간 정보 없음';
  const [h, m] = String(time).split(':');
  return Number(h) >= 24 ? `익일 ${String(Number(h) - 24).padStart(2, '0')}:${m}` : String(time);
}

// ─────────────────────────────────────────────
// 결과 목록: 구간 묶음(승차역 -> 하차역) > 카테고리 > 장소 (D-028)
// 순위는 장소가 아니라 구간의 속성이다. 구간 묶음 맨 위의 막대에 한 번만 보이고 장소 행에는 붙이지 않는다.
// ─────────────────────────────────────────────
const placeKey = p => String(p?.id ?? `${p?.name}|${p?.address}`);

function windowHours() {
  const r = state.chipRange || { start: state.startHour, end: state.endHour };
  return Array.from({ length: r.end - r.start + 1 }, (_, i) => r.start + i);
}

// 카테고리 필터를 적용한 구간 묶음 목록(장소가 없어진 묶음은 뺀다)
function visibleGroups() {
  return (state.results || [])
    .map(g => ({ ...g, categories: g.categories.filter(c => state.selectedCategory === 'all' || c.category === state.selectedCategory) }))
    .filter(g => g.categories.length);
}

function groupTitle(g) {
  return g.kind === 'walk' ? '걸어서' : `${stationName(g.boarding_station)}역 → ${stationName(g.alighting_station)}역 · ${g.stops}구간`;
}

// 장소 + 묶음 정보를 지도(showPlaceRoute)와 분석 탭이 쓰는 한 항목으로 합친다
function itemFor(g, place) {
  return { ...place, groupId: g.id, no_train: g.kind === 'walk', boarding_station: g.boarding_station || state.lastMeta?.boarding_station || null, alighting_station: g.alighting_station || null, hour_ranks: g.hour_ranks || [], rank_n: g.rank_n || 0 };
}

// 목록 안의 막대 자리: 떠 있는 창 모드면 한 줄 요약만 둔다(막대 그리기는 chartHtml 하나를 같이 쓴다).
function inlineChartHtml(g) {
  return state.floatMode ? '' : chartHtml(g);
}

// 구간 묶음의 시간대 순위 막대. 높이는 순서뿐이며 낮을수록 한산하다. 고른 시간의 출발 열차만 시각순으로 보여 준다.
function chartHtml(g) {
  if (g.kind === 'walk') return '<p class="rg-note">걸어서 가는 장소예요. 열차를 타지 않아 시간대 순위가 없습니다.</p>';
  const hours = windowHours(), byHour = new Map(g.hour_ranks.map(c => [c.hour, c])), span = Math.max(1, g.rank_n - 1);
  const sel = state.groupHours[g.id] ?? null, cur = byHour.get(sel);
  const cols = hours.map(h => {
    const c = byHour.get(h);
    if (!c) return `<div class="col empty" role="img" aria-label="${h}시 열차 없음"><span class="bar"></span><span class="h">${h}</span><span class="v">–</span></div>`;
    const frac = (c.rank - 1) / span, n = Math.min(5, 1 + Math.floor(frac * 4.999)), on = sel === h;
    const label = `${h}시, ${g.rank_n}개 시간대 중 ${c.rank}번째로 한산`;
    return `<button type="button" class="col${on ? ' sel' : ''}" data-hour="${h}" data-gid="${escapeHtml(g.id)}" aria-pressed="${on}" aria-label="${label}${on ? ', 선택됨' : ''}" title="${label}"><span class="bar" style="height:${8 + Math.round(frac * 28)}px;background:var(--q${n})"></span><span class="h">${h}</span><span class="v">${c.rank}</span></button>`;
  }).join('');
  const trains = cur ? `<div class="train-list"><div class="train-group"><strong>${sel}시 · ${g.rank_n}개 시간대 중 ${cur.rank}번째로 한산</strong> <span>${cur.trains.map(x => escapeHtml(formatTrainTime(x.departure_time))).join(', ')}</span></div></div>` : '<p class="rg-note">시간을 누르면 그 시간대에 승차역에서 출발하는 열차를 볼 수 있어요.</p>';
  return `<div class="rg-bars"><div class="cols" style="--n:${hours.length}">${cols}</div></div>${trains}
    <p class="rg-note">막대 높이는 순서를 나타내며 사람 수가 아닙니다. 낮은 막대(1번째)가 가장 한산하며, 순위 차이가 2 이하인 시간대는 같은 수준으로 봅니다.</p>`;
}

function placeRow(g, place) {
  const p = place.poi || {}, walk = g.kind === 'walk';
  const wa = place.walk_access_minutes, we = place.walk_egress_minutes, wt = place.walk_total_minutes;
  const walkLine = typeof wt !== 'number' ? ''
    : walk ? `걸어서 약 ${wt}분 (추정)` : `걷기 ${wa}분 + ${we}분 = ${wt}분 (추정)`;
  const advice = (!walk && typeof place.distance_km === 'number' && typeof place.walking_distance_km === 'number' && place.distance_km < place.walking_distance_km * 0.85)
    ? `<div class="walk-advice">걸어서 바로 가는 편이 더 가까울 수 있어요 (직선 약 ${Math.round(place.distance_km * 1000)}m)</div>` : '';
  const key = placeKey(p), on = state.selectedItem && state.selectedItem.groupId === g.id && placeKey(state.selectedItem.poi) === key;
  return `<div class="place-row${on ? ' selected' : ''}" role="button" tabindex="0" data-gid="${escapeHtml(g.id)}" data-pkey="${escapeHtml(key)}">
      <div class="name">${catIcon(p.facility_type)}<span class="name-text">${escapeHtml(p.name)}</span></div>
      <div class="meta"><span class="rt">직선 ${typeof place.distance_km === 'number' ? place.distance_km.toFixed(1) : '–'}km</span><span class="rt">${ICON.walk}${walkLine}</span></div>
      ${advice}
      <div class="addr">${escapeHtml(p.address || '주소 정보 없음')}</div>
      <div class="row-foot">${kakaoRouteLink(p, walk)}</div>
    </div>`;
}

function findItem(gid, pkey) {
  return state.listed.find(r => r.groupId === gid && placeKey(r.poi) === pkey) || null;
}

// 장소를 고른다: 지도에 핀·경로를 그리고 목록의 행을 표시한다. fromMap 이면 구역을 펼치고 행으로 스크롤한다.
function selectPlace(item, fromMap = false, keepCamera = false) {
  document.querySelectorAll('#resultsCards .place-row.selected').forEach(r => r.classList.remove('selected'));
  const row = [...document.querySelectorAll('#resultsCards .place-row')].find(r => r.dataset.gid === item.groupId && r.dataset.pkey === placeKey(item.poi));
  if (row) {
    row.classList.add('selected');
    if (fromMap) {
      const sec = row.closest('details');
      if (sec && !sec.open) sec.open = true;
      row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }
  state.floatGid = item.groupId;
  renderFloat();
  showPlaceRoute(item, true, !keepCamera);
}

// 선택한 장소가 현재 보이는 결과에 없으면 선택·경로·분석 프로필을 모두 비운다(이전 장소의 순위가 남지 않게).
function clearSelectionIfMissing(items) {
  if (state.floatGid && !items.some(r => r.groupId === state.floatGid)) { state.floatGid = null; renderFloat(); }
  const sel = state.selectedItem;
  if (sel && !items.some(r => r.groupId === sel.groupId && placeKey(r.poi) === placeKey(sel.poi))) {
    state.selectedItem = null;
    clearRoute();
    window.Analysis?.setSelected(null);
  }
}

function announceHour(gid, hour) {
  const g = (state.results || []).find(x => x.id === gid), c = g?.hour_ranks?.find(x => x.hour === hour);
  const live = document.getElementById('viewStatus');
  if (live) live.textContent = c ? `${groupTitle(g)} ${hour}시: ${g.rank_n}개 시간대 중 ${c.rank}번째로 한산, 승차역 출발 열차 ${c.trains.map(x => formatTrainTime(x.departure_time)).join(', ')}` : '';
}

function renderRecommendations(payload) {
  state.lastMeta = payload.meta || state.lastMeta;
  const groups = visibleGroups();
  state.listed = groups.flatMap(g => g.categories.flatMap(c => c.places.map(p => itemFor(g, p))));
  clearSelectionIfMissing(state.listed);
  renderPoiMarkers(state.listed);
  const alive = new Set(groups.map(g => g.id));
  Object.keys(state.groupHours).forEach(id => { if (!alive.has(id)) delete state.groupHours[id]; });
  if (!state.open) state.open = state.selectedCategory !== 'all'
    ? new Set(groups.flatMap(g => g.categories.map(c => `${g.id}|${c.category}`)))
    : new Set((groups[0]?.categories || []).map(c => `${groups[0].id}|${c.category}`));

  document.getElementById('resultsMeta').textContent = `${state.date} 운행일 · ${state.startHour}~${state.endHour}시 · 직선거리 순`;
  const cards = document.getElementById('resultsCards');
  if (!groups.length) {
    cards.innerHTML = '<p class="empty-state" role="status">조건에 맞는 장소가 없습니다. 걷는 시간 한도나 지하철 이동 구간 조건을 바꿔 보세요.</p>';
  } else {
    cards.innerHTML = groups.map(g => {
      const walkG = g.kind === 'walk', ico = walkG ? ICON.walk : ICON.train;
      const label = walkG ? '걸어서' : `${stationName(g.boarding_station)}역 → ${stationName(g.alighting_station)}역`;
      const badge = walkG ? '' : `<span class="rg-badge">${g.stops}구간</span>`;
      return `<section class="route-group${walkG ? ' is-walk' : ''}" aria-label="${escapeHtml(groupTitle(g))}">
      <h3 class="rg-title">${state.floatMode ? `<button type="button" class="rg-sel" data-gid="${escapeHtml(g.id)}" aria-pressed="${state.floatGid === g.id}" aria-label="${escapeHtml(groupTitle(g))}, 누르면 시간대 순위 창이 열립니다">${ico}<span class="rg-label">${escapeHtml(label)}</span>${badge}</button>` : `${ico}<span class="rg-label">${escapeHtml(label)}</span>${badge}`}</h3>
      <div class="rg-chart" data-chart="${escapeHtml(g.id)}">${inlineChartHtml(g)}</div>
      <div class="rg-places">${g.categories.map(c => { const key = `${g.id}|${c.category}`; return `<details class="cat-sec" data-key="${escapeHtml(key)}"${state.open.has(key) ? ' open' : ''}><summary><span class="cs-name">${escapeHtml(catLabel(c.category))}</span><span class="cs-count">(${c.places.length}곳)</span></summary>${c.places.map(p => placeRow(g, p)).join('')}</details>`; }).join('')}</div>
    </section>`; }).join('');
    cards.querySelectorAll('details.cat-sec').forEach(d => d.addEventListener('toggle', () => { d.open ? state.open.add(d.dataset.key) : state.open.delete(d.dataset.key); }));
    const notes = payload.meta?.limitations;
    if (Array.isArray(notes) && notes.length) {
      const note = document.createElement('details');
      note.className = 'limits-note';
      note.innerHTML = `<summary>예측의 한계</summary><p>${escapeHtml(notes.join(' · '))}</p>`;
      cards.prepend(note);
    }
  }
  window.Analysis?.refreshHeatmap();
  window.Analysis?.refreshProfile();
  renderFloat();
}

// 시간 막대 클릭(목록 안 막대·떠 있는 창 공통): 그 묶음의 시간을 고르고 막대·창을 다시 그린다.
function pickHour(col) {
  const gid = col.dataset.gid, hour = Number(col.dataset.hour), g = (state.results || []).find(x => x.id === gid);
  if (!g) return;
  state.groupHours[gid] = state.groupHours[gid] === hour ? null : hour;
  const box = [...document.querySelectorAll('#resultsCards [data-chart]')].find(b => b.dataset.chart === gid);
  if (box) box.innerHTML = inlineChartHtml(g);
  const body = document.querySelector('#rankFloat .rf-body');
  if (body && state.floatGid === gid) body.innerHTML = chartHtml(g);
  announceHour(gid, state.groupHours[gid]);
  window.Analysis?.refreshProfile();
  [...document.querySelectorAll('.col[data-hour]')].find(b => b.dataset.gid === gid && Number(b.dataset.hour) === hour && b.isConnected)?.focus();
}

// 떠 있는 순위 창(대체 표시). 내용은 chartHtml 을 그대로 쓴다. 제목줄을 끌어 옮기고 ×·Esc 로 닫는다.
function clampFloat(box, left, top) {
  return { left: Math.max(4, Math.min(window.innerWidth - box.offsetWidth - 4, left)), top: Math.max(4, Math.min(window.innerHeight - box.offsetHeight - 4, top)) };
}
function placeFloat(box, left, top) {
  const p = clampFloat(box, left, top);
  box.style.left = `${p.left}px`;
  box.style.top = `${p.top}px`;
  state.floatPos = p;
}
function renderFloat() {
  const box = document.getElementById('rankFloat');
  if (!box) return;
  const g = state.floatMode && state.floatGid ? (state.results || []).find(x => x.id === state.floatGid) : null;
  const onRecommend = document.getElementById('tab-recommend')?.classList.contains('active');
  if (!g || !onRecommend) { box.hidden = true; box.setAttribute('aria-hidden', 'true'); box.innerHTML = ''; return; }
  box.removeAttribute('aria-hidden');
  const wasHidden = box.hidden;
  box.hidden = false;
  box.setAttribute('aria-label', `시간대 순위: ${groupTitle(g)}`);
  box.innerHTML = `<div class="rf-bar" tabindex="0" aria-label="${escapeHtml(groupTitle(g))}. 제목줄을 끌어 옮길 수 있고 방향키로도 움직입니다. Esc로 닫습니다."><strong>${escapeHtml(groupTitle(g))}</strong><button type="button" class="rf-close" aria-label="순위 창 닫기">×</button></div><div class="rf-body">${chartHtml(g)}</div>`;
  if (state.floatPos) placeFloat(box, state.floatPos.left, state.floatPos.top);
  else {
    const a = document.querySelector('.map-area')?.getBoundingClientRect();
    placeFloat(box, a ? a.right - box.offsetWidth - 12 : window.innerWidth, a ? a.bottom - box.offsetHeight - 12 : window.innerHeight);   // 처음에는 지도 영역 오른쪽 아래(검색 패널을 가리지 않는다)
  }
}
// 사용자가 ×/Esc 로 닫는 경우: 체크를 끄고 저장한 뒤 목록의 순위 막대를 되살린다. (자동으로 숨길 때는 renderFloat 만 쓴다.)
function closeFloat() { setFloatMode(false); }
function setFloatMode(on) {
  state.floatMode = on;
  const toggle = document.getElementById('rankFloatToggle');
  if (toggle) toggle.checked = on;
  try { localStorage.setItem('rankFloat', on ? '1' : '0'); } catch (_) { /* 저장 실패는 현재 화면에만 적용 */ }
  state.floatGid = on ? (state.selectedItem?.groupId ?? null) : null;
  if (state.results.length) renderRecommendations({ meta: state.lastMeta }); else renderFloat();
}
function initFloat() {
  const box = document.getElementById('rankFloat'), toggle = document.getElementById('rankFloatToggle');
  if (!box || !toggle) return;
  try { state.floatMode = localStorage.getItem('rankFloat') === '1'; } catch (_) { /* 저장소를 못 쓰면 기본값(끔) */ }
  toggle.checked = state.floatMode;
  toggle.addEventListener('change', () => setFloatMode(toggle.checked));
  let drag = null;
  box.addEventListener('pointerdown', e => {
    const bar = e.target.closest('.rf-bar');
    if (!bar || e.button !== 0 || e.target.closest('button')) return;
    drag = { id: e.pointerId, x: e.clientX, y: e.clientY, left: box.offsetLeft, top: box.offsetTop };
    box.setPointerCapture(e.pointerId);
    box.classList.add('is-dragging');
    e.preventDefault();
  });
  box.addEventListener('pointermove', e => { if (drag && drag.id === e.pointerId) placeFloat(box, drag.left + e.clientX - drag.x, drag.top + e.clientY - drag.y); });
  const end = e => { if (drag && drag.id === e.pointerId) { drag = null; box.classList.remove('is-dragging'); } };
  box.addEventListener('pointerup', end);
  box.addEventListener('pointercancel', end);
  box.addEventListener('click', e => {
    if (e.target.closest('.rf-close')) { closeFloat(); return; }
    const col = e.target.closest('.col[data-hour]');
    if (col) pickHour(col);
  });
  box.addEventListener('keydown', e => {
    const d = e.target.classList?.contains('rf-bar') && { ArrowLeft: [-12, 0], ArrowRight: [12, 0], ArrowUp: [0, -12], ArrowDown: [0, 12] }[e.key];
    if (d) { e.preventDefault(); placeFloat(box, box.offsetLeft + d[0], box.offsetTop + d[1]); }
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !box.hidden) closeFloat(); });
  window.addEventListener('resize', () => { if (!box.hidden) placeFloat(box, box.offsetLeft, box.offsetTop); });
}

// 목록 클릭(위임): 시간 막대는 그 묶음의 시간을 고르고, 장소 행은 장소를 고른다.
function initResultsList() {
  const cards = document.getElementById('resultsCards');
  cards.addEventListener('click', ev => {
    const col = ev.target.closest('.col[data-hour]');
    if (col) { pickHour(col); return; }
    const sel = ev.target.closest('.rg-sel');
    if (sel) { state.floatGid = sel.dataset.gid; renderFloat(); cards.querySelectorAll('.rg-sel').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.gid === state.floatGid))); document.querySelector('#rankFloat .rf-bar')?.focus(); return; }
    if (ev.target.closest('.kakao-route')) return;
    const row = ev.target.closest('.place-row');
    const item = row && findItem(row.dataset.gid, row.dataset.pkey);
    if (item) selectPlace(item);
  });
  cards.addEventListener('keydown', ev => {
    const row = ev.target.closest?.('.place-row');
    if (row && ev.target === row && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); row.click(); }
  });
}

function setUpdating(on) {
  document.getElementById('resultsSection')?.classList.toggle('is-updating', on);
  const badge = document.getElementById('mapUpdating');
  if (badge) badge.hidden = !on;
  if (on) {
    state.routePolylines.forEach(p => { try { if (typeof p.setOptions === 'function') p.setOptions({ strokeOpacity: 0.3 }); } catch (_) { /* 무시 */ } });
  }
}

function setStale(on) {
  document.getElementById('resultsSection')?.classList.toggle('is-stale', on);
}

function showUpdateNote(message, retry = false) {
  const note = document.getElementById('updateNote');
  if (!note) return;
  if (!message) { note.hidden = true; note.textContent = ''; return; }
  note.textContent = message + ' ';
  if (retry) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'update-retry';
    btn.textContent = '다시 시도';
    btn.addEventListener('click', () => requestRecommendations());
    note.appendChild(btn);
  }
  note.hidden = false;
}

async function requestRecommendations(opts = {}) {
  const auto = opts.auto === true;
  clearTimeout(state.researchTimer);
  state.researchTimer = null;
  const prev = auto && state.selectedItem ? { gid: state.selectedItem.groupId, key: placeKey(state.selectedItem.poi) } : null;
  if (!state.departure) {
    document.getElementById('resultsCards').innerHTML = '<p class="empty-state">먼저 위의 출발지 선택을 눌러 지도 선택을 켜거나, 역 목록에서 출발지를 골라 주세요.</p>';
    renderMetroSchematic();
    return;
  }
  state.recommendationController?.abort();
  const controller = new AbortController();
  state.recommendationController = controller;
  const id = ++state.recommendationRequestId;
  const button = document.getElementById('searchBtn');
  const startedAt = Date.now();
  let tick = null;
  setStale(false);
  showUpdateNote('');
  if (auto) {
    setUpdating(true);   // 이전 결과는 흐리게 두고 새 결과가 오면 바꾼다
  } else {
    setUpdating(false);
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.innerHTML = '<span class="spinner" aria-hidden="true"></span><span class="go-label">계산 중…</span>';
    const cardsBox = document.getElementById('resultsCards');
    document.getElementById('resultsMeta').textContent = '추천 계산 중';
    cardsBox.innerHTML = `<div class="loading-status" role="status"><span id="loadingElapsed">계산 중 · 0초</span></div><div class="skeleton-row" aria-hidden="true">${'<div class="skeleton-card"><i></i><i></i><i></i><i></i></div>'.repeat(4)}</div>`;
    tick = setInterval(() => {
      const el = document.getElementById('loadingElapsed');
      if (el) el.textContent = `계산 중 · ${Math.floor((Date.now() - startedAt) / 1000)}초`;
    }, 1000);
  }
  let timedOut = false;
  const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 90000);

  try {
    const request = {
        date: state.date,
        start_hour: state.startHour,
        end_hour: state.endHour,
        category: state.selectedCategory,
        origin: state.departure,
        ...(Number(document.getElementById('minStops').value) > 0 ? { min_stops: Number(document.getElementById('minStops').value) } : {}),
        ...(Number(document.getElementById('maxStops').value) < STATIONS.length - 1 ? { max_stops: Number(document.getElementById('maxStops').value) } : {}),
        ...(document.getElementById('maxWalk').value !== '' ? { max_walk_minutes: Number(document.getElementById('maxWalk').value) } : {}),
    };
    const payload = await staticEngine().recommend(request, { signal: controller.signal });
    if (id !== state.recommendationRequestId) return;
    controller.signal.throwIfAborted();
    if (!Array.isArray(payload?.groups)) throw new Error('추천 결과를 읽을 수 없습니다. 페이지를 새로고침한 뒤 다시 시도해 주세요.');

    setUpdating(false);
    if (!auto) { state.groupHours = {}; state.open = null; }
    state.results = payload.groups;
    state.lastMeta = payload.meta || state.lastMeta;
    state.chipRange = { start: state.startHour, end: state.endHour };
    renderRecommendations(payload);
    if (!auto) document.getElementById('resultsSection').scrollIntoView({ behavior: 'smooth' });
    if (prev) {
      // 출발지 변경 후 재검색: 같은 구간 묶음에 같은 장소가 있으면 새 결과로 경로를 다시 그린다(카메라는 움직이지 않음). 없으면 선택은 이미 해제되어 있다.
      const item = findItem(prev.gid, prev.key);
      if (item) { selectPlace(item, false, true); } else { showUpdateNote('선택했던 장소가 새 출발지 기준 결과에 없어 선택을 해제했습니다.'); }
    }
  } catch (error) {
    if (id !== state.recommendationRequestId) return;
    const message = error.name === 'AbortError'
      ? (timedOut ? '계산이 오래 걸려 중단했습니다. 잠시 후 다시 시도해 주세요.' : '계산을 중단했습니다. 다시 찾기를 눌러 주세요.')
      : error.message === 'Failed to fetch' ? '추천에 필요한 자료를 불러오지 못했습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요.'
      : error.message || '추천을 계산하지 못했습니다. 잠시 후 다시 시도해 주세요.';
    if (auto) {
      // 이전 결과는 그대로 두되(흐림 해제 후 '이전 결과' 표시) 오류와 재시도 버튼을 보인다
      setUpdating(false);
      setStale(true);
      showUpdateNote(`${message} 아래는 이전 조건의 결과입니다.`, true);
      return;
    }
    renderPoiMarkers([]);
    document.getElementById('resultsMeta').textContent = '추천을 불러오지 못했습니다';
    document.getElementById('resultsCards').innerHTML = `<p class="empty-state is-error" role="alert">${escapeHtml(message)}<br>잠시 후 [찾기]를 눌러 다시 시도해 주세요.</p>`;
    document.getElementById('predictionAnalysis').textContent = '예측 자료를 불러오지 못했습니다.';
  } finally {
    clearTimeout(timeout);
    clearInterval(tick);
    if (id === state.recommendationRequestId) state.recommendationController = null;
    if (id === state.recommendationRequestId && !auto) {
      button.disabled = false;
      button.removeAttribute('aria-busy');
      setSearchLabel('찾기');
    }
  }
}

// 출발지 문장 칸: 눌러서 지도 안내와 역 목록을 연다 (Esc/바깥 클릭으로 닫힘)
function initQueryBar() {
  const slot = document.getElementById('slotOrigin'), pop = document.getElementById('originPop'), sel = document.getElementById('originStation');
  const pickButton = document.getElementById('mapPickButton'), pickCancel = document.getElementById('mapPickCancel');
  if (!slot || !pop || !sel) return;
  sel.innerHTML += STATIONS.map(s => `<option value="${s.idx}">${escapeHtml(s.name)}역</option>`).join('');
  const close = (focus = false) => { pop.hidden = true; slot.setAttribute('aria-expanded', 'false'); if (focus) slot.focus(); };
  slot.addEventListener('click', () => {
    if (state.mapPickMode) setMapPickMode(false);
    const open = pop.hidden;
    pop.hidden = !open;
    slot.setAttribute('aria-expanded', String(open));
    if (open) pickButton?.focus();
  });
  pickButton?.addEventListener('click', () => {
    if (!state.map) {
      setMapPickMode(false);
      renderMetroSchematic();
      showUpdateNote('지도를 불러오지 못했습니다. 역을 출발지로 골라 추천을 이용할 수 있습니다.');
      sel.focus();
      return;
    }
    setMapPickMode(true);
    close();
    pickCancel?.focus();
  });
  pickCancel?.addEventListener('click', () => {
    setMapPickMode(false);
    slot.focus();
  });
  sel.addEventListener('change', () => {
    const st = STATIONS.find(x => String(x.idx) === sel.value);
    if (!st) return;
    setDeparture(st.lat, st.lng, `${st.name}역`);
    state.map?.setCenter(new MapView.LatLng(st.lat, st.lng));
    close(true);
  });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (state.mapPickMode) { setMapPickMode(false); slot.focus(); }
    else if (!pop.hidden) close(true);
  });
  document.addEventListener('click', e => { if (!pop.hidden && !e.target.closest('.slot-box')) close(); });
}

function setMapPickMode(active) {
  state.mapPickMode = !!active;
  const hint = document.getElementById('mapPickHint');
  const button = document.getElementById('mapPickButton');
  if (hint) hint.hidden = !state.mapPickMode;
  button?.setAttribute('aria-pressed', String(state.mapPickMode));
  document.querySelector('.map-area')?.classList.toggle('is-picking', state.mapPickMode);
}

// 이동 구간 드롭다운: 이상 0..N(0=제한 없음), 이하 1..N(N=제한 없음). 서로 모순되는 칸은 끄고 값은 바꾸지 않는다.
function syncStopsOptions() {
  const N = STATIONS.length - 1, lo = document.getElementById('minStops'), hi = document.getElementById('maxStops');
  if (Number(lo.value) > Number(hi.value)) { lo.value = '0'; hi.value = String(N); }   // 어긋난 복원 값은 기본값으로
  [...lo.options].forEach(o => { o.disabled = Number(o.value) > Number(hi.value); });
  [...hi.options].forEach(o => { o.disabled = Number(o.value) < Number(lo.value); });
}

function initStopsSelects() {
  const N = STATIONS.length - 1, lo = document.getElementById('minStops'), hi = document.getElementById('maxStops');
  lo.innerHTML = Array.from({ length: N + 1 }, (_, n) => `<option value="${n}">${n === 0 ? '제한 없음' : `${n}개 이상`}</option>`).join('');
  hi.innerHTML = Array.from({ length: N }, (_, i) => `<option value="${i + 1}">${i + 1 === N ? '제한 없음' : `${i + 1}개 이하`}</option>`).join('');
  lo.value = '0'; hi.value = String(N);
  [lo, hi].forEach(el => el.addEventListener('change', syncStopsOptions));
  syncStopsOptions();
}

function initSearchBtn() {
  initStopsSelects();
  ['maxWalk', 'minStops', 'maxStops'].forEach(id => document.getElementById(id).addEventListener('change', () => {
    cancelPendingRecommendation();
    if (state.results.length > 0) {
      setSearchLabel('다시 찾기');
      document.getElementById('predictionAnalysis').textContent = '검색 조건이 변경되었습니다. [다시 찾기]를 누르면 다시 계산합니다.';
    }
  }));
  setSearchLabel('찾기');
  document.getElementById('searchBtn').addEventListener('click', () => requestRecommendations());
}

document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initRecommendationControls();
  initDateInput();
  initFilters();
  initResultsList();
  initFloat();
  initQueryBar();
  initSearchBtn();
  loadPois();
  loadMetroLineGeometry();
  renderMetroSchematic();
  setTimeout(tryInitMap, 400);
});
