📋 지하철 및 날씨 데이터 1시간 단위 병합 메뉴얼

1. 작업 목표
   ./data/subway/의 지하철 XML 데이터와 ./data/weather/의 날씨 JSON 데이터를 읽어와, 1시간 단위(hourly)로 1:1 매핑하여 하나의 통합 JSON 파일로 저장합니다.

2. 입력 데이터 구조
   2.1 지하철 데이터 (./data/subway/YYYY-MM-DD.xml)
   각 <item>은 특정 역, 승차권 종류, 승차/하차 구분(entryFlag)에 대한 1시간 단위 인원(cnt00~cnt23) 을 담고 있습니다.

필터링 조건: 승차 데이터만 사용하므로 entryFlag == "0" 인 항목만 대상으로 합니다.

2.2 날씨 데이터 (./data/weather/YYYY-MM-DD.json)
hourly 객체 안에 24시간 치 배열이 담겨 있습니다.

time: ["2026-10-01T00:00", ..., "2026-10-01T23:00"] (24개)

precipitation: 시간별 강수량 배열 (24개)

snowfall: 시간별 적설량 배열 (24개)

temperature_2m: 시간별 기온 배열 (24개)

3. 출력 데이터 구조 (./data/merged/YYYY-MM-DD.json)
   json
   {
   "date": "2026-10-01",
   "hourly_data": [
   {
   "hour": 0,
   "weather": {
   "precipitation": 0.0,
   "snowfall": 0.0,
   "temperature_2m": 18.0
   },
   "subway": [
   {"station_no": "101", "boardings": 0},
   {"station_no": "102", "boardings": 0}
   ]
   },
   {
   "hour": 14,
   "weather": {
   "precipitation": 2.4,
   "snowfall": 0.0,
   "temperature_2m": 20.1
   },
   "subway": [
   {"station_no": "101", "boardings": 38},
   {"station_no": "102", "boardings": 30}
   ]
   }
   // ... 23시까지 반복
   ]
   }
4. 병합 절차 (Step-by-Step)
   Step 1: 디렉토리 생성 및 날짜 설정
   ./data/merged/ 디렉토리가 없으면 생성합니다.

병합할 날짜(예: 2026-10-01)를 기준으로 파일 경로를 설정합니다.

Step 2: 날씨 데이터 로드
./data/weather/YYYY-MM-DD.json 파일을 읽어 JSON 객체로 파싱합니다.

hourly 객체에서 precipitation, snowfall, temperature_2m 배열을 추출합니다. (인덱스 0~23이 00시~23시에 해당)

Step 3: 지하철 데이터 로드 및 시간별 집계
./data/subway/YYYY-MM-DD.xml 파일을 읽어 XML을 파싱합니다.

<items> 아래의 모든 <item>을 순회합니다.

entryFlag == "0" (승차)인 항목만 필터링합니다.

각 역(stationNo)별로 cnt00~cnt23 값을 추출하여, 시간(hour)별 역별 승차 인원을 담는 딕셔너리를 만듭니다.

예: {"101": {"0": 0, "1": 0, ..., "14": 38}, "102": {...}}

Step 4: 시간(Hour) 기준 병합
0시부터 23시까지 반복문을 실행합니다.

각 시간(hour)에 대해:

날씨: Step 2에서 추출한 배열의 hour 인덱스 값을 가져옵니다.

지하철: Step 3에서 만든 딕셔너리에서 해당 시간의 역별 승차 인원을 가져옵니다.

이를 하나의 객체로 묶어 hourly_data 배열에 추가합니다.

Step 5: 최종 JSON 저장
병합된 데이터를 ./data/merged/YYYY-MM-DD.json 경로에 저장합니다.

ensure_ascii=False, indent=2 옵션을 사용합니다.

5. 주의사항 및 예외 처리
   날씨 시간 배열 파싱: time 배열의 값은 "2026-10-01T14:00" 형식입니다. 시간(Hour)을 추출하려면 split("T")[1][:2]를 사용하여 정수로 변환하세요.

파일 누락: 특정 날짜의 날씨 또는 지하철 파일이 없을 경우, 에러를 발생시키지 말고 로그를 남긴 후 해당 날짜는 건너뛰도록 예외 처리하세요.

지하철 데이터 누락: 특정 역의 데이터가 없거나 cnt 값이 비어있을 경우 0으로 처리하세요.

데이터 타입: 승차 인원(boardings)은 정수형(Integer)으로 변환하세요.

역 번호 정렬: subway 배열을 station_no 기준으로 오름차순 정렬하면 보기 좋습니다.
