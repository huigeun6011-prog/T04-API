# lineC_final 기준 (실행 전 고정)

사용자 결정: pool3(imputed 20개 표시 유지)를 최종 시간표 후보로 채택. `lineC_pool3/candidate_arrival_events_pool3.csv`는 그대로 두고 `lineC_final/candidate_arrival_events_final.csv`를 새로 만든다.

열: train_id, direction, stationID, arrival_time(시각만, HH:MM:SS), imputed, impute_evidence, observed_peak_within_45s, lag_out_s, lag_in_s, tail_unsupported_flag, group(weekday), 새 열 low_signal, structure_status, refuted_share_cell.
- low_signal = 그 열차의 (방향, 첫 역 도착 시각 시간대)가 분석 구간 밖(정의는 `outputs/hangzhou/lineC_pos2/criteria.md`).
- structure_status = 그 행 역이 속한 구간의 (방향, 시간대, 구간) 칸 판정(새 종합 규칙, 심지 않은 데이터): 지원 / 반박(전 구간 운행과 모순 없음) / 알 수 없음 / 미확인(분석 구간 밖).
- refuted_share_cell = 같은 (방향, 시간대) 6개 구간 중 반박 칸 비율.
- 열차는 구간 밖이어도 삭제하지 않는다.
