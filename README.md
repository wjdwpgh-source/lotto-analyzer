# 로또 통계 분석 & 번호 추천기

과거 통계 분석 도구입니다. 당첨 번호를 예측하거나 당첨 확률을 높이지 않습니다.

## 데이터 구조
- `data/lotto645.json` : 운영 데이터 (1~1243회, 이후 자동 추가)
- `data/seed/lotto645_seed.json` : 복구용 시드 (공개 저장소 3곳 다수결로 검증, 1~1243회)
- `scripts/update.py` : 갱신/대조/복구 스크립트
- `.github/workflows/update-data.yml` : 일 09:00, 일 21:00, 월 09:00(KST) 자동 실행

## 수집 규칙
- 출처 3곳(kysmk1987, JunKwon91, uriseozz의 공개 저장소) + 동행복권 조회(보조)
- 신규 회차는 **2곳 이상이 같은 값일 때만** 추가. 1곳뿐이면 대기, 값이 갈리면 실행이 실패로 표시됨(알림)
- 저장 전 검증(회차 연속, 번호 범위, 중복, 추첨일) 통과 시에만 교체하고, 교체 전 자동 백업

## 복구 (Actions 탭 → update-data → Run workflow → mode 선택)
- `audit` 대조 보고 / `audit-fix` 불일치 교정 / `seed` 시드 복원 / `rebuild` 전체 재구성
