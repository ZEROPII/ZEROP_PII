# 전달 묶음 코드 (수정 금지)

`의료데이터 전환/개발자_전달/02_코드/`(2026-10-09)의 파일을 그대로 옮겼습니다. 고칠 일이 생기면 이 폴더를 바꾸지 말고 전달한 쪽에 알려 새 판을 받습니다. 받은 그대로인지 확인하려면 아래 해시와 비교합니다(`sha256sum medical/bundle/*.py`).

| 파일 | 역할 | SHA-256 |
| --- | --- | --- |
| `kcalc.py` | 사건 단위 누적 후보 수(k). 같은 사건 조건 동시 충족, 고유 환자 집계, 충돌 격리, ZERO_MATCH | `6a61b314c074ea008a0f8ab3a220c23ee8eb40ad507274e7d739c8073410a4ec` |
| `normalize_bridge.py` | Observation → 노드·MAPPED/PENDING/UNMAPPED (v0.9.1) | `6393204091bf3b20b86577d1b782726c6950d1dcb38a2f4ddfc9ad4497215b69` |
| `seed_select.py` | Seed 적용 조건(`required_state_condition`) 평가, 자리표시자 채우기 | `f6bd9888ef8d935cf29c840999a0bb489b311ca234a3b3652bdae3b941509f5e` |
| `check_rag_facts.py` | RAG 문서 사실표를 원자료와 대조 | `2e19a96763247b4144e4979e05cf058b63aab7f3f3c37ed5f2302138fa2d1b29` |
| `check_registry.py` | Seed Registry 구조·교차 검사 | `c8501b536608f9620367eed39418a2529266771ebc5ca062591b6e8031868d28` |
| `harness_reference.py` | 하네스 명세의 참조 구현(방어 없는 기준 조건만). `medical/`의 실행 코드는 이 파일을 나눠 옮기고 C1·C1S를 더한 것이며, 참조용으로만 둡니다 | `b5ccd1453cdf34c7b230cce7cdd0e654b79a2798e952869705c4b1a2555300cb` |

데이터(`data/medical/`)도 같은 묶음의 `01_데이터`, `03_Seed`에서 옮겼습니다. `노드_v0.9.csv`·`사건연결표_v0.9.csv`는 `main`의 `risk_defender/data/`에 있는 파일과 내용이 같습니다(git blob 해시 동일).
