# 🗺 개발 로드맵 — 대전 한적 나들이

> 현재 상태와 남은 작업을 단계별로 정리한 실행 계획서입니다.  
> 각 Phase는 **이전 Phase의 완료를 전제로** 진행합니다.

---

## 현재 상태 요약

```
✅ 완료  —  AI 모델 학습 (load_predictor.joblib)
✅ 완료  —  웹 뼈대 (web/index.html · style.css · app.js), 더미 데이터 동작
✅ 완료  —  README.md, ROADMAP.md, docs/AI/* 문서화
⬜ 미완  —  아래 Phase 1~5 전부
```

---

## Phase 1 — 정적 데이터 구축 (난이도 ⭐☆☆☆☆)

> **의존성 없음. 지금 바로 시작 가능. 다른 모든 Phase의 기반.**

### 1-A. 대전 1호선 역 좌표 JSON 확정

현재 `app.js` 내부 배열에 하드코딩된 좌표를 별도 파일로 분리하고 정확도를 검증합니다.

- **작업**: 네이버/카카오 지도에서 22개 역 출입구 중심 좌표를 직접 확인하여 수정
- **산출물**: `web/data/stations.json`
- **스키마 예시**:
  ```json
  [
    { "name": "판암", "idx": 0, "lat": 36.3225, "lng": 127.4542, "line": "101" },
    ...
  ]
  ```

### 1-B. 한적한 목적지 데이터셋 구축

현재 `app.js` 내 10개 더미 데이터를 실제 장소로 채웁니다.

- **목표 수량**: 25~40개 (카테고리별 최소 4~5개)
- **산출물**: `web/data/destinations.json`
- **스키마 예시**:
  ```json
  [
    {
      "id": 1,
      "name": "한밭수목원",
      "category": "park",
      "station": "정부청사",
      "station_idx": 11,
      "lat": 36.3665,
      "lng": 127.3695,
      "walk_minutes": 10,
      "desc": "도심 속 자연 수목원. 무료입장.",
      "tags": ["무료입장", "반려동물 가능"],
      "hours": "09:00~18:00",
      "closed": "월요일"
    }
  ]
  ```
- **포함 필드**: 이름, 카테고리, 연계역, 위경도, 도보 시간, 한줄 설명, 태그, 운영시간, 휴무일

> [!TIP]
> 카테고리별 체크리스트
> - **📚 도서관** (5개): 한밭도서관, 갈마도서관, 유성도서관, 노은도서관, 대전평생학습관
> - **🌳 공원** (6개): 한밭수목원, 월평공원, 유림공원, 샘머리공원, 남선공원, 보라매공원
> - **📖 서점** (4개): 계룡문고, 중앙로 독립서점들, 북카페 겸업 서점
> - **🖼 전시관** (5개): 대전시립미술관, 이응노미술관, 대전예술의전당, 근현대사전시관, 엑스포과학공원
> - **👟 산책로** (5개): 갑천변 생태산책로, 유등천변, 대전천 벚꽃길, 국립현충원 둘레길, 계족산 황토길

### 1-C. `app.js`를 외부 JSON으로 연결

하드코딩된 `STATIONS`, `DESTINATIONS` 배열을 JSON 파일에서 `fetch()`로 로드하도록 교체합니다.

```javascript
// 변경 전
const STATIONS = [ { name: '판암', ... } ];

// 변경 후
const { stations, destinations } = await loadData();
async function loadData() {
  const [s, d] = await Promise.all([
    fetch('./data/stations.json').then(r => r.json()),
    fetch('./data/destinations.json').then(r => r.json()),
  ]);
  return { stations: s, destinations: d };
}
```

> [!NOTE]
> `fetch()`는 로컬 `file://` 프로토콜에서 CORS 오류가 납니다.  
> 로컬 개발 시에는 `python -m http.server 8000` 으로 실행하세요.

---

## Phase 2 — ONNX 모델 변환 (난이도 ⭐⭐⭐☆☆)

> **Phase 1과 병행 가능. ML 추론을 브라우저에서 실행하기 위한 핵심 단계.**

### 2-A. 변환 라이브러리 설치

