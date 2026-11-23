# 대전 한적 나들이 추천 프로젝트

대전도시철도 1호선의 예상 이동 혼잡과 실제 장소(POI)를 조합해 덜 붐비는 시간·이용역·목적지를 추천하는 웹 프로젝트입니다. 기준일은 2026-11-23입니다.

**다음 AI는 [인수인계](docs/HANDOFF.md)를 먼저 읽으세요.** 실험·재학습·모델 교체는 사용자 지시가 있을 때만 합니다. `.env`의 키 값은 출력하거나 문서·로그에 복사하지 않습니다.

## 구성

| 구성 | 위치 | 설명 |
|---|---|---|
| 정적 웹 (현행 공개용) | `static-web/` (소스 `static_src/`) | 브라우저 JavaScript가 모델 예측·추천을 직접 계산합니다. Python 서버가 필요 없고 GitHub Pages로 배포합니다. 추천, 분석, 모델 소개, '오늘의 정보판' 탭이 있습니다. |
| 기존 Python 웹 | `web/`, `prediction_api.py` | 로컬 실행용으로 보존한 원본입니다(Kakao JS SDK 사용). |
| 지도 이미지 Worker | `worker/` | Kakao REST 키를 Worker Secret에만 두고 지도 이미지를 프록시합니다([worker/README](worker/README.md)). |
| T04 정보판 | `scripts/t04_daily_record.mjs`, `static-web/data/t04/` | 대전 1호선의 운행일별 실측 승하차와 7일간 비·눈 정보를 표시합니다. 과제용 조회 기록은 로컬에서 수동으로 남깁니다. |
| 모델·자료 | `outputs/load_predictor.joblib`, `data/` | production HGB 모델과 승하차·날씨·시간표·POI 자료입니다. |

## 실행

**정적 웹 확인** — 프로젝트 루트에서 `run_static.bat`을 실행합니다. Node가 있으면 공개용 데이터를 동기화하고, `.venv` 또는 시스템 Python으로 정적 파일 서버를 시작합니다. 직접 실행할 때는 다음 순서입니다.

```powershell
node scripts/sync_static_data.mjs
python -m http.server 5501 --bind 127.0.0.1 --directory static-web
```

접속은 `http://127.0.0.1:5501/`입니다. `file://`로 직접 열지 마세요. 현재 모델에서 정적 웹을 다시 만들거나 Python과의 동등성을 확인할 때만 다음을 실행합니다(재학습 없음).

```powershell
.venv/Scripts/python.exe scripts/build_static_web.py
.venv/Scripts/python.exe scripts/validate_static_web.py
```

**기존 Python 웹** — 프로젝트 루트에서 `.venv`에 의존성을 설치한 뒤 `run_web.bat`을 실행합니다. 로컬 지도에 Kakao JavaScript 키를 쓰려면 `web/config.example.js`를 `web/config.local.js`로 복사해 설정합니다. 키가 없으면 노선도 대체 화면이 표시됩니다. 직접 실행할 때는 5500 포트의 기존 서버를 먼저 확인합니다.

```powershell
Get-NetTCPConnection -LocalPort 5500 -State Listen -ErrorAction SilentlyContinue
.venv/Scripts/python.exe prediction_api.py --port 5500
```

페이지는 `http://127.0.0.1:5500/web/index.html`입니다.

**Node 테스트** — `node --test scripts/`(Node 22 기준). Worker는 `worker/`에서 `npm test`를 실행합니다.

자세한 실행·배포 절차, 지도 설정, 파일별 역할은 [인수인계](docs/HANDOFF.md)(§8~§9, §12)와 [웹 연결](docs/AI/WEB_INTEGRATION_DESIGN.md)을 참고하세요.

## T04 정보판과 배포

