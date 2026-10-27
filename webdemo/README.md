# 의료 POC 데모 웹앱

의료 데이터 전환 POC를 화면으로 돌려 보는 로컬 데모입니다. 중심은 보안 담당자 화면(보안 관제, 레드팀 실행, POC 결과)입니다. 같은 질문을 C0·C1·C1S 세 조건에 나란히 보내고, 원 응답과 Defender 판정과 k를 펼쳐 봅니다. '검사 대상 서비스' 화면은 우리 도구가 지키는 의료 AI 서비스를 의료진 입장에서 흉내 낸 것으로, Defender가 실제로 끼어드는 자리를 보여 주는 용도입니다.

API 키가 필요 없습니다. 대상 AI는 질문받은 단서를 검색 문서의 기록값으로 답하는 결정적 응답기(`medical/simulate.py`의 `OracleRoleLLM`)이고 LLM을 부르지 않습니다. `.env`도 만들 필요가 없습니다.

## 실행

저장소 맨 위 폴더에서 실행합니다.

```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r webdemo/requirements.txt              # 저장소 requirements + fastapi, uvicorn
python -m webdemo                                    # http://127.0.0.1:8000
```

켜는 데 10초 안팎 걸립니다(Synthea 576명 적재, 저장소 461명 문서 생성, kcalc 준비). 포트를 바꾸려면 `--port 8080`을 붙입니다. 엔진과 레드팀 실행 기록은 `runs/webdemo/`에 생기며 커밋하지 않습니다.

## 화면

| 화면 | 누가 보나 | 하는 일 |
| --- | --- | --- |
| 검사 대상 서비스 | 의료진 (보호 대상 서비스) | 질의 환자를 고르고 유사 사례를 검색한 뒤, 등록 질문 중 하나를 골라 보냅니다. 보내기 전에 그 질문이 사례별 후보 수를 얼마로 줄이는지 경고하고 다른 질문을 제안합니다. 답에서 넓힌 값과 뺀 값을 표시하고, 사례별 k와 공개 내역을 보여 줍니다. 원 응답과 원래 값은 이 화면으로 오지 않습니다. |
| 보안 관제 | 보안 담당자 | 같은 대화를 세 조건으로 나란히 봅니다. 사례 A의 턴별 k, 사례 5명의 현재 k와 정답 환자 대조(Validated k), 턴별 원 응답과 공개 응답, Defender가 단서마다 내린 판정과 그때의 k를 펼칩니다. 퍼저로 한 턴씩 또는 끝까지 자동 공격할 수 있습니다. |
| 레드팀 실행 | 보안 담당자 | `medical.experiment.run_experiment`를 그대로 배치로 돌리고 `medical.poc_analysis`로 집계합니다. 위반율(8턴·10턴), 턴별 누적 위반, 결정적 단서, Defender 판정 분포, 짝 비교 exact McNemar를 보여 줍니다. |
| POC 결과 | 모두 | 2026-10-23 POC의 4가지 설정(응답 수준 2 × 질문 선택 2) 집계입니다. `webdemo/data/poc_summary.json`(POC의 `poc_all.json` 복사본)을 읽습니다. |

화면 오른쪽 위의 보호 모드에서 의료진 화면에 보일 조건(C1·C1S·C0)을 고릅니다. 세 조건은 항상 함께 진행되고, 보호 모드는 어느 조건의 답을 보여 줄지만 바꿉니다.

## 발표에서 보여 주기 좋은 순서

처음 열면 보안 관제 화면이 나옵니다.

1. **검사 대상 서비스**에서 T0014(2세 남, Acute bronchitis, 처방 조회)를 고르고 검색합니다. 턴 0 답에서 이미 사례4의 약이 빠지고 사례5의 약이 넓혀진 것과 그 이유가 보입니다.
2. 시점 질문 하나를 고르면 "기록대로 답하면 사례1의 후보가 6명에서 1명으로 줄어든다"는 경고가 뜹니다. 보내면 C1은 그 값을 빼고 k = 6을 지킵니다.
3. **보안 관제**에서 같은 T0014로 새 대화를 시작해 "퍼저로 끝까지"를 누릅니다. 결과 보고 슬라이드 18과 같은 대화가 재현됩니다. 턴 5의 '관리 계획 시작일 2004'를 C1S는 빈 State로 판정해 그대로 내보내고(461 → 12, 안전해 보임) 사례 A가 k = 1이 됩니다. C1은 누적 State로 판정해 같은 값을 뺍니다. 턴 5 행을 누르면 두 조건의 판정 근거가 나란히 보입니다.
4. **레드팀 실행**에서 4명(12명)으로 한 번 돌려 배치 결과 화면을 보여 주고, **POC 결과**에서 296명 전체 숫자로 넘어갑니다.

## 구조