```powershell
pip install skl2onnx onnx onnxruntime
```

현재 환경에 `skl2onnx`, `onnx`가 설치되어 있지 않습니다 (확인 완료).

### 2-B. 변환 스크립트 작성 및 실행

- **산출물**: `scripts/convert_model_to_onnx.py`
- **입력**: `outputs/load_predictor.joblib` (scikit-learn 1.9.1 학습 완료)
- **출력**: `web/model/load_predictor.onnx` (~1~2MB 예상)

```python
# 핵심 변환 로직 (스크립트 내부)
import joblib
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType

model = joblib.load("./outputs/load_predictor.joblib")
# 피처 8개: station_idx, hour, dir_code, is_weekend, temp, precip, snow, plan_version
initial_type = [('float_input', FloatTensorType([None, 8]))]
onnx_model = convert_sklearn(model, initial_types=initial_type)
with open("./web/model/load_predictor.onnx", "wb") as f:
    f.write(onnx_model.SerializeToString())
```

> [!WARNING]
> `HistGradientBoostingRegressor`는 `skl2onnx` 지원 범위에 포함되지만,
> 버전에 따라 변환 오류가 날 수 있습니다. 변환 실패 시 대안:
> - **대안 A**: Python으로 트리 구조를 JSON으로 직접 덤프하여 JS에서 파싱
> - **대안 B**: LightGBM으로 모델을 재학습 후 `lightgbm`의 ONNX 내보내기 사용

### 2-C. 변환 결과 정확도 검증

Python `onnxruntime`으로 원본 `joblib` 모델과 `onnx` 모델의 예측값이 일치하는지 확인합니다.

---

## Phase 3 — 브라우저 ML 추론 연동 (난이도 ⭐⭐⭐⭐☆)

> **Phase 2 완료 후 진행. 더미 데이터를 실제 모델 예측값으로 교체.**

### 3-A. `onnxruntime-web` 로드

```html
<!-- web/index.html에 추가 -->
<script src="https://cdn.jsdelivr.net/npm/onnxruntime-web@1.19.2/dist/ort.min.js"></script>
```

### 3-B. `web/model_runner.js` 작성

- 모델 초기화(`ort.InferenceSession.create`)
- 입력 텐서 생성 (8개 피처 × N개 추론 행)
- 출력 텐서 → JS 배열 변환
- `app.js`의 `mockLoad`를 `modelRunner.predict(station, hour, direction, weather)` 호출로 교체

### 3-C. 추론 흐름 완성

날짜 선택 → 날씨 조회 → 22개 역 × 20개 시간대 × 2개 방향 = **880개 추론**을 한 배치로 실행하여 UI 상태로 저장.

---

## Phase 4 — 외부 API 연동 (난이도 ⭐⭐☆☆☆)

> **Phase 1~3과 거의 독립적으로 병행 가능.**

### 4-A. 날씨 API — Open-Meteo (무료, API 키 불필요)

```javascript
// 대전 위경도 고정 (36.35, 127.38)
const url = `https://api.open-meteo.com/v1/forecast`
          + `?latitude=36.35&longitude=127.38`
          + `&daily=temperature_2m_max,precipitation_sum,snowfall_sum`
          + `&timezone=Asia%2FSeoul&start_date=${date}&end_date=${date}`;
