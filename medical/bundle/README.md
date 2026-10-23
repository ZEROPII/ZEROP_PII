# 전달 묶음 코드 (수정 금지)

`개발자_전달/02_코드/`(2026-10-21 전달, v0.10)의 파일을 그대로 옮겼습니다. 고칠 일이 생기면 이 폴더를 바꾸지 말고 전달한 쪽에 알려 새 판을 받습니다. 받은 그대로인지 확인하려면 아래 해시와 비교합니다(`sha256sum medical/bundle/*.py`).

| 파일 | 역할 | SHA-256 |
| --- | --- | --- |
| `kcalc.py` | 사건 단위 누적 후보 수(k). 같은 사건 조건 동시 충족, 고유 환자 집계, 충돌 격리, ZERO_MATCH (v0.9.1, 10-09 판과 같음) | `6a61b314c074ea008a0f8ab3a220c23ee8eb40ad507274e7d739c8073410a4ec` |
| `normalize_bridge.py` | Observation → 노드·MAPPED/PENDING/UNMAPPED (v0.11.1: 분기 노드, 조사·괄호·'주' 접미사·도시 단독 표현) | `feed304c7d32ccdc8a83feb252f4f9b029f2eb11603546555aee13e3901fec54` |
| `seed_select.py` | Seed 적용 조건 평가, 자리표시자 채우기 (v0.13: 단서 두 개 행, 조사 맞추기, LINKED_EVENT) | `87be62466b5cf47b20d4e78400f52e3f908246e83548a72fe50340d0aff44b7a` |
| `check_rag_facts.py` | RAG 문서 사실표를 원자료와 대조 | `508a8b4af386e196b5cefd2d9852a19e739b0a95be0b67e9f54e9fe0e224f819` |
| `check_registry.py` | Seed Registry 구조·교차 검사 (v0.13) | `abab042c2681167651be61acc8a6ef691a4e67104815b32bf6f296b0ec5ee512` |
| `harness_reference.py` | 하네스 명세의 참조 구현 v0.2(방어 없는 기준 조건만, 현재 환자 맥락 패널). `medical/`의 실행 코드는 이 파일을 나눠 옮기고 C1·C1S를 더한 것이며, 참조용으로만 둡니다 | `52749c58fb4869f0c88af99206afaf2d0868788296fcb74c32c89fcbee212ab8` |

데이터(`data/medical/`)도 같은 묶음의 `01_데이터`, `03_Seed`에서 옮겼습니다.

- `노드_v0.10.csv`: v0.9에 PERIOD 분기(QUARTER) 단계를 더한 것 (71,692 노드).
- `사건연결표_v0.10.csv`·`표현_노드_매핑표_v0.10.csv`: v0.9와 내용이 같습니다(파일 해시 동일, git은 같은 blob으로 저장). 이름만 판에 맞췄습니다.
- v0.9·v0.7 파일은 이전 파일럿 실행 기록을 다시 계산할 때 쓰므로 남겨 둡니다.
- main의 `risk_defender/data/`는 아직 `노드_v0.9.csv`를 씁니다.
