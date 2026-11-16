# 대전 한적 나들이 추천 프로젝트

대전도시철도1호선의 예상 이동 혼잡과 실제 장소를 조합해 시간·이용역·목적지를 추천하는 로컬 웹 프로젝트입니다. **다음 AI는 [인수인계](docs/HANDOFF.md)를 먼저 읽으세요.** 기준2026-11-16입니다. 실험·재학습·모델교체는 사용자 지시가 있을 때만 합니다.

## 현재 동작

- 실제 POI548행(좌표532곳)을 Kakao지도·목록·필터에 연결했습니다. 좌표없는 산책로11곳은 텍스트로 표시합니다.
- 출발점·운행일·05~24시 범위·카테고리·한산함/거리 비중(10%단위)을 고르고 추천 버튼으로 Python API를 호출합니다.
- Open-Meteo 실제 시간별 날씨를 무키로 조회하며 캐시·호출 간격을 적용합니다. 더미 장소·날씨·혼잡도 계산은 제거했습니다.
- API는 `outputs/load_predictor.joblib`과 시간표로 이동 가능한 열차·이용구간·장소 후보를 계산합니다. 장소 방문객수를 예측하지 않습니다.

## 모델 상태와 한계

production HGB모델은731운행일·3,733,691행으로 학습했습니다. 운행일2024-11-01~2026-11-01이며 마지막24시는 실제2026-11-02 00시 버킷입니다. 날짜holdout MAE20.14명/R²0.8766은 **추정라벨 재현성**이며 실제승객 정확도가 아닙니다. 배포파일은 평가후 전체기간으로refit했습니다.

Adam으로 GT분배율을 추정하는 단계와 HistGradientBoosting으로 미래값을 예측하는 단계는 다릅니다. production은 이전200회solver의 clamp·종점0보정 라벨입니다. 이후 배분소실 수정/raw·slack 기록/1000회 후보와3가정 실험을 만들었으나 production에는 적용하지 않았습니다. 현재 GT생성코드를 기본실행하면 production과 다른 방법으로 생성됩니다.

실제피크19사례에는 약376명의 큰MAE가 남았고 추천순위도 미검증입니다. [방법론](docs/AI/METHODOLOGY.md)과 [실험결과](outputs/diagnostics/assumption_ablation/report.md)를 참고하세요.

**역 좌표:** `web/app.js`의 22개 역 좌표는 [VWorld 보정표](docs/AI/STATION_COORDINATES.md)와 일치합니다(2026-11-16 대조 확인). API도 이 좌표를 읽습니다. 브라우저 지도·전체UX 시각검증은 하지 않았습니다.

## 로컬 실행

**Kakao 키 설정:** `web/config.example.js`를 `web/config.local.js`로 복사하고 JavaScript 키를 넣습니다. `config.local.js`는 gitignore 대상이라 커밋되지 않습니다. 키가 없으면 지도 대신 노선도 대체 화면이 표시됩니다.

프로젝트루트에서 Python3.12 환경 `.venv/Scripts/python.exe`를 사용합니다. 먼저8000/5500의 기존서버를 확인하고 중복기동하지 마세요.

```powershell
Get-NetTCPConnection -LocalPort 8000,5500 -State Listen -ErrorAction SilentlyContinue
.venv/Scripts/python.exe prediction_api.py --port 8000
```

별도터미널의 정적서버가 필요할 때만 실행합니다(VS Code Live Server5500 사용중이면 불필요).

```powershell
.venv/Scripts/python.exe -m http.server 5500 --bind 127.0.0.1
```

페이지: [127.0.0.1:5500/web/index.html](http://127.0.0.1:5500/web/index.html).8000은예측API입니다. 공개배포·ONNX·브라우저직접joblib추론은 구현하지 않았습니다.

## 문서

- [인수인계·확정요구·백업·남은일](docs/HANDOFF.md), [로드맵](ROADMAP.md)
- [방법론](docs/AI/METHODOLOGY.md), [모델 개요](docs/AI/MODEL.md), [웹 연결](docs/AI/WEB_INTEGRATION_DESIGN.md)
- [추출기](docs/AI/EXTRACT_TRAIN_LOADS.md), [승하차](docs/AI/SUBWAY.md), [날씨](docs/AI/WEATHER.md), [POI](docs/AI/POI_COLLECTION_TASK.md)
- [가정](docs/ASSUMPTIONS.md), [결정](docs/DECISIONS.md), [실패 기록](docs/FAILURES.md)

지도는Kakao이고 `best_model.pt`는 이전모델입니다. `.env`의 키값을 출력하거나 문서·로그에 복사하지 마세요.