- **승하차** — `#t04`에서 날짜를 고르면 기준일을 포함한 7일의 실측 총 승하차와 비·눈을 그래프와 표로 봅니다. 운행일 D는 D일 05~23시와 D+1일 00시를 합산합니다. 과제용 `daily.json`은 조회한 KST 날짜별 기록이며, 날짜 선택 그래프의 과거 이력은 `business_days.json`에서 가져옵니다.
- **수동 기록** — 루트 `.env`에 `SUBWAY_API_KEY`를 설정하고 Node 22에서 `node --env-file=.env scripts/t04_daily_record.mjs all`을 실행합니다. 승하차 원본이 이미 있으면 재사용하므로, 실행 날짜에 실제로 API를 다시 조회했다는 확인에는 캐시 사용 여부를 먼저 확인해야 합니다. 명령별 동작과 검증 방법은 [인수인계 §12](docs/HANDOFF.md#12-외부-과제-요구-aleph-t04-외부-데이터-모니터링-대시보드-2026-11-23-정리)에 있습니다.
- **Pages** — 일일 수집 워크플로는 삭제했습니다. 배포는 `pages.yml`이 담당하며, `data/raw/`에서 공개용 날씨와 기록에 필요한 XML을 만들어 `static-web/`만 게시합니다.

## 모델 한계

production 모델은 2026-11-19부터 **열차 단위 OD 라벨 61일**로 학습한 HistGradientBoosting 모델입니다([D-027](docs/DECISIONS.md)). 검증 MAE 23.94명/R² 0.838은 **추정 라벨 재현성**이며 실제 승객 정확도가 아닙니다.

- **절대 인원 수는 신뢰할 수 없습니다.** 수준은 기준 분포 q가 정하며 검증되지 않았습니다. 그래서 웹은 인원 수치를 보이지 않고 같은 구간의 시간대 상대 순위만 보입니다([D-028](docs/DECISIONS.md)).
- 믿을 수 있는 것은 시간대·역의 상대 순서뿐이며 근거는 항저우 C선 정답 비교입니다. 열차 한 대 단위 구분은 복원되지 않았습니다.
- 대전 자체 검증은 실제 피크 18건뿐이며 한산한 쪽 순서는 검증되지 않았습니다([E-40](docs/EXPERIMENTS.md)).
- 장소 방문객 수나 장소 자체의 혼잡도는 예측하지 않습니다. 도보 시간은 직선거리 어림이고 운영시간·실제 보행 경로는 없습니다.
- 지도·선로 정합, 모바일·터치 환경은 최종 확인하지 않았습니다.

이전 production(Adam 라벨 731일)은 `outputs/backup_before_od_swap_20261119/`와 git 이력에 있고, 되돌리는 법은 [HANDOFF §4](docs/HANDOFF.md)에 있습니다. 상세는 [방법론](docs/AI/METHODOLOGY.md)과 [모델 개요](docs/AI/MODEL.md)를 보세요.

## 문서

**현황·계획**
- [인수인계](docs/HANDOFF.md): 확정 요구, production·후보, 파일 안내, T04 과제 요구와 구현 상태(정본)
- [로드맵](ROADMAP.md): 진행 중인 일, 완료 기록, 다음 후보
- [리뷰](docs/REVIEW.md): D-028~D-030 변경에 대한 코드 리뷰 기록

**기록**
- [가정](docs/ASSUMPTIONS.md), [결정](docs/DECISIONS.md), [실패 기록](docs/FAILURES.md), [시도·실험 기록](docs/EXPERIMENTS.md)

**모델·방법**
- [방법론](docs/AI/METHODOLOGY.md), [모델 개요](docs/AI/MODEL.md), [재차인원 역산 실행 지침서](docs/AI/LOAD_ESTIMATION_RUNBOOK.md), [열차별 재차 추출기](docs/AI/EXTRACT_TRAIN_LOADS.md)
- 항저우 태그 실험: [시간표 복원 지침](docs/AI/HANGZHOU_TIMETABLE_BRIEF.md)(보류, [E-22](docs/EXPERIMENTS.md)), [OD 시험 메모](docs/AI/HANGZHOU_OD_TEST_BRIEF.md)

**웹·자료**
- [웹 연결·정적 웹](docs/AI/WEB_INTEGRATION_DESIGN.md), [역 좌표](docs/AI/STATION_COORDINATES.md), [지도 Worker](worker/README.md)
- [승하차](docs/AI/SUBWAY.md), [시간별 승하차(이전 경로)](docs/AI/SUBWAY_HOURLY.md), [날씨](docs/AI/WEATHER.md), [POI 수집](docs/AI/POI_COLLECTION_TASK.md), [자료 흐름도](docs/AI/PROJECT_DATA_FLOW.svg)