```
webdemo/
  backend/engine.py   세션(질의 환자 1명 × 세 조건), 질문 후보, 보내기 전 확인, 레드팀 작업
  backend/app.py      FastAPI 엔드포인트, 프론트엔드 정적 파일
  frontend/           빌드 없는 HTML·CSS·JS (index.html, js/*.js)
  data/               POC 집계 (poc_summary.json)
tests/test_webdemo.py
```

| 엔드포인트 | 내용 |
| --- | --- |
| `GET /api/meta` · `GET /api/patients` | 기준값(k_req 5, Defender 5·3, 기준 집단 461명), 질의 trial 296개와 현재 환자 패널 |
| `POST /api/sessions` | `{trial_id, profile: staged\|full, fuzzer: uniform\|feedback}` → 사례 검색(턴 0)까지 실행 |
| `GET /api/sessions/{id}/clinician?arm=C1` | 의료진 화면용. 공개된 답, 바뀐 값 표시, 사례별 k, 공개 내역 |
| `GET /api/sessions/{id}/security` | 보안 관제용. 세 조건의 원 응답·공개 응답·판정·k, Validated k |
| `GET /api/sessions/{id}/questions?arm=C1` | 그 조건의 공개 상태에서 물을 수 있는 Seed |
| `POST /api/sessions/{id}/preview` | `{seed_id, arm}` → 기록대로 답했을 때 사례별 k (State는 바꾸지 않음) |
| `POST /api/sessions/{id}/turns` | `{seed_id?, arm}` → 한 턴. seed_id가 없으면 퍼저가 고름 |
| `POST /api/sessions/{id}/run?arm=C1` | 퍼저로 질문 예산(10턴)까지 |
| `POST /api/redteam` · `GET /api/redteam/{id}` | 배치 실행 `{profile, fuzzer, per_type}`과 진행·결과 |
| `GET /api/poc` | 저장된 POC 집계 |

백엔드는 `medical/`의 코드를 고치지 않고 불러 씁니다(`make_prefix`, `ArmRun._turn`, `choose_seed`·`FeedbackSelector`, `MedicalDefender`, `validate_case`, `run_experiment`, `analyse`). 짝 비교 p는 `evaluation/eval_baseline.py`의 `exact_mcnemar`로 냅니다.

## 세 조건을 같은 질문으로 진행하는 규칙

POC 배치에서는 조건마다 자기 State로 Seed를 골랐습니다. 데모에서는 사람이 고른 질문을 세 조건에 똑같이 보내야 비교가 되므로 아래처럼 맞췄습니다.

- 질문 후보와 퍼저 선택은 화면에 보이는 조건(기본 C1)의 공개 상태로 정합니다. 질문 문장은 조건마다 자기 공개 상태로 채웁니다. '더 자세히' 질문에 들어가는 앞선 공개 값이 조건마다 다르기 때문입니다.
- 그 조건의 상태에서 Seed 조건이 맞지 않으면, '처음 묻기' 질문은 그대로 다시 묻습니다. '더 자세히' 질문은 좁힐 값이 있으면 그 값으로 묻고, 없으면 그 조건만 그 턴을 건너뜁니다. 건너뛴 이유는 화면에 표시됩니다.
- trial 번호와 난수는 POC와 같습니다. 그래서 퍼저 자동 선택만 쓰면 C1은 POC 배치의 C1과 같은 질문 순서가 됩니다(T0014로 확인, `tests/test_webdemo.py`).

## 이 데모의 범위

- **대상 AI가 결정적 응답기입니다.** 거절하거나 틀리게 답하는 경우가 없고, 등록 질문(Seed v0.13, 140행)만 알아듣습니다. 그래서 자유 입력 대신 질문 목록에서 고르게 했습니다. 질문 변형 연산자(M1·M3·M4)는 골라지지만 이 설정에서는 문장을 바꾸지 않습니다.
- **합성 데이터입니다.** Synthea 576명(저장소 461명, 질의 환자 풀 115명)이며 모두 Massachusetts 거주자입니다. 화면의 k = 1은 합성 기준 집단 안에서 유일하다는 뜻까지만입니다.
- **한 사람이 쓰는 로컬 데모입니다.** 세션은 서버 메모리에만 있어 서버를 끄면 지워집니다. 요청은 한 번에 하나씩 처리합니다(kcalc 캐시와 응답기 상태를 세션끼리 나눠 쓰기 때문). 로그인과 권한 분리는 없습니다. 의료진 화면과 보안 관제 화면은 API만 나눠 두었습니다.
- LLM 대상 AI로 바꾸려면 `Engine`의 `OracleRoleLLM`을 `medical.llm.ClientRoleLLM`으로 바꾸고, 자유 입력 질문을 받는 엔드포인트를 더해야 합니다. 이때는 추출기도 LLM이 되므로 턴마다 수 초가 걸립니다.
