# 의료 대화형 AI 시나리오 (Synthea 합성 환자) 실행 패키지
#
# 근거 문서 (docs/medical/)
#   대상AI_하네스_평가_명세_v0.1.md : RAG 문서, 대상 AI, 질의 환자, 변형기, 추출기, 종료, 기록, Validated k
#   추출_정규화_명세_v0.3.md        : Observation 필드, 정규화·commit 규칙
#   설계보고서_구현발췌.txt          : SynthPAI용 원설계 중 구현에 필요한 절
#
# 전달 묶음 코드(medical/bundle/)는 고치지 않고 불러 쓴다.
#   kcalc.py           : 사건 단위 누적 후보 수(k) — 의료 실험의 공식 k는 이것 하나로만 계산한다
#   normalize_bridge.py: Observation → 노드·MAPPED/PENDING/UNMAPPED
#   seed_select.py     : Seed 적용 조건 평가와 자리표시자 채우기
#
# Defender 판정 정책(허용/일반화/억제, 기준 5·3)은 risk_defender(이유진 파트)의 규칙을 그대로 따르고,
# 각 판단에 쓰는 k만 kcalc로 계산한다 (medical/defense.py). risk_defender 코드는 수정하지 않는다.
