📋 Open-Meteo 1시간 단위 날씨 데이터 순차 수집 메뉴얼 (2026년 10월)

1. 작업 목표
   Open-Meteo Archive API를 사용하여, 2026년 10월 1일부터 2026년 10월 31일까지 대전 지역의 1시간 단위 날씨 데이터를 수집하고, ./data/weather/ 디렉토리에 날짜별 JSON 파일로 저장합니다.

2. API 정보
   Base URL: https://archive-api.open-meteo.com/v1/archive

응답 포맷: JSON

인증 방식: 불필요 (Open-Meteo는 무료이며 API 키가 필요 없습니다.)

3. 요청 파라미터
   파라미터 값 설명
   latitude 36.35 대전 중심부 위도
   longitude 127.38 대전 중심부 경도
   start_date 2026-10-01 ~ 2026-10-31 조회 날짜 (일별로 변경)
   end_date 2026-10-01 ~ 2026-10-31 조회 날짜 (start_date와 동일)
   hourly precipitation,snowfall,temperature_2m 1시간 단위 데이터 항목 (강수량, 적설량, 기온)
   timezone Asia/Seoul 한국 시간대 설정
4. 요청 URL 예시
   text
   https://archive-api.open-meteo.com/v1/archive?latitude=36.35&longitude=127.38&start_date=2026-10-01&end_date=2026-10-01&hourly=precipitation,snowfall,temperature_2m&timezone=Asia/Seoul
5. 순차 수집 절차 (Step-by-Step)
   Step 1: 저장 디렉토리 생성
   스크립트 실행 시 ./data/weather/ 디렉토리가 없으면 자동으로 생성(os.makedirs)하도록 합니다.

Step 2: 날짜 범위 설정 및 반복
시작일: 2026-10-01

종료일: 2026-10-31

하루씩 증가하는 반복문(Loop)을 구성합니다.

Step 3: 일별 요청 (Loop)
반복문 내에서 start_date와 end_date를 동일한 날짜로 설정하여 요청합니다.

예: 1회차 요청 시 start_date=2026-10-01, end_date=2026-10-01

예: 2회차 요청 시 start_date=2026-10-02, end_date=2026-10-02

Step 4: 응답 처리 및 저장
응답받은 JSON 데이터를 파싱합니다.

응답의 hourly 객체 안에 있는 time, precipitation, snowfall, temperature_2m 배열을 추출합니다.

time 배열은 ["2026-10-01T00:00", "2026-10-01T01:00", ..., "2026-10-01T23:00"] 형태입니다. (24개)

추출한 데이터를 ./data/weather/ 디렉토리에 날짜별 JSON 파일로 저장합니다.

저장 경로: ./data/weather/2026-10-01.json

파일 내용 예시:

json
{
"date": "2026-10-01",
"hourly": {
"time": ["2026-10-01T00:00", ..., "2026-10-01T23:00"],
"precipitation": [0.0, 0.0, ..., 2.4],
"snowfall": [0.0, 0.0, ..., 0.0],
"temperature_2m": [18.0, 17.8, ..., 19.5]
}
}
Step 5: 대기 시간 (Rate Limit 준수)
Open-Meteo는 무료이지만, 과도한 요청을 방지하기 위해 요청 간 0.5~1초의 대기 시간(sleep) 을 두는 것을 권장합니다.

6. 주의사항
   날짜 형식: API 요청 시 날짜는 반드시 YYYY-MM-DD 형식이어야 합니다.

타임존: timezone=Asia/Seoul을 반드시 포함하여 한국 시간 기준으로 데이터를 받으세요.

에러 처리: 응답 상태 코드가 200이 아닐 경우, 로그를 남기고 해당 날짜는 건너뛰거나 재시도하도록 로직을 구성하세요.

디렉토리 권한: ./data/weather/ 생성 시 쓰기 권한이 있는지 확인하세요.

변수명 주의: 1시간 단위 데이터는 precipitation_sum이 아니라 precipitation (해당 시간 강수량)을 사용합니다.
