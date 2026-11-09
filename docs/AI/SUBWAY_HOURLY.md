subway_time.json → station_hourly.json 변환 매뉴얼

1. 목적
   기존 subway_time.json(열차별 정차 시각 목록)을 입력받아, 역별·요일별·시간대별 열차 통과 대수를 담은 station_hourly.json을 출력한다.

출력 JSON은 이후 승하차 인원 분배 계산의 분모로 사용된다.

2. 입력
   subway_time.json — 다음 구조를 가진다.

json
{
"trains": [
{
"train_id": "평일-상행-001",
"day_type": "평일", // "평일" | "휴일"
"direction": "상행", // "상행" | "하행"
"origin": "반석",
"destination": "판암",
"interpolated": true,
"stops": [
{ "station": "반석", "time": "05:30" },
{ "station": "지족", "time": "05:32" },
...
]
},
...
]
}
day_type: "평일" 또는 "휴일" 두 값만 존재.

direction: "상행"(반석→판암) 또는 "하행"(판암→반석).

stops: 각 열차의 정차역과 시각. 첫 stop = 출발역, 마지막 stop = 종착역.

3. 출력
   station_hourly.json — 최상위 키는 요일 구분 두 개만 둔다. 역명은 한글 그대로 사용한다(역 ID로 바꾸지 않는다). 시간대 키는 문자열 숫자로 한다.

json
{
"평일": {
"판암": {
"5": { "departures": 0, "passes": 0, "arrivals": 3 },
"6": { "departures": 0, "passes": 0, "arrivals": 4 }
},
"신흥": {
"5": { "departures": 0, "passes": 2, "arrivals": 0 }
},
"정부청사": {
"23": { "departures": 0, "passes": 2, "arrivals": 1 }
}
},
"휴일": {
...
}
}
필드 정의
필드 의미 승차 분모 하차 분모
departures 해당 역이 출발역인 열차 수 ✅ 포함 ❌ 제외
passes 해당 역을 중간 통과한 열차 수 ✅ 포함 ✅ 포함
arrivals 해당 역이 종착역인 열차 수 ❌ 제외 ✅ 포함
승차 분모 = departures + passes

하차 분모 = passes + arrivals

4. 변환 규칙

4.1 열차 1대당 처리
각 열차의 stops 배열을 순회한다.

첫 번째 stop의 역 → 해당 요일·시간대에 departures += 1

마지막 stop의 역 → 해당 요일·시간대에 arrivals += 1

중간 stop의 역 → 해당 요일·시간대에 passes += 1

4.2 시간대 판정
각 stop의 time 문자열에서 시(hour) 두 자리를 정수로 파싱한다.

예: "05:30" → 5, "23:58" → 23, "24:12" → 24.

24시대는 그대로 "24" 키로 저장한다. 0시로 되돌리지 않는다.

시간대 키는 문자열로 저장한다. ("5", "6", ..., "24")

4.3 역 키
stops[].station의 한글 역명을 그대로 사용한다.

22개 역: 판암, 신흥, 대동, 대전, 중앙로, 중구청, 서대전네거리, 오룡, 용문, 탄방, 시청, 정부청사, 갈마, 월평, 갑천, 유성온천, 구암, 현충원, 월드컵경기장, 노은, 지족, 반석.

4.4 초기화
출력 딕셔너리는 빈 상태에서 시작한다.

어떤 역·시간대 조합에 처음 카운트가 발생할 때 해당 키를 생성하고 0으로 초기화한 뒤 증가시킨다.

카운트가 0인 조합은 출력에 포함하지 않는다 (빈 딕셔너리 절약).

5. 의사코드
   text
   output = {"평일": {}, "휴일": {}}

for train in input.trains:
day = train.day_type # "평일" | "휴일"
stops = train.stops
n = len(stops)

    if n == 0:
        continue

    for i, stop in enumerate(stops):
        station = stop.station
        hour = int(stop.time[:2])     # "05:30" → 5
        hour_key = str(hour)          # "5", "24" 등

        # 출력 딕셔너리 초기화
        if station not in output[day]:
            output[day][station] = {}
        if hour_key not in output[day][station]:
            output[day][station][hour_key] = {
                "departures": 0, "passes": 0, "arrivals": 0
            }

        cell = output[day][station][hour_key]

        if i == 0:
            cell["departures"] += 1
        elif i == n - 1:
            cell["arrivals"] += 1
        else:
            cell["passes"] += 1

write_json("station_hourly.json", output) 6. 검증 기준
변환 후 다음을 확인한다.

총 카운트 합계 검증

전체 열차 수 × 1 = departures 총합 = arrivals 총합

각 열차의 stop 수 합 = departures + passes + arrivals 총합

예: 열차 462대, 정차 시각 총합이 N이라면,
sum(departures) = 462, sum(arrivals) = 462,
sum(passes) = N - 924 이어야 한다.

요일별 분리 검증

output["평일"]의 총 카운트 = 평일 열차들의 stop 수 합

output["휴일"]도 동일.

시간대 범위 검증

모든 시간대 키는 "5" 이상 "24" 이하의 문자열이어야 한다.

역 이름 검증

22개 역 이름 외의 키가 없어야 한다.

7. 주의 사항
   interpolated: true 플래그는 무시한다. 보간된 종착역 stop도 일반 stop과 동일하게 arrivals로 카운트한다.

방향(상행/하행)은 무시한다. 승차/하차 인원이 방향 구분 없이 총합으로 주어지므로, 여기서도 방향을 나누지 않는다.

train_id, origin, destination 메타데이터는 사용하지 않는다. 오직 stops 배열의 순서와 station/time만 사용한다.

시간대 키는 반드시 문자열이어야 한다. JSON에서 정수 키는 문자열로 변환되지만, 혼동을 막기 위해 명시적으로 str()을 적용한다.

24시대 처리: "24:12"는 "24" 키에 카운트한다. 0시대로 매핑하면 승하차 데이터의 시간대(0~23시)와 어긋난다. 이후 승하차 조인 단계에서 "24"를 어떻게 다룰지는 별도 결정한다.

8. 산출물
   station_hourly.json 파일 1개.

콘솔 출력(선택): 총 열차 수, 요일별 카운트 합, 역별 카운트 합 등 요약.
