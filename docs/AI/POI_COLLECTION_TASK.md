# 대전 문화·여가 시설 데이터 수집 작업 지시서

## 0. 작업 개요

대전광역시의 **도서관, 전시관(문화시설), 서점, 공원, 산책로** 정보를 각 공식 배포처에서 **1회 수집**하여 로컬에 보관한다. 매일 동적 수집은 불필요하며, **한 번 받아서 유지·활용**하는 것이 목적이다.

- **최종 산출물**: `./data/raw/poi/` 아래에 시설별 원본 파일 + 통합 좌표 파일
- **좌표계**: WGS84 (EPSG:4326)
- **언어**: 한국어
- **공공데이터포털 API 신청**: 필요한 활용신청과 키 발급은 완료됨. 실제 호출과 응답 수집만 수행한다.
- **주의**: 모든 데이터는 국내 공식 배포처에서만 수집한다. 해외 서비스·해외 API는 사용하지 않는다.

## 1. 공통 규칙

1. **원본 보존**: 다운로드한 원본 파일(CSV/XLSX/JSON)은 절대 가공하지 말고 `./data/raw/poi/{시설}/raw/` 에 그대로 보관한다.
2. **가공본 분리**: 좌표 변환·정제 결과는 `./data/raw/poi/{시설}/processed/` 에 저장한다.
3. **출처 기록**: 각 데이터마다 `source.md` 를 만들어 **배포처 URL, 다운로드 일시, 라이선스(이용허락범위), 담당 부서**를 기록한다.
4. **좌표 변환**: 주소만 있고 제공 좌표가 없는 데이터는 **VWorld Geocoder API 2.0**으로 변환한다.
   - VWorld 개발자센터에서 발급받은 인증키를 프로젝트 루트 `.env`의 `VWORLD_API_KEY`에 저장한다.
   - 코드에서는 `python-dotenv` 등으로 환경변수 `VWORLD_API_KEY`를 읽는다. **키를 코드나 문서에 직접 기록하지 않는다.**
   - 요청 좌표계는 `EPSG:4326`으로 지정한다. 응답 `point.x`는 경도(longitude), `point.y`는 위도(latitude)다.
   - 주소 종류는 도로명주소(`ROAD`) 우선으로 조회하고, 결과가 없으면 지번주소(`PARCEL`)로 재시도한다. 실제 요청값은 발급 계정의 API 가이드와 대조한다.
   - VWorld 이용 한도와 호출 간격을 확인하고 준수한다. 동일 주소의 결과는 캐시해 중복 호출을 줄인다.
5. **실패 처리**: 다운로드·변환 실패 시 **중단하지 말고 로그를 남기고 계속 진행**한다. 실패 목록은 `./data/raw/poi/failures.md` 에 기록한다.
6. **좌표 없는 데이터**: 좌표를 얻을 수 없는 시설(예: 산책로)은 **주소·코스 텍스트만 보관**하고, 좌표 컬럼은 비워둔다. 억지로 추정하지 않는다.

## 2. 시설별 수집 작업

### 2-1. 도서관

- **배포처**: 공공데이터포털 `대전광역시_공공도서관 현황` (파일데이터, CSV)
- **URL**: `https://www.data.go.kr` 에서 "대전광역시\_공공도서관 현황" 검색
- **작업**:
  1. CSV 다운로드 → `./data/raw/poi/library/raw/`
  2. 주소 컬럼 확인 (소재지)
  3. 주소를 VWorld로 지오코딩 → `./data/raw/poi/library/processed/library.csv` (컬럼: 명칭, 주소, 위도, 경도)
  4. `source.md` 작성

### 2-2. 전시관 (문화시설)

- **배포처**: 공공데이터포털 `대전광역시_문화시설` (Open API, JSON)
- **이용허락범위**: 제한 없음
- **작업**:
  1. **공공데이터포털 활용신청과 서비스키 발급은 완료됨.** 수집 시 `.env`의 `DATA_GO_KR_SERVICE_KEY`를 사용한다.
  2. API **1회 호출**로 전체 목록 수집 → `./data/raw/poi/culture/raw/culture.json`
  3. `시설유형`이 "전시관"인 항목 필터링
  4. 유효한 좌표 필드가 있으면 그대로 사용하고, 없으면 주소를 VWorld로 변환 → `./data/raw/poi/culture/processed/culture.csv` (컬럼: 명칭, 유형, 주소, 위도, 경도)
  5. `source.md` 작성 (서비스키는 환경변수 `DATA_GO_KR_SERVICE_KEY`에서 읽고 하드코딩 금지)

### 2-3. 서점

- **배포처**: 대전광역시 홈페이지 > 문화콘텐츠과 > `대전광역시 인증 지역서점 목록` (XLSX)
- **작업**:
  1. XLSX 다운로드 → `./data/raw/poi/bookstore/raw/`
  2. **주소 컬럼 존재 여부 확인**. 없으면 `failures.md` 에 "주소 컬럼 없음" 기록하고 종료.
  3. 주소가 있으면 VWorld로 좌표 변환 → `./data/raw/poi/bookstore/processed/bookstore.csv`
  4. `source.md` 작성

