# 지도 이미지 Worker

`worker.mjs`는 Kakao 지도 REST API의 고정 이미지 경로만 호출합니다. 브라우저에는 이미지와 검증한 공개 지도 매개변수만 반환합니다. REST 키는 Cloudflare의 기존 암호화 Secret `KAKAO_MAP_API_KEY`를 사용하며 저장소·프런트 설정·요청 URL에 넣지 않습니다.

- `GET /api/health`: 비밀 값이 없는 상태 응답
- `GET /api/map-image?center=127.3845,36.3504&lv=6&width=1024&height=640&scale=1`: PNG/JPEG 이미지
- `center`: WGS84 경도,위도, `lv`: 1~15, `width`: 1~2048, `height`: 1~1024, `scale`: 1~2(기본 1)
- 좌표 정렬 검증용 선택 매개변수 `marker=경도,위도`를 최대 5개 반복할 수 있습니다. 좌표만 허용하며 upstream 마커 옵션 문자열은 서버에서 고정합니다.

배포 전 `wrangler.jsonc`의 `ALLOWED_ORIGINS`에 실제 정적 웹의 정확한 origin을 쉼표로 구분해 넣습니다. origin에는 경로와 마지막 `/`를 넣지 않습니다. 현재 설정과 코드 기본값은 `https://huigeun6011-prog.github.io`와 로컬 확인용 5501 포트를 허용합니다. 대시보드에서 파일만 배포해도 같은 기본값을 쓰며, 환경 변수 `ALLOWED_ORIGINS`가 있으면 그 값으로 대체합니다(빈 문자열은 모두 거부). 등록하지 않은 origin·`null`·Origin 헤더 없는 이미지 요청은 403입니다. CORS는 브라우저의 출처 제한이며 REST 키 대신 이용자 인증을 제공하지는 않습니다.

고정 HTTPS upstream, `Authorization` 헤더 인증, 리디렉션 차단, 입력 범위·중복/알 수 없는 매개변수 차단, 10초 제한, 16MiB 이미지 제한과 PNG/JPEG 서명을 적용합니다. upstream 본문·헤더·예외는 오류 응답이나 로그에 복사하지 않습니다. Worker 코드는 로그를 출력하지 않으며 설정 파일도 observability를 끕니다. 요청·응답 캐시는 `no-store`입니다.

검증: `npm test` (이 폴더에서 실행). 배포 명령은 `npx wrangler deploy --config wrangler.jsonc`이며, 계정 인증과 기존 Secret 유지 여부를 확인한 뒤 실행합니다. 프런트에는 Worker 기본 URL만 설정합니다. Python·원본 `web/`·`.env`는 사용하거나 수정하지 않습니다.

배포 후 실제 이미지 정렬 검증은 저장소 루트에서 `node scripts/check_map_proxy.mjs --output-dir outputs/map-proxy-qa`로 한 번 실행합니다. 키 없이 Worker에 최대 4개의 이미지 요청만 보내고, lv 2/3/4 및 scale 1/2의 크기·CORS를 확인합니다. 공식 마커는 지도 중심과 WTM 기준 동쪽·북쪽 100m에 놓으며, 저장한 `report.json`·PNG와 `index.html`의 청록색 십자선으로 마커 끝점과 프런트 좌표의 실제 일치를 확인합니다. 자동 색상 후보는 참고용이며 실제 끝점 일치 판정은 이미지 확인 뒤 기록해야 합니다. 이 검증 프로그램의 로컬 테스트는 `node --test scripts/check_map_proxy.test.mjs`입니다.
