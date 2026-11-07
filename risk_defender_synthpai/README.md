# risk_defender_synthpai — SynthPAI판 risk_defender 고정 사본

main(cb5b23b)의 `risk_defender/`는 의료(Synthea 576명) 판으로 바뀌었다 (`to_age_band` 삭제, 프로필 구조 변경 등).
이 저장소의 SynthPAI 파이프라인(`adapters/`·`orchestrator/`·`validation/`·`normalizer/`·`ontology/`)과 논문 실험은
그 전 판(커밋 ac1407a, "Refine defender: suppress directly when k ≤ suppress_threshold")을 쓴다.

그래서 그 판을 이 폴더에 그대로 고정해 두고 SynthPAI 쪽 코드는 여기서 import한다.

- 원본: `git show ac1407a:risk_defender/<파일>` — 코드는 그대로이고, 바꾼 것은 두 가지뿐이다.
  1. `demo.py`의 절대 import 이름(`risk_defender.` → `risk_defender_synthpai.`)
  2. `demo.py`의 데이터 경로: SynthPAI 원자료는 예전처럼 `risk_defender/data/user_bot_profiles_300*.json`에서 읽는다 (커밋 금지 파일).
- 의료 시나리오(`medical/`)는 이 사본을 쓰지 않는다. 판정 정책은 main `risk_defender`와 같은 규칙을 kcalc 위에서 다시 구현했다 (`medical/defense.py`).
- risk_defender 담당자(이유진)가 SynthPAI판을 따로 유지하기로 하면 이 폴더는 지운다.