### 2-4. 공원

- **1순위 배포처**: 대전시 **대시민 빅데이터 포털** `대전광역시 도시공원정보` (REST API)
  - URL: `https://apis.data.go.kr/6300000/parkInfoDaejeonService/parkInfoDaejeonList`
  - **개발가이드 먼저 확인**하여 좌표 필드 유무 파악
  - API **1회 호출**로 전체 수집 → `./data/raw/poi/park/raw/park.json`
  - 유효 좌표가 있으면 그대로, 없으면 주소를 VWorld로 변환 → `./data/raw/poi/park/processed/park.csv`
- **2순위 (1순위 실패 시)**: 각 구청 홈페이지의 **녹지현황 XLSX**
  - 중구청, 서구청, 유성구청, 대덕구청, 동구청 홈페이지에서 "녹지현황" 검색
  - 파일 다운로드 → `./data/raw/poi/park/raw/{구청명}_녹지현황.xlsx`
  - 주소 컬럼이 있으면 VWorld로 변환, 없으면 명칭·면적만 보관
- `source.md` 작성 (어느 출처를 썼는지 명시)

### 2-5. 산책로

- **배포처**: 공공데이터포털 `대전광역시_산책길 대전둘레산길` (파일데이터, CSV)
- **작업**:
  1. CSV 다운로드 → `./data/raw/poi/trail/raw/`
  2. **좌표 컬럼 유무 확인**
  3. 좌표가 없으면 **코스 텍스트만 보관** → `./data/raw/poi/trail/processed/trail.csv` (컬럼: 구간, 명칭, 코스, 거리, 시간)
  4. `source.md` 작성

## 3. 통합 산출물

모든 시설의 processed CSV를 합쳐 **`./data/raw/poi/poi_all.csv`** 를 만든다.

- **컬럼**: `facility_type`(library/culture/bookstore/park/trail), `name`, `address`, `latitude`, `longitude`, `source`
- **좌표 없는 항목**: `latitude`, `longitude` 는 빈 값으로 둔다.
- **중복 제거**: 같은 이름·주소가 여러 출처에 있으면 1건만 남기고 `source` 에 출처를 병기한다.

## 4. 검증 및 보고

작업 완료 후 **`./data/raw/poi/REPORT.md`** 를 작성한다.

- 시설별 **수집 건수**
- 시설별 **좌표 변환 성공/실패 건수**
- **실패 목록** (`failures.md` 링크)
- **라이선스 요약** (출처별 이용허락범위)
- **재현 방법**: 어떤 순서로 실행했는지

## 5. 금지 사항

- 해외 API·해외 지도 서비스 사용 금지
- VWorld API 키·공공데이터포털 서비스키 **코드 하드코딩 금지** (`.env`/환경변수 사용)
- 원본 파일 **가공 금지** (raw는 그대로)
- 좌표 없는 데이터에 **임의 좌표 추정 금지**
- 다운로드 실패 시 **작업 중단 금지** (로그 남기고 계속)

## 6. 실행 순서 (권장)

1. `./data/raw/poi/` 디렉터리 구조 생성
2. `.env`에 `VWORLD_API_KEY`, `DATA_GO_KR_SERVICE_KEY`가 설정되어 있는지 값은 출력하지 않고 확인
3. 도서관 → 전시관 → 서점 → 공원 → 산책로 순으로 수집
4. 각 시설별 `processed` CSV 생성
5. `poi_all.csv` 통합
6. `REPORT.md`, `failures.md` 작성

## 7. 참고: 좌표 변환 (VWorld Geocoder API 2.0)

- 주소 → WGS84 좌표 변환 엔드포인트: `https://api.vworld.kr/req/address`
- 주요 요청값: `service=address`, `request=getcoord`, `version=2.0`, `crs=epsg:4326`, `address={주소}`, `type=ROAD` 또는 `PARCEL`, `format=json`, `key={VWORLD_API_KEY}`
- 성공 응답에서 `response.result.point.x`를 경도, `response.result.point.y`를 위도로 저장한다.
- CSV의 `위도`/`latitude`에는 `y`, `경도`/`longitude`에는 `x`를 넣는다. 지도 표시 순서와 혼동하지 않는다.
- 응답 성공 여부를 확인한 뒤 좌표를 저장한다. 실패하거나 결과가 모호한 주소는 실패 목록에 기록하고 추정 좌표를 넣지 않는다.
- 공식 자료: [VWorld 2026 API 교육 자료](https://github.com/V-world/V-world_API_sample/blob/master/%EB%B8%8C%EC%9D%B4%EC%9B%94%EB%93%9C_%EA%B5%90%EC%9C%A1/2026%EB%85%84_%EB%B8%8C%EC%9D%B4%EC%9B%94%EB%93%9C_%EA%B5%90%EC%9C%A1/Readme.md), [VWorld 개발자센터](https://www.vworld.kr/)
