const datePicker = document.getElementById('datePicker');
const timeSlider = document.getElementById('timeSlider');
const timeDisplay = document.getElementById('timeDisplay');
const weatherPrecip = document.getElementById('weatherPrecip');
const weatherTemp = document.getElementById('weatherTemp');
const weatherSnow = document.getElementById('weatherSnow');
const subwayMap = document.getElementById('subwayMap');

// 대전 1호선 역 정보 (101~122)
// SVG 그리기 위한 좌표 (임의의 선형 배치)
const stations = [
    { no: "101", name: "판암" }, { no: "102", name: "신흥" }, { no: "103", name: "대동" },
    { no: "104", name: "대전" }, { no: "105", name: "중앙로" }, { no: "106", name: "중구청" },
    { no: "107", name: "서대전네거리" }, { no: "108", name: "오룡" }, { no: "109", name: "용문" },
    { no: "110", name: "탄방" }, { no: "111", name: "시청" }, { no: "112", name: "정부청사" },
    { no: "113", name: "갈마" }, { no: "114", name: "월드컵경기장" }, { no: "115", name: "노은" },
    { no: "116", name: "지족" }, { no: "117", name: "반석" }, { no: "118", name: "현충원" },
    { no: "119", name: "구암" }, { no: "120", name: "유성온천" }, { no: "121", name: "갑천" },
    { no: "122", name: "대전역" } // 임시 매핑 (실제와 다를 수 있음)
];

// 임시: SVG 초기화 (선형 배치)
function drawSubwayMap() {
    subwayMap.innerHTML = ''; // 초기화
    const startX = 50;
    const startY = 200;
    const gapX = 30; // 역 간격

    // 노선 선 그리기
    let pathD = `M ${startX} ${startY}`;
    for (let i = 1; i < stations.length; i++) {
        pathD += ` L ${startX + i * gapX} ${startY}`;
    }
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", pathD);
    path.setAttribute("class", "line-path");
    subwayMap.appendChild(path);

    // 역 노드 그리기
    stations.forEach((station, index) => {
        const cx = startX + index * gapX;
        const cy = startY;

        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circle.setAttribute("cx", cx);
        circle.setAttribute("cy", cy);
        circle.setAttribute("r", 5); // 기본 크기
        circle.setAttribute("class", "station-node");
        circle.setAttribute("id", `station-${station.no}`);
        subwayMap.appendChild(circle);

        const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
        text.setAttribute("x", cx);
        text.setAttribute("y", cy + 15);
        text.setAttribute("class", "station-name");
        text.textContent = station.name;
        subwayMap.appendChild(text);
    });
}

// JSON 데이터 로드 및 UI 업데이트
async function updateDashboard(date, hour) {
    // 파일명 형식: YYYY-MM-DD.json
    const url = `./data/merged/${date}.json`;
    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error("Data not found");
        const data = await response.json();

        // 1. 날씨 업데이트
        const weather = data.hourly_data[hour].weather;
        weatherPrecip.textContent = `${weather.precipitation.toFixed(1)} mm`;
        weatherTemp.textContent = `${weather.temperature_2m.toFixed(1)} °C`;
        weatherSnow.textContent = `${weather.snowfall.toFixed(1)} cm`;

        // 날씨 아이콘 변경 (간단한 로직)
        const weatherIcon = document.getElementById('weatherIcon');
        if (weatherIcon) {
            if (weather.snowfall > 0) {
                weatherIcon.className = 'fa-solid fa-snowflake';
            } else if (weather.precipitation > 0) {
                weatherIcon.className = 'fa-solid fa-cloud-rain';
            } else {
                weatherIcon.className = 'fa-solid fa-sun';
            }
        }

        // 2. 지하철 승차 인원 업데이트 (노드 크기 변경)
        data.hourly_data[hour].subway.forEach(sub => {
            const node = document.getElementById(`station-${sub.station_no}`);
            if (node) {
                // 승차 인원에 비례하여 반지름 조정 (최소 3, 최대 15)
                const radius = Math.max(3, Math.min(15, sub.boardings / 10));
                node.setAttribute("r", radius);
            }
        });

    } catch (error) {
        console.error("Error loading data:", error);
        alert("해당 날짜의 데이터를 찾을 수 없습니다.");
    }
}

// 이벤트 리스너
timeSlider.addEventListener('input', (e) => {
    const hour = e.target.value;
    timeDisplay.textContent = `${hour.toString().padStart(2, '0')}:00`;
    updateDashboard(datePicker.value, hour);
});

datePicker.addEventListener('change', (e) => {
    updateDashboard(e.target.value, timeSlider.value);
});

// 초기화
window.onload = () => {
    drawSubwayMap();
    // 초기 날짜 설정 (2026-10-01)
    datePicker.value = "2026-10-01";
    updateDashboard("2026-10-01", 12);
};