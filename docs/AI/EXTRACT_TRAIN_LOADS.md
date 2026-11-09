# 열차별 재차인원 궤적 일괄 추출기 매뉴얼 (`extract_train_loads.py`)

본 문서는 학습된 모델[`outputs/load_predictor.joblib`]과 열차 운행 시각표, 날짜 및 날씨 데이터를 결합하여 **특정 날짜(또는 기간)에 운행하는 모든 열차의 정차역별 재차인원 궤적(Trajectory)을 일괄 추출하는 스크립트[`extract_train_loads.py`]**의 역할, 내부 아키텍처, 그리고 사용법을 기술합니다.

---

## 1. 스크립트 역할 및 목적

- **역할**: 대전도시철도 1호선에서 특정 일자에 운행하는 **모든 열차(하루 약 242대, 정차 횟수 약 5,281회)**에 대해, 열차가 역을 통과할 때마다 승객이 몇 명 타고 있는지(`load`)와 혼잡도(`congestion`)를 전수 계산하여 구조화된 파일(JSON/CSV)로 추출합니다.
- **기존 시뮬레이션과의 차이**:
  - 과거 단순 1/n 분배 방식(`F-001`, `train_load_simulation.py`)에서 발생하던 종점 잔류 오차(상행 $+26$명, 하행 $-23$명) 없이, **학습된 GBDT 모델을 통해 실제 출퇴근 피크 및 방향성 비대칭을 정밀하게 반영한 재차인원을 산출**합니다.
  - 종점 도착 시 승객 전원 하차에 따른 잔류 인원 0 처리로 물리적 일관성을 유지합니다.
- **초고속 연산**: 하루 전체 정차 데이터(5,281건)를 하나의 배치(Batch)로 구성하여 모델에 전달하므로, **하루치 전수 추출에 단 0.2~0.3초**밖에 걸리지 않습니다.

---

## 2. 참조 데이터 및 의존 관계

| 구분                      | 파일 경로                                                | 설명                                         |
| :------------------------ | :------------------------------------------------------- | :------------------------------------------- |
| **예측 모델**             | `./outputs/load_predictor.joblib`                        | 2단계에서 학습된 재차인원 예측 모델          |
| **운행 시각표 (개편 전)** | `./data/processed/subway_time/subway_time_20250930.json` | 2026-03-30 이전 시각표 (및 이후 휴일 시각표) |
| **운행 시각표 (개편 후)** | `./data/processed/subway_time/subway_time_20260330.json` | 2026-03-30 이후 평일 개편 시각표             |
| **기상 데이터**           | `./data/raw/weather/{날짜}.json`                         | 해당 일자 1시간 단위 기온, 강수량, 적설량    |

---

## 3. 내부 처리 파이프라인

```
[입력: 날짜(YYYY-MM-DD)]
        │
        ▼
1. 캘린더 판정 ──> 평일/주말 판정 및 법정공휴일 세트 대조 (자동 휴일 전환)
        │
        ▼
2. 시각표 로드 ──> 2026-03-30 기준 개편 전/후 분기 (휴일은 20250930 폴백)
        │
        ▼
3. 날씨 매칭   ──> weather/{날짜}.json에서 시간대별 기온/강수/적설 로드 (결측 시 평년값 방어)
        │
        ▼
4. 배치 구성   ──> 하루 242대 열차 × 정차역 = 약 5,281개 정차 시점 행렬 구성
        │
        ▼
5. 모델 추론   ──> model.predict(X_df) 일괄 수행 (소요시간 ~0.05초)
        │
        ▼
6. 궤적 조립   ──> 열차 단위로 정차역 순서대로 재차인원 정렬, 종점 잔류 0 보정
        │
        ▼
[출력: ./outputs/train_loads/train_load_{날짜}.json (및 .csv)]
```

---

## 4. CLI 사용법 (명령어 예시)

터미널(PowerShell/CMD)에서 아래 명령어로 실행할 수 있습니다.

### ① 특정 단일 날짜 추출 (기본 JSON 저장)

```powershell
python extract_train_loads.py --date 2025-11-04
```

- 출력: `./outputs/train_loads/train_load_2025-11-04.json` 생성 (약 0.2초 소요)

### ② JSON과 함께 분석용 CSV 파일도 동시 생성

```powershell
python extract_train_loads.py --date 2025-11-04 --save-csv
```

- 출력: `train_load_2025-11-04.json` 및 `train_load_2025-11-04.csv` 동시 생성

### ③ 특정 기간(일주일 / 한 달 등) 연속 추출

```powershell
python extract_train_loads.py --start-date 2026-10-01 --end-date 2026-10-07
```

- 출력: 지정한 7일간의 파일(`train_load_2026-10-01.json` ~ `train_load_2026-10-07.json`)이 순차적으로 생성됩니다.

### ④ 출력 경로 및 모델 경로 커스텀 지정

```powershell
python extract_train_loads.py --date 2026-11-15 --output-dir ./my_outputs --model ./outputs/load_predictor.joblib
```

