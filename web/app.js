'use strict';

// 대전 1호선 22개 역 VWorld 정밀 보정 좌표 (판암 0 ~ 반석 21)
const STATIONS = [
  { name: '판암',         idx: 0,  lat: 36.31696046, lng: 127.45837805 },
  { name: '신흥',         idx: 1,  lat: 36.31967849, lng: 127.44869127 },
  { name: '대동',         idx: 2,  lat: 36.32950425, lng: 127.44290144 },
  { name: '대전',         idx: 3,  lat: 36.33222770, lng: 127.43442886 },
  { name: '중앙로',       idx: 4,  lat: 36.32859315, lng: 127.42554303 },
  { name: '중구청',       idx: 5,  lat: 36.32478871, lng: 127.41954949 },
  { name: '서대전네거리', idx: 6,  lat: 36.32240766, lng: 127.41256249 },
  { name: '오룡',         idx: 7,  lat: 36.32856377, lng: 127.40505467 },
  { name: '용문',         idx: 8,  lat: 36.33825237, lng: 127.39330512 },
  { name: '탄방',         idx: 9,  lat: 36.34560284, lng: 127.38454168 },
  { name: '시청',         idx: 10, lat: 36.35158114, lng: 127.38672540 },
  { name: '정부청사',     idx: 11, lat: 36.35757789, lng: 127.38123378 },
  { name: '갈마',         idx: 12, lat: 36.35764061, lng: 127.37256862 },
  { name: '월평',         idx: 13, lat: 36.35825770, lng: 127.36453627 },
  { name: '갑천',         idx: 14, lat: 36.35452027, lng: 127.35440346 },
  { name: '유성온천',     idx: 15, lat: 36.35388461, lng: 127.34153051 },
  { name: '구암',         idx: 16, lat: 36.35664509, lng: 127.33061899 },
  { name: '현충원',       idx: 17, lat: 36.35919845, lng: 127.32132942 },
  { name: '월드컵경기장', idx: 18, lat: 36.36701090, lng: 127.31785476 },
  { name: '노은',         idx: 19, lat: 36.37410659, lng: 127.31788909 },
  { name: '지족',         idx: 20, lat: 36.38412150, lng: 127.31951307 },
  { name: '반석',         idx: 21, lat: 36.39189559, lng: 127.31440279 },
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
  pois: [],
  weatherRequestId: 0,
  startHour: 5,
  endHour: 24,
  quietWeight: 0.5,
  recommendationRequestId: 0,
  recommendationController: null,
  weather: null,
  nextWeather: null,
  results: [],
  lastMeta: null,
  selectedItem: null,
};

const API_BASE = window.RECOMMENDATION_API_BASE || 'http://127.0.0.1:8000';

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
const catEmoji = c => ({ library: '📚', park: '🌳', bookstore: '📖' })[c] || '📍';
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
  }));
}

function tryInitMap(retries = 20) {
  if (typeof kakao !== 'undefined' && kakao.maps) kakao.maps.load(initMap);
  else if (retries > 0) setTimeout(() => tryInitMap(retries - 1), 300);
  else { renderMetroSchematic(); }
}

function initMap() {
  document.getElementById('mapFallback').style.display = 'none';
  state.map = new kakao.maps.Map(document.getElementById('kakaoMap'), { center: new kakao.maps.LatLng(36.3515, 127.3867), level: 6 });
  state.map.addControl(new kakao.maps.MapTypeControl(), kakao.maps.ControlPosition.TOPRIGHT);
  state.map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT);

  STATIONS.forEach(s => {
    const node = document.createElement('div');
    node.className = 'station-dot';
    node.title = `${s.name}역 (클릭하여 출발지로 지정)`;
    node.addEventListener('click', e => {
      e.stopPropagation();
      setDeparture(s.lat, s.lng, `${s.name}역`);
    });
    new kakao.maps.CustomOverlay({
      position: new kakao.maps.LatLng(s.lat, s.lng),
      content: node,
      yAnchor: 0.5,
      xAnchor: 0.5,
      zIndex: 4,
    }).setMap(state.map);
  });

  kakao.maps.event.addListener(state.map, 'click', e => {
    setDeparture(e.latLng.getLat(), e.latLng.getLng());
  });

  renderPoiMarkers();
}