```

- 반환값: 일 최고기온, 강수량 합계, 적설량 합계
- `app.js`의 `loadWeather()` 함수를 실제 호출로 교체

> [!TIP]
> Open-Meteo는 무료·무키·CORS 허용이라 GitHub Pages 정적 배포에 가장 적합합니다.
> 단, 예보 가능 기간은 현재 기준 최대 16일 선행이므로 그 이후 날짜 선택 시 UI 안내 필요.

### 4-B. 네이버 지도 API — Client ID 발급 및 연동

1. [Naver Cloud Platform Console](https://console.ncloud.com) → 애플리케이션 등록
2. **Maps - Web Dynamic Map** 사용 허가 신청
3. 허용 도메인에 `localhost` 및 최종 GitHub Pages 도메인 추가
4. `index.html`의 `YOUR_CLIENT_ID`를 발급받은 키로 교체
5. `app.js`의 `setDeparture()` 함수가 클릭 좌표를 Reverse Geocoding으로 주소로 변환하는 기능 추가

---

## Phase 5 — 목적지 상세 플랜 & UX 완성 (난이도 ⭐⭐⭐☆☆)

> **Phase 1~4 완료 후 진행. 서비스의 최종 완성도를 높이는 단계.**

### 5-A. 목적지 상세 카드 / 모달

추천 카드 클릭 시 현재 `alert()`으로 처리되는 부분을 슬라이드업 패널 또는 모달로 교체:
- 출발역 → 도착역 경로 (어느 방향 열차, 몇 시 탑승)
- 해당 시간대 열차 혼잡도 게이지
- 목적지 운영시간, 도보 경로 힌트
- 네이버 지도 길찾기 딥링크

### 5-B. 추천 가중치 고도화

현재 단순 선형 가중치를 더 세밀하게 개선합니다:
- **시간 선호 필터**: 사용자가 오전/오후/저녁 중 원하는 시간대 범위 지정
- **최대 도보 거리 필터**: 슬라이더로 "역까지 최대 N분 거리만"으로 제한

### 5-C. 모바일 반응형 최종 검증

Chrome DevTools 모바일 에뮬레이터로 전체 UX 테스트 (iPhone SE, Galaxy S21 기준).

---

## Phase 6 — 배포 (난이도 ⭐☆☆☆☆)

> **Phase 1~5 완료 후 진행.**

### 6-A. GitHub 저장소 정리

```
.gitignore에 반드시 포함:
  outputs/ground_truth_train_loads.csv  # 6MB, 대용량
  data/raw/                             # 원시 수집 데이터
  .env                                  # API 키
  __pycache__/
```

### 6-B. GitHub Pages 배포 설정

- 저장소 Settings → Pages → Source: `main` 브랜치 `/web` 폴더 지정
- 접속 URL: `https://{username}.github.io/{repo}/`

### 6-C. 네이버 지도 허용 도메인에 Pages 도메인 추가

Naver Cloud Console → 애플리케이션 → 허용 도메인에 GitHub Pages 도메인 추가.

---

## 전체 의존성 그래프

```
Phase 1 (데이터)
  ├── 1-A 역 좌표 ──────────────────┐
  ├── 1-B 목적지 JSON ──────────────┤
  └── 1-C app.js fetch 연결 ────────┤
                                    │
Phase 2 (ONNX 변환) ────────────────┤
  └── 변환 스크립트 & 검증 ──────────┤
                                    │
Phase 3 (브라우저 추론) ◄───────────┘ (1-C + 2 완료 필요)
  └── model_runner.js

Phase 4 (외부 API) ─── 대부분 독립적으로 병행 가능
  ├── 4-A 날씨 API (즉시 가능)
  └── 4-B 네이버 지도 (API 키 발급 후)

Phase 5 (UX 완성) ◄─── 1~4 완료 후
Phase 6 (배포)    ◄─── 1~5 완료 후
```

---

## 작업 순서 추천 (실용적 관점)

| 순서 | 작업 | 이유 |
| :--: | :--- | :--- |
| **1** | **1-B 목적지 데이터 구축** | 가장 반복적인 수작업. 먼저 끝내두면 뒤가 편해짐 |
| **2** | **4-A Open-Meteo 날씨 API** | API 키 불필요, 1시간이면 연동 가능 |
| **3** | **4-B 네이버 지도 API 키 발급** | 발급 심사에 시간이 걸릴 수 있으므로 일찍 신청 |
| **4** | **1-A 역 좌표 JSON 정확도 검증** | 지도 API 뜨면 바로 확인 가능 |
| **5** | **2 ONNX 변환 (skl2onnx 설치 → 변환 → 검증)** | 기술 불확실성이 가장 높음. 빠를수록 좋음 |
| **6** | **3 브라우저 ML 추론 연동** | 2 완료 직후 |
| **7** | **5 UX 완성 (상세 모달, 시간 필터)** | 데이터·추론이 모두 완성된 뒤 |
| **8** | **6 GitHub Pages 배포** | 최종 |
