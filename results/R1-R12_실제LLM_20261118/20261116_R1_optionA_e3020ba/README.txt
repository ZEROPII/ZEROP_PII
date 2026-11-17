R1 옵션 A 실행 원자료 (팀원 가이드 R1, LLM 재실행 아님)

실행명    v3_A8 (2026-11-16 실행 폴더를 그대로 복사함. 원래 위치 ~/Downloads/팀원전달_v3보정_20261116/v3_A8 는 건드리지 않음)
커밋      e3020ba (브랜치 exp/turn0-normalize). 원격 HEAD 152d74a의 바로 앞 커밋이라 원격 이력에 있음
          run_meta.json에는 커밋 해시가 없고 파일별 sha256(code 항목)이 있다.
          e3020ba의 같은 파일 46개와 모두 일치한다 (2026-11-17 확인. ae54315와는 4개, 152d74a와는 8개가 다름)
설정      s=3 (run_meta config.suppress_threshold=3, 그 커밋의 기본값), g=5, k_req=5, 갈래 C1, trial 8, budget 10 (턴 0~10),
          정규화 v2 (normalize_ext v0.11.5-exp), 문서 template, widen 없음,
          모델 claude-haiku-4-5-20251001 (llm_usage.jsonl 664건 모두 같은 모델)
명령      caffeinate -i python3 ~/Downloads/팀원전달_v3보정_20261116/run_logged.py run --arms C1 --limit 8 --budget 10 --normalizer v2 --docs template --out ~/Downloads/팀원전달_v3보정_20261116/v3_A8
시각      2026-11-16 16:53 ~ 17:52 (KST, 약 59분)
승인      2026-11-16 확인 가이드 6번 R1 (양승준 · 사용자 승인 후 실행)
호출      664회 (대상 AI 67 · 추출 192 · 재작성 77 · 변형 164 · 점검 164) · 입력 1,201,736 · 출력 402,373 토큰 · 정가 기준 약 $3.21
질의 환자 F1 · F4 · R6와 같은 8명

파일
  run_meta.json · trial요약.json · 턴기록.jsonl · 추출입출력.jsonl · llm_usage.jsonl · report.md   실행이 만든 파일 그대로
  llm_errors.jsonl   빈 파일. LLM 오류가 0건이었고, 그때 실행 도구(run_logged.py)는 오류가 있을 때만 오류 파일을 만들어서
                     전달할 때 빈 파일로 만들었다
  eval_v72/          export_eval 결과 (최종 커밋 6e7938a의 평가 코드, LLM 없음). eval_result.json = 턴 0~7, eval_result_maxturn10.json = 턴 0~10
  extract_accuracy.json  추출 재현율 · 정밀도 (최종 커밋 코드, LLM 없음)
  llm_usage_진행.jsonl · trial체크포인트.jsonl · 사실표.csv · RAG문서.jsonl · 코호트분리.csv   실행 도구 · 저장소가 만든 보조 파일

특이사항
  - 이 실행은 budget 10이다. 8턴(턴 0~7) 값은 eval_v72/eval_result.json으로 본다. R6는 처음부터 턴 0~7로 돈다.
  - 사례 A가 질의 환자(OTHER)로 잡힌 trial은 없다 (e3020ba는 사례 A 수정 a6b8516 이후 커밋).