function setDeparture(lat, lng, label = null) {
  state.departure = { lat, lng };

  if (state.map) {
    if (state.departureMarker) state.departureMarker.setMap(null);
    const node = document.createElement('div');
    node.className = 'departure-dot';
    node.title = '선택한 출발지';
    // xAnchor: 0.5, yAnchor: 0.5로 정확히 클릭 커서 위치에 중심 배치
    state.departureMarker = new kakao.maps.CustomOverlay({
      position: new kakao.maps.LatLng(lat, lng),
      content: node,
      xAnchor: 0.5,
      yAnchor: 0.5,
      zIndex: 10,
    });
    state.departureMarker.setMap(state.map);
  }

  document.getElementById('locationBox').innerHTML = `<div class="loc-addr">📍 ${escapeHtml(label || '출발지 지정됨')}</div><div class="loc-coords">위도 ${lat.toFixed(5)} · 경도 ${lng.toFixed(5)}</div>`;
  const near = STATIONS.map(s => ({ ...s, km: distKm(lat, lng, s.lat, s.lng) })).sort((a, b) => a.km - b.km).slice(0, 5);
  document.getElementById('stationDistList').innerHTML = near.map(s => `<div class="stn-row"><span class="stn-row-name">${escapeHtml(s.name)}역</span><span class="stn-row-dist">직선거리 ${(s.km * 1000).toFixed(0)}m</span></div>`).join('');

  // 이미 계산된 추천 결과가 있으면 재추천 필요 알림, 없으면 미리보기 갱신
  // 💡 사용자가 지도를 클릭해 출발지를 찍었을 때는 지도 시점(줌/중심)이 제멋대로 움직이지 않도록 adjustBounds를 false로 유지합니다.
  if (state.results && state.results.length > 0) {
    document.getElementById('searchBtn').textContent = '🔍 새 출발지로 추천 다시 찾기';
    document.getElementById('predictionAnalysis').textContent = '출발지가 변경되었습니다. [추천 다시 찾기]를 누르면 새 출발지 기준으로 열차 일정을 계산합니다.';
    if (state.selectedItem) {
      showPlaceRoute(state.selectedItem, true, false);
    }
  } else {
    renderResults(computeRecommendations());
    if (state.selectedItem) {
      showPlaceRoute(state.selectedItem, false, false);
    }
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

function showPlaceRoute(item, isRecommendation = false, adjustBounds = true) {
  if (!state.map) return;
  clearRoute();
  state.selectedItem = item;

  const poi = isRecommendation ? (item.poi || {}) : item;
  const poiLat = Number(poi.latitude);
  const poiLng = Number(poi.longitude);
  if (!Number.isFinite(poiLat) || !Number.isFinite(poiLng)) return;

  const poiPos = new kakao.maps.LatLng(poiLat, poiLng);
  const bounds = new kakao.maps.LatLngBounds();
  bounds.extend(poiPos);

  // 💡 1. 출발지 및 목적지 기준 가장 가까운 역을 항상 현재 위치 기준으로 정확히 결정
  // (이전 검색 결과의 '예전 역'에 묶여 경로가 엉뚱한 곳으로 이어지는 문제 해결)
  const currentDepartureStation = state.departure ? nearestStation(state.departure).station : null;
  const currentPoiStation = nearestStation(poi).station;

  let bStation = currentDepartureStation || (item.boarding_station ? (STATIONS.find(s => s.name === item.boarding_station.name) || item.boarding_station) : null);
  let aStation = item.alighting_station ? (STATIONS.find(s => s.name === item.alighting_station.name) || item.alighting_station) : currentPoiStation;

  // 💡 2. 도보 직행 판정:
  // - 같은 역 생활권인 경우
  // - 또는 출발지~목적지 직선거리가 900m 이내로 도보 생활권인 경우
  // - 또는 지하철역까지 걸어가는 거리 합이 출발지->목적지 직행 거리보다 멀어 지하철 탑승이 비합리적인 경우
  const directDist = state.departure ? distKm(state.departure.lat, state.departure.lng, poiLat, poiLng) : 999;
  const walkToBoardDist = (state.departure && bStation) ? distKm(state.departure.lat, state.departure.lng, bStation.lat, bStation.lng) : 0;
  const walkFromAlightDist = aStation ? distKm(aStation.lat, aStation.lng, poiLat, poiLng) : 0;

  const isDirectWalk = (bStation && aStation && bStation.name === aStation.name) ||
                       (directDist <= 0.9) ||
                       (directDist <= (walkToBoardDist + walkFromAlightDist) * 0.85);

  if (state.departure) {
    const depPos = new kakao.maps.LatLng(state.departure.lat, state.departure.lng);
    bounds.extend(depPos);

    if (isDirectWalk || !bStation || bStation.name === aStation.name) {
      // 🚶 지하철 불필요: 출발지 → 목적지 직행 도보 점선
      const line = new kakao.maps.Polyline({
        map: state.map,
        path: [depPos, poiPos],
        strokeWeight: 4,
        strokeColor: '#A07845',
        strokeOpacity: 0.85,
        strokeStyle: 'shortdash',
      });
      state.routePolylines.push(line);
    } else {
      // 🚇 지하철 이용 경로:
      // [1] 출발지 → 탑승역 보행 점선
      const bPos = new kakao.maps.LatLng(bStation.lat, bStation.lng);
      bounds.extend(bPos);
      const walkToBoardLine = new kakao.maps.Polyline({
        map: state.map,
        path: [depPos, bPos],
        strokeWeight: 4,
        strokeColor: '#A07845',
        strokeOpacity: 0.85,
        strokeStyle: 'shortdash',
      });
      state.routePolylines.push(walkToBoardLine);

      // 탑승역 뱃지
      const bBadge = document.createElement('div');
      bBadge.className = 'route-station-badge';
      bBadge.textContent = `🚇 승차: ${bStation.name}역`;
      const bOverlay = new kakao.maps.CustomOverlay({
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
        const metroPath = stationsAlong.map(s => new kakao.maps.LatLng(s.lat, s.lng));
        metroPath.forEach(pt => bounds.extend(pt));

        // 2-1. 흰색 테두리 밑선
        const metroUnderlay = new kakao.maps.Polyline({
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
        const metroLine = new kakao.maps.Polyline({
          map: state.map,
          path: metroPath,
          strokeWeight: 6,
          strokeColor: '#007448', // 대전 1호선 공식 노선색
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
          const overlay = new kakao.maps.CustomOverlay({
            position: new kakao.maps.LatLng(stn.lat, stn.lng),
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
      const aPos = new kakao.maps.LatLng(aStation.lat, aStation.lng);
      bounds.extend(aPos);

      const aBadge = document.createElement('div');
      aBadge.className = 'route-station-badge alight';
      aBadge.textContent = `🚶 하차: ${aStation.name}역`;
      const aOverlay = new kakao.maps.CustomOverlay({
        position: aPos,
        content: aBadge,
        yAnchor: 1.6,
        zIndex: 16,
      });
      aOverlay.setMap(state.map);
      state.routePolylines.push(aOverlay);

      const walkToPoiLine = new kakao.maps.Polyline({
        map: state.map,
        path: [aPos, poiPos],
        strokeWeight: 4,
        strokeColor: '#C47E4A',
        strokeOpacity: 0.85,
        strokeStyle: 'shortdash',
      });
      state.routePolylines.push(walkToPoiLine);
    }
  } else {
    // 출발지가 아직 없을 때: 목적지 및 인근 역 표시
    if (aStation) {
      const aPos = new kakao.maps.LatLng(aStation.lat, aStation.lng);
      bounds.extend(aPos);
      const line = new kakao.maps.Polyline({
        map: state.map,
        path: [aPos, poiPos],
        strokeWeight: 4,
        strokeColor: '#C47E4A',
        strokeOpacity: 0.85,
        strokeStyle: 'shortdash',
      });
      state.routePolylines.push(line);
    }
  }

  // 장소 팝업 카드 띄우기
  const content = document.createElement('div');
  content.className = 'poi-info-card';
  content.innerHTML = `
    <div class="poi-info-title">
      <span>${catEmoji(poi.facility_type)} ${escapeHtml(poi.name)}</span>
      <span style="font-size:11px;color:#888;">${catLabel(poi.facility_type)}</span>
    </div>
    <div class="poi-info-desc">${escapeHtml(poi.address || '주소 정보 없음')}</div>
    <div class="poi-info-route">
      ${isDirectWalk || !bStation || bStation.name === aStation.name
        ? `🚶 도보 직행 (약 ${(directDist * 1000).toFixed(0)}m · 지하철 불필요)`
        : `🚇 ${escapeHtml(bStation.name)}역 탑승 → ${escapeHtml(aStation.name)}역 하차`}
    </div>
  `;
  state.poiInfoOverlay = new kakao.maps.CustomOverlay({
    position: poiPos,
    content,
    yAnchor: 1.3,
    zIndex: 20,
  });
  state.poiInfoOverlay.setMap(state.map);

  // 카드나 마커를 직접 클릭했을 때만 지도 영역을 경로 전체가 한눈에 보이게 자동 조절
  if (adjustBounds) {
    state.map.setBounds(bounds);
  }
}

// ─────────────────────────────────────────────
// POI 데이터 및 날씨
// ─────────────────────────────────────────────
async function loadPois() {
  const cards = document.getElementById('resultsCards');
  cards.innerHTML = '<p class="empty-state">장소 데이터를 불러오는 중입니다.</p>';
  try {
    const response = await fetch('./data/pois.json');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!Array.isArray(data)) throw new Error('POI 데이터 형식이 배열이 아닙니다.');
    // 유효한 장소(도서관, 공원, 서점)만 필터링
    state.pois = data.filter(p => p.facility_type === 'library' || p.facility_type === 'park' || p.facility_type === 'bookstore');
    renderResults(computeRecommendations());
    renderPoiMarkers();
  } catch (error) {
    console.error('POI 데이터 로드 실패:', error);
    cards.innerHTML = '<p class="empty-state">장소 데이터를 불러오지 못했습니다. 웹 서버에서 페이지를 열고 다시 시도해 주세요.</p>';
    document.getElementById('resultsMeta').textContent = '데이터 로드 실패';
  }
}

function initDateInput() {
  const input = document.getElementById('dateInput');
  const today = new Date().toLocaleDateString('sv-SE');
  input.value = today;
  state.date = today;
  loadWeather(today);
  input.addEventListener('change', e => {
    if (!e.target.value) return;
    state.date = e.target.value;
    loadWeather(state.date);
    if (state.results.length > 0) {
      document.getElementById('searchBtn').textContent = '🔍 변경된 날짜로 추천 다시 찾기';
      document.getElementById('predictionAnalysis').textContent = '날짜가 변경되었습니다. [추천 다시 찾기]를 누르면 해당 날짜 예보와 시간표로 다시 계산합니다.';
    }
  });
}

async function loadWeather(date) {
  const box = document.getElementById('weatherBox'), id = ++state.weatherRequestId;
  state.weather = null;
  state.nextWeather = null;
  box.innerHTML = '<span class="placeholder-text">날씨를 불러오는 중입니다…</span>';
  if (!window.WeatherClient || typeof window.WeatherClient.fetchForDate !== 'function') {
    box.innerHTML = '<span class="placeholder-text">날씨 서비스를 사용할 수 없습니다.</span>';
    return;
  }
  const result = await window.WeatherClient.fetchForDate(date);
  if (id !== state.weatherRequestId) return;
  if (!result.available) {
    box.innerHTML = `<span class="placeholder-text">선택한 날짜의 날씨를 불러오지 못했습니다.${result.reason ? ` (${escapeHtml(result.reason)})` : ''}</span>`;
    return;
  }
  state.weather = result;
  state.nextWeather = null;
  renderHourlyWeather();
  const following = await window.WeatherClient.fetchForDate(nextDate(date));
  if (id !== state.weatherRequestId) return;
  state.nextWeather = following;
  renderHourlyWeather();
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
  document.getElementById('weatherBox').innerHTML = `<div class="weather-badge">Open-Meteo · ${state.weather.source === 'archive' ? '과거 날씨' : '예보'}</div><div class="weather-hourly"><table><caption>선택한 시간대의 대전 날씨</caption><thead><tr><th>시간</th><th>기온</th><th>강수</th><th>적설</th></tr></thead><tbody>${rows.join('')}</tbody></table></div>${state.endHour === 24 && !state.nextWeather?.available ? '<p class="control-help">익일 00시 날씨는 조회 중이거나 제공 범위 밖입니다.</p>' : ''}`;
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
      renderHourlyWeather();
      if (state.results.length > 0) {
        document.getElementById('searchBtn').textContent = '🔍 변경된 시간으로 추천 다시 찾기';
        document.getElementById('predictionAnalysis').textContent = '시간 범위가 변경되었습니다. [추천 다시 찾기]를 누르면 새 시간대 열차를 계산합니다.';
      }
    });
  }

  // 💡 슬라이더: 이전에 계산된 결과가 있으면 결과를 날리지 않고 즉시 가중치를 재계산해 재정렬!
  document.getElementById('quietWeight').addEventListener('input', e => {
    const val = Number(e.target.value);
    state.quietWeight = val / 100;
    document.getElementById('quietWeightLabel').textContent = `한산함 ${val}%`;
    document.getElementById('distanceWeightLabel').textContent = `거리 ${100 - val}%`;

    if (state.results && state.results.length > 0) {
      const w = state.quietWeight;
      state.results.forEach(r => {
        const qScore = typeof r.quiet_score === 'number' ? r.quiet_score : 50;
        const dScore = typeof r.distance_score === 'number' ? r.distance_score : 50;
        r.score = Number((w * qScore + (1 - w) * dScore).toFixed(1));
      });
      state.results.sort((a, b) => (b.score - a.score) || (a.distance_km - b.distance_km));
      renderRecommendations({ results: state.results, meta: state.lastMeta });
    }
  });
}

function initFilters() {
  document.querySelectorAll('.filter-btn').forEach(btn => btn.addEventListener('click', () => {
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.selectedCategory = btn.dataset.cat;

    if (state.results && state.results.length > 0) {
      // 추천 결과 모드일 때: 현재 카테고리에 맞게 필터링 렌더링
      renderRecommendations({ results: state.results, meta: state.lastMeta });
    } else {
      // 미리보기 모드일 때: 장소 목록 필터링 렌더링
      renderResults(computeRecommendations());
    }
    renderPoiMarkers();
  }));
}

function computeRecommendations() {
  let places = state.pois.filter(p => hasCoords(p));
  if (state.selectedCategory !== 'all') {
    places = places.filter(p => p.facility_type === state.selectedCategory);
  }
  return places.map(p => {
    const near = nearestStation(p);
    const originKm = state.departure ? distKm(state.departure.lat, state.departure.lng, Number(p.latitude), Number(p.longitude)) : null;
    return { ...p, nearestStation: near.station, stationKm: near.km, originKm };
  }).sort((a, b) => (state.departure ? a.originKm - b.originKm : String(a.name).localeCompare(String(b.name), 'ko')));
}

// ─────────────────────────────────────────────
// 📋 장소 미리보기 렌더링
// ─────────────────────────────────────────────
function renderResults(results) {
  const cards = document.getElementById('resultsCards');
  const cat = state.selectedCategory === 'all' ? '전체 장소' : catLabel(state.selectedCategory);
  document.getElementById('resultsMeta').textContent = `장소 목록 · ${cat} ${results.length}곳 · ${state.departure ? '출발지 직선거리순 (카드를 누르면 경로가 지도에 표시됩니다)' : '출발 위치를 선택하세요'}`;

  if (!results.length) {
    cards.innerHTML = '<p class="empty-state">해당 카테고리의 장소가 없습니다.</p>';
    return;
  }

  cards.innerHTML = results.map((p, i) => `
    <article class="result-card" data-index="${i}">
      <div class="result-rank">${i + 1}</div>
      <div class="result-name">${escapeHtml(p.name)}</div>
      <div class="result-cat">${catEmoji(p.facility_type)} ${catLabel(p.facility_type)}</div>
      <div class="result-info"><span class="result-info-key">주소</span><span class="result-info-val">${escapeHtml(p.address || '주소 정보 없음')}</span></div>
      <div class="result-info"><span class="result-info-key">가까운 역</span><span class="result-info-val">${escapeHtml(p.nearestStation.name)}역 · 직선 ${(p.stationKm * 1000).toFixed(0)}m</span></div>
      ${p.originKm !== null ? `<div class="result-info"><span class="result-info-key">출발지 거리</span><span class="result-info-val">직선 ${(p.originKm * 1000).toFixed(0)}m</span></div>` : ''}
      <div class="result-source" style="color:var(--primary);font-weight:600;">👆 클릭하여 지도에서 위치 및 경로 보기</div>
    </article>
  `).join('');

  // 카드 클릭 이벤트 바인딩
  cards.querySelectorAll('.result-card').forEach(card => {
    card.addEventListener('click', () => {
      cards.querySelectorAll('.result-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      const idx = Number(card.dataset.index);
      const item = results[idx];
      showPlaceRoute(item, false);
    });
  });
}

function renderPoiMarkers() {
  if (!state.map) return;
  state.poiMarkers.forEach(m => m.setMap(null));
  state.poiMarkers = [];

  let places = state.pois.filter(hasCoords);
  if (state.selectedCategory !== 'all') {
    places = places.filter(p => p.facility_type === state.selectedCategory);
  }

  places.forEach(p => {
    const node = document.createElement('button');
    node.className = 'poi-map-dot';
    node.type = 'button';
    node.title = p.name || '';
    node.setAttribute('aria-label', p.name || '장소');
    node.addEventListener('click', e => {
      e.stopPropagation();
      showPlaceRoute(p, false);
      // 우측 카드 목록 중 해당 카드를 찾아 스크롤 및 선택
      const cards = document.querySelectorAll('.result-card');
      cards.forEach(card => {
        if (card.querySelector('.result-name')?.textContent === p.name) {
          cards.forEach(c => c.classList.remove('selected'));
          card.classList.add('selected');
          card.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
        }
      });
    });

    const overlay = new kakao.maps.CustomOverlay({
      position: new kakao.maps.LatLng(Number(p.latitude), Number(p.longitude)),
      content: node,
      yAnchor: 0.5,
      xAnchor: 0.5,
      zIndex: 2,
    });
    overlay.setMap(state.map);
    state.poiMarkers.push(overlay);
  });
}

function stationName(station) {
  return typeof station === 'string' ? station : (station?.name || '역 정보 없음');
}

function formatTrainTime(time) {
  if (!time) return '시간 정보 없음';
  const [h, m] = String(time).split(':');
  return Number(h) >= 24 ? `익일 ${String(Number(h) - 24).padStart(2, '0')}:${m}` : String(time);
}

function countLabel(value) {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)}명` : '예측 없음';
}

// ─────────────────────────────────────────────
// 🏆 실제 추천 결과 렌더링
// ─────────────────────────────────────────────
function renderRecommendations(payload) {
  let results = payload.results || [];
  state.lastMeta = payload.meta || state.lastMeta;

  if (state.selectedCategory !== 'all') {
    results = results.filter(r => r.poi?.facility_type === state.selectedCategory);
  }

  document.getElementById('resultsMeta').textContent = `${state.date} 운행일 · ${state.startHour}~${state.endHour}시 · ${results.length}개 추천 · 한산함 ${Math.round(state.quietWeight * 100)}% (카드를 클릭하면 지하철 및 도보 경로가 표시됩니다)`;

  const cards = document.getElementById('resultsCards');
  if (!results.length) {
    cards.innerHTML = '<p class="empty-state">선택한 조건으로 이동 가능한 추천이 없습니다. 시간 범위나 목적지 테마를 바꿔 주세요.</p>';
    return;
  }

  cards.innerHTML = results.map((r, i) => {
    const p = r.poi || {}, noTrain = r.no_train;
    return `
      <article class="result-card" data-index="${i}">
        <div class="result-rank">${i + 1}</div>
        <div class="result-name">${escapeHtml(p.name)}</div>
        <div class="result-cat">${catEmoji(p.facility_type)} ${catLabel(p.facility_type)}</div>
        <div class="recommendation-time">${noTrain ? '🚶 도보 직행 (지하철 없음)' : `🚇 ${escapeHtml(formatTrainTime(r.departure_time))} 출발 → ${escapeHtml(formatTrainTime(r.arrival_time))} 도착`}</div>
        <div class="result-info"><span class="result-info-key">이용 경로</span><span class="result-info-val">${noTrain ? '지하철 없이 직접 이동' : `${escapeHtml(stationName(r.boarding_station))}역 → ${escapeHtml(stationName(r.alighting_station))}역 (${escapeHtml(r.direction || '')})`}</span></div>
        <div class="result-info"><span class="result-info-key">예상 재차</span><span class="result-info-val">${noTrain ? '열차 미탑승 (점수 중립)' : `구간 평균 ${countLabel(r.mean_load)}`}</span></div>
        <div class="result-info"><span class="result-info-key">거리</span><span class="result-info-val">직선 ${weatherNumber(r.distance_km, 'km')}</span></div>
        <div class="result-info"><span class="result-info-key">주소</span><span class="result-info-val">${escapeHtml(p.address || '주소 정보 없음')}</span></div>
        <div class="result-source" style="color:var(--primary);font-weight:600;">👆 클릭하여 지하철 노선 경로 보기 · 추천점수 ${typeof r.score === 'number' ? r.score.toFixed(1) : ''}점</div>
      </article>
    `;
  }).join('');

  // 카드 클릭 이벤트 바인딩
  cards.querySelectorAll('.result-card').forEach(card => {
    card.addEventListener('click', () => {
      cards.querySelectorAll('.result-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      const idx = Number(card.dataset.index);
      const item = results[idx];
      showPlaceRoute(item, true);
    });
  });

  const transit = results.filter(r => !r.no_train);
  document.getElementById('predictionAnalysis').innerHTML = transit.length
    ? `<div class="analysis-scroll"><table><thead><tr><th>출발 시각</th><th>이용 구간 / 장소</th><th>평균 재차</th><th>최대 재차</th></tr></thead><tbody>${transit.map(r => `<tr><td>${escapeHtml(formatTrainTime(r.departure_time))}</td><td>${escapeHtml(stationName(r.boarding_station))} → ${escapeHtml(stationName(r.alighting_station))}<br><strong>${escapeHtml(r.poi?.name)}</strong></td><td>${countLabel(r.mean_load)}</td><td>${countLabel(r.max_load)}</td></tr>`).join('')}</tbody></table></div>`
    : '열차 이동이 필요한 추천이 없습니다.';

  const notes = payload.meta?.limitations;
  if (Array.isArray(notes) && notes.length) {
    const note = document.createElement('p');
    note.className = 'control-help';
    note.textContent = notes.join(' · ');
    cards.prepend(note);
  }
}

async function requestRecommendations() {
  if (!state.departure) {
    document.getElementById('resultsCards').innerHTML = '<p class="empty-state">먼저 지도에서 출발 위치를 선택해 주세요. 지도 클릭이 어려우면 아래 노선도 역 이름을 클릭해 선택할 수 있습니다.</p>';
    renderMetroSchematic();
    return;
  }
  state.recommendationController?.abort();
  const controller = new AbortController();
  state.recommendationController = controller;
  const id = ++state.recommendationRequestId;
  const button = document.getElementById('searchBtn');
  button.disabled = true;
  button.textContent = '이동 가능한 후보 계산 중…';
  document.getElementById('resultsCards').innerHTML = '<p class="empty-state">시간표와 예상 열차 재차인원으로 순위를 계산하고 있습니다.</p>';
  const timeout = setTimeout(() => controller.abort(), 90000);

  try {
    const response = await fetch(`${API_BASE}/api/recommend`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      body: JSON.stringify({
        date: state.date,
        start_hour: state.startHour,
        end_hour: state.endHour,
        quiet_weight: Math.round(state.quietWeight * 100),
        category: state.selectedCategory,
        origin: state.departure,
        limit: 50,
      }),
    });
    let payload;
    try {
      payload = await response.json();
    } catch (_) {
      throw new Error('예측 서비스 응답을 읽을 수 없습니다.');
    }
    if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : '예측 서비스가 요청을 처리하지 못했습니다.');
    if (!Array.isArray(payload.results)) throw new Error('예측 결과 형식을 확인할 수 없습니다.');
    if (id !== state.recommendationRequestId) return;

    state.results = payload.results;
    renderRecommendations(payload);
    document.getElementById('resultsSection').scrollIntoView({ behavior: 'smooth' });

    // 1위 추천 장소의 경로를 지도에 기본 표시
    if (payload.results.length > 0) {
      const firstCard = document.querySelector('.result-card[data-index="0"]');
      if (firstCard) firstCard.classList.add('selected');
      showPlaceRoute(payload.results[0], true);
    }
  } catch (error) {
    if (id !== state.recommendationRequestId) return;
    document.getElementById('resultsMeta').textContent = '추천을 불러오지 못했습니다';
    document.getElementById('resultsCards').innerHTML = `<p class="empty-state">${escapeHtml(error.name === 'AbortError' ? '응답 시간이 길어 요청을 중단했습니다. 잠시 후 다시 시도해 주세요.' : error.message === 'Failed to fetch' ? '예측 서비스(포트 8000)에 연결할 수 없습니다. prediction_api.py 가 실행 중인지 확인해 주세요.' : error.message)}<br>혼잡도나 추천 점수를 임의로 대신 표시하지 않습니다.</p>`;
    document.getElementById('predictionAnalysis').textContent = '예측 자료를 불러오지 못했습니다.';
  } finally {
    clearTimeout(timeout);
    if (id === state.recommendationRequestId) {
      button.disabled = false;
      button.textContent = '🔍 추천 경로 찾기';
    }
  }
}

function initSearchBtn() {
  document.getElementById('searchBtn').addEventListener('click', requestRecommendations);
}

document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initRecommendationControls();
  initDateInput();
  initFilters();
  initSearchBtn();
  loadPois();
  setTimeout(tryInitMap, 400);
});
