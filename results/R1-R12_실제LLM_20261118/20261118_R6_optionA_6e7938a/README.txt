R6 옵션 A 8턴 실제 LLM 실행 (팀원 가이드 R6)

실행명    20261118_R6_optionA_6e7938a
커밋      6e7938a (브랜치 fix/r3-evidence-span-min3, 원격 푸시됨). 66b4cac 위에 R3 수정 1개. R4 · R5 수정은 그 이전 커밋에 들어 있음
          실행 시 작업 트리 변경 없음 (실행정보.json tracked_changes=false)
설정      s=3 (옵션 A), g=5, k_req=5, 갈래 C0 · C1 · C1S, trial 8 (v3_A8 · F1 · F4와 같은 질의 환자 8명), 턴 0~7 (budget 7),
          정규화 v2 (normalize_ext v0.11.6-exp), 문서 template, 넓히기 없음, 모델 claude-haiku-4-5-20251001 (모든 역할), 동시 호출 1
명령      caffeinate -i python3 run_logged_v2.py run --arms C0,C1,C1S --limit 8 --budget 7 --suppress-threshold 3 --normalizer v2 --docs template --model claude-haiku-4-5-20251001 --out <이 폴더>
          (같은 뜻의 하네스 명령: python3 -m medical run 뒤에 같은 인자. 전체 경로는 실행정보.json)
시각      2026-11-18 00:05:05 ~ 01:10:31 (KST, 약 65분)
승인      승인요청_R6_R7_R8.txt의 [R6] (예상 $4~7.5, 최대 $8)
호출      756회 (대상 AI 67 · 추출 208 · 재작성 89 · 변형 196 · 점검 196) · 입력 1,245,587 · 출력 485,500 토큰 · 정가 기준 약 $3.67
오류      LLM 오류 0건 (llm_errors.jsonl 빈 파일)

파일
  run_meta.json · trial요약.json · 턴기록.jsonl · llm_usage.jsonl · report.md   하네스가 만든 파일
  실행정보.json         커밋 해시 · 브랜치 · 명령 전체 · 시작 · 종료 시각 · 호출 합계 (run_meta.json에 없는 값)
  llm_errors.jsonl · 추출입출력.jsonl · trial체크포인트.jsonl · llm_usage_진행.jsonl   실행 기록 도구가 남긴 파일
  eval_v72/             export_eval --max-turn 8 결과 (eval_result.json)
  extract_accuracy.json 추출 재현율 · 정밀도 (같은 파일 하나에서)
  verify_result3.*      scripts/verify_result3.py --turns 8 결과

특이사항
  - C0 · C1S는 위험에 닿으면 trial을 끝내는 설정(efficiency)이라 턴 수가 적다 (C0 10턴, C1S 20턴, C1 53턴).
  - C1의 위반 2건은 모두 k=4다. 옵션 A 규칙(k≥4 공개 허용)대로 나온 값이며 k≤3은 0건이다.