---

## 5. CLI 인자 목록 (Arguments)

| 옵션명         | 단축형 |              기본값               | 설명                                                 |
| :------------- | :----: | :-------------------------------: | :--------------------------------------------------- |
| `--date`       |   -    |              `None`               | 추출할 단일 날짜 (`YYYY-MM-DD`). 미지정 시 오늘 날짜 |
| `--start-date` |   -    |              `None`               | 기간 추출 시작 날짜 (`YYYY-MM-DD`)                   |
| `--end-date`   |   -    |              `None`               | 기간 추출 종료 날짜 (`YYYY-MM-DD`)                   |
| `--model`      |   -    | `./outputs/load_predictor.joblib` | 사용할 학습 모델 경로                                |
| `--output-dir` |   -    |      `./outputs/train_loads`      | 결과 파일이 저장될 디렉토리                          |
| `--save-csv`   |   -    |              `False`              | 플래그 설정 시 테이블 형태의 CSV 파일도 함께 생성    |

---

## 6. 출력 파일 스키마 (Output Schema)

### 6.1 JSON 파일 구조 (`train_load_{date}.json`)

최상위 메타데이터 아래에 열차별 시뮬레이션 배열(`simulations`)이 포함되어 있으며, 기존 프로젝트의 `outputs/train_load_2025-11-04.json`과 구조적으로 완벽히 호환됩니다.

```json
{
  "date": "2025-11-04",
  "day_type": "평일",
  "train_count": 242,
  "total_stops": 5281,
  "model_version": "HistGradientBoostingRegressor",
  "simulations": [
    {
      "train_id": "평일-상행-001",
      "day_type": "평일",
      "direction": "상행",
      "origin": "반석",
      "destination": "판암",
      "stops": [
        {
          "station": "반석",
          "time": "05:30",
          "hour": "5",
          "load": 38.4,
          "congestion": "여유",
          "is_origin": true,
          "is_destination": false,
          "temp": 4.1,
          "precip": 0.0
        },
        {
          "station": "지족",
          "time": "05:32",
          "hour": "5",
          "load": 47.7,
          "congestion": "여유",
          "is_origin": false,
          "is_destination": false,
          "temp": 4.1,
          "precip": 0.0
        },
        ...
        {
          "station": "판암",
          "time": "06:10",
          "hour": "6",
          "load": 0.0,
          "congestion": "여유",
          "is_origin": false,
          "is_destination": true,
          "temp": 4.5,
          "precip": 0.0
        }
      ]
    }
  ]
}
```

### 6.2 CSV 파일 구조 (`train_load_{date}.csv`, `--save-csv` 사용 시)

데이터 분석 및 시각화(Pandas, Tableau, Excel)에 적합한 2차원 테이블 형식입니다:

| 칼럼명           | 데이터 타입 | 설명                                                           |
| :--------------- | :---------: | :------------------------------------------------------------- |
| `date`           |   문자열    | 운행 일자 (`2025-11-04`)                                       |
| `day_type`       |   문자열    | 요일 구분 (`평일` 또는 `휴일`)                                 |
| `train_id`       |   문자열    | 열차 고유 식별자 (예: `평일-상행-001`)                         |
| `direction`      |   문자열    | 운행 방향 (`상행` 또는 `하행`)                                 |
| `station`        |   문자열    | 정차역 이름 (예: `시청`, `대전`)                               |
| `time`           |   문자열    | 정차 시각 (`05:30`)                                            |
| `hour`           |    정수     | 시간대 버킷 (`5` ~ `24`)                                       |
| `load`           |    실수     | **예측된 열차 내 재차인원 (명)**                               |
| `congestion`     |   문자열    | 혼잡도 등급 (`여유`, `보통`, `약간 혼잡`, `혼잡`, `매우 혼잡`) |
| `is_origin`      |   불리언    | 출발역 여부                                                    |
| `is_destination` |   불리언    | 종착역 여부                                                    |
| `temp`           |    실수     | 해당 시간대 기온 ($^\circ\text{C}$)                            |
| `precip`         |    실수     | 해당 시간대 강수량 ($\text{mm}$)                               |

---

## 7. 다른 AI 및 후속 작업자를 위한 안내

1. **대량 전수 추출**: 2년 치(약 730일) 전체를 추출하더라도 소요 시간은 약 2~3분 내외입니다 (`--start-date 2024-11-01 --end-date 2026-10-31`).
2. **시각화 및 대시보드 연동**: 생성된 `train_load_{date}.json`을 프론트엔드 차트나 히트맵(시간 $\times$ 역 재차인원 시각화)에 그대로 전달하여 사용할 수 있습니다.
3. **새로운 모델 배포 시**: 새 모델을 학습한 뒤 `outputs/load_predictor.joblib` 파일을 교체하기만 하면, 이 스크립트가 자동으로 최신 모델을 감지하여 재차인원을 추출합니다.
