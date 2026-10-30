# Zero PII 의료 AI 데모 (의료진 화면 + 보안 관제)

의료진이 쓰는 유사 사례 조회 화면(팀원 `frontend/` Clinical Case Finder)과 보안 담당자 관제 화면을 한 앱으로 합친 로컬 데모입니다. 의료진 화면에서 질문하면 그 대화가 관제 화면에 바로 나타나고, 방어 규칙이 무엇을 왜 가렸는지와 가리지 않았다면 후보가 몇 명이었을지를 보여 줍니다.

API 키가 필요 없습니다. 대상 AI는 질문받은 단서를 검색 문서의 기록값으로 답하는 결정적 응답기(`medical/simulate.py`의 `OracleRoleLLM`)이고 LLM을 부르지 않습니다. 실제 LLM으로 돌리려면 팀원 `api_server/`(`python -m api_server`, `.env` 필요)를 쓰면 되고, 같은 화면이 의료진 부분만 그대로 붙습니다.

## 실행 (맥 기준)

필요한 것: Python 3.10 이상, Node.js 18 이상(화면 빌드용). 저장소 맨 위 폴더에서 실행합니다.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r webdemo/requirements.txt
python -m webdemo --build
```

`--build`는 처음 한 번만 붙이면 됩니다(`frontend/`에서 `npm install`과 `npm run build:demo`를 대신 실행). 준비되면 http://127.0.0.1:8000 을 엽니다. 서버가 켜지는 데 10초 안팎 걸립니다(Synthea 576명 적재, 저장소 461명 문서, kcalc 준비).

| 옵션 | 뜻 |
| --- | --- |
| `--port 8080` | 포트 바꾸기 |
| `--trial T0010` | 의료진 화면에서 처음 보여 줄 질의 환자 (기본 T0014, 화면에서도 바꿀 수 있음) |
| `--no-sim` | 관제 화면용 레드팀 시뮬레이션 대화 6건을 만들지 않음 |

화면을 고치면서 보려면 터미널 두 개를 씁니다: 하나는 `python -m webdemo`, 다른 하나는 `cd frontend && npm run dev:demo` 후 http://localhost:5173 (개발 서버가 `/api`를 8000번으로 넘깁니다).

엔진과 레드팀 실행 기록은 `runs/webdemo/`에 생기며 커밋하지 않습니다.

## 화면

| 화면 | 누가 | 하는 일 |
| --- | --- | --- |
| 진료 (`/`) | 의료진 | 지금 진료 중인 환자, AI가 찾은 비슷한 사례 5건, 사례별 대화. 보내기 전에 그 질문이 후보를 몇 명으로 줄이는지 미리 알려 주고, 답에서 넓힌 값과 가린 값을 표시합니다. 사례별 후보 수(후보 렌즈), 나간 정보, 판정 근거를 봅니다. 다른 질의 환자로 새 대화를 시작할 수 있습니다. |
| 조회 기록 (`/history`) | 의료진 | 사례별 질문 수와 최신 후보 수 |
| 관제 (`/monitor`) | 보안 담당자 | 모든 대화(의료진 화면 대화 + 시작할 때 만든 레드팀 시뮬레이션 대화)를 위험 순으로 보여 줍니다. 대화를 고르면 질문 흐름, 가리지 않았다면 남았을 후보, 방어 없음·턴별 방어였다면의 후보를 봅니다. 원래 값과 환자 번호는 사유를 남겨야 열리고, 검토 완료·의료진 확인 요청·규칙 추가는 감사 기록에 남습니다. 3초마다 새로 고칩니다. |
| 리포트 (`/report`) | 보안 담당자 | 2026-10-23 POC 4가지 설정의 집계와, 이 자리에서 레드팀 점검을 다시 돌린 결과 |
| 감사 기록 (`/audit`) | 보안 담당자 | 원문 열람(사유 포함), 검토 표시, 새 대화 시작, 레드팀 실행 |
| 보호 정책 (`/policy`) | 모두 | 지금 판정 기준(5·3)과 화면에서 쓰는 말 |

키보드: ⌘K(윈도우 Ctrl+K) 화면·대화 찾기, 관제 목록에서 J/K 이동. 오른쪽 위 버튼으로 라이트/다크를 바꿉니다.

## 발표에서 보여 주기 좋은 순서

1. **진료**: T0014(2세 남, Acute bronchitis, 처방 조회). 사례 4의 처방 약이 처음부터 '(비공개)'인 것이 보입니다(검색 답에서 그대로면 후보 2명).
2. 예시 질문 '시점'을 누르면 입력칸에 "사례1 환자가 그 시술을 받은 시기를 월 단위로 알려 주세요."가 들어가고, 보내기 전 확인에 "그대로 답하면 사례 1 후보가 6명에서 1명으로 줄어듭니다"가 뜹니다. 보내면 시작일을 가리고 후보 6명을 지킵니다.
3. 오른쪽 위에서 **보안 담당자**로 바꾸면 방금 그 대화가 '의료진 화면' 행으로 보입니다. 고르면 "가리지 않았다면 1명", "방어 없음 1명"이 나란히 보입니다. **사유 적고 보기**로 원래 값(2004-06)을 열고, **감사 기록**에서 그 열람이 남은 것을 보여 줍니다.
4. **리포트**에서 POC 296건 결과를 보여 주고, 유형마다 2명으로 **다시 점검**을 눌러 15초 안팎에 같은 방식의 결과가 나오는 것을 보여 줍니다.

## 구조

```
frontend/                      팀원 Clinical Case Finder (React·TS·Vite·Tailwind)에 관제 화면과 Zero PII 스타일을 더함
  src/index.css, tailwind.config.js   디자인 토큰 (라이트/다크, 대비·색각 검사 통과값)
  src/pages/MonitorPage.tsx · ReportPage.tsx · AuditPage.tsx   보안 담당자 화면
  src/api/monitorApi.ts        관제 API (데모 서버에만 있음)
  .env.demo                    npm run dev:demo / build:demo 설정 (VITE_API_MODE=http, /api)
webdemo/
  backend/engine.py            세션(질의 환자 1명 × 세 조건 C0·C1·C1S), 질문 후보, 미리 세기, 레드팀 작업
  backend/clinic.py            의료진 화면 계약 (api_server와 같은 경로·응답 모양)
  backend/intent.py            의료진이 쓴 문장 → 묻는 단서 → Seed (결정적 응답기용 규칙)
  backend/monitor.py           관제 목록·상세·원문 열람·검토·감사 기록, 시뮬레이션 대화
  backend/app.py               FastAPI, frontend/dist 내보내기
  data/poc_summary.json        POC 집계
tests/test_webdemo.py
```

### API

| 경로 | 내용 |
| --- | --- |
| `GET /api/workspace` · `/protection-policy` · `/patient-context` · `/cases?patientContextId=` · `/risk-states` | 의료진 화면 (api_server와 같음) |
| `GET /api/cases/{id}/session` · `/disclosures` · `/policy-decision` | 〃 |
| `POST /api/cases/{id}/messages` · `/preflight` | 질문 보내기, 보내기 전 미리 세기 (데모에서는 `supported: true`) |
| `GET /api/cases/{id}/suggestions` · `GET /api/clinic/patients` · `POST /api/session/reset {trialId}` | 예시 질문, 질의 환자 목록, 새 대화 |
| `GET /api/monitor/overview` · `GET /api/monitor/sessions/{sid}` | 관제 목록과 상세 (원래 값은 지워서 보냄) |
| `POST /api/monitor/sessions/{sid}/reveal {reason}` · `/review {action}` · `GET /api/monitor/audit` | 원문 열람, 검토 표시, 감사 기록 |
| `POST /api/redteam` · `GET /api/redteam/{id}` · `GET /api/poc` | 레드팀 배치와 POC 집계 |
| `/api/meta` · `/api/patients` · `/api/sessions…` | 세션 직접 조작 (POC 재현·테스트) |

백엔드는 `medical/`를 고치지 않고 불러 씁니다(`make_prefix`, `ArmRun._turn`, `choose_seed`·`FeedbackSelector`, `MedicalDefender`, `validate_case`, `run_experiment`, `analyse`).

## 의료진 질문을 결정적 응답기에 보내는 규칙

결정적 응답기는 자유 문장을 읽지 못하고 묻는 단서(Seed)를 받아야 답합니다. 그래서 `intent.py`가 문장에서 사례 번호('사례3'), 묻는 단서(나이·성별·거주지·진단·시술·약·관리 계획·시기), '더 자세히' 여부, 사례 전체 질문인지를 낱말로 찾고, 그에 맞는 Seed v0.13 행을 고릅니다. 화면과 기록에는 의료진이 쓴 문장이 그대로 남습니다. 단서를 찾지 못하면 기록을 공개하지 않고 답할 수 있는 질문 예를 돌려줍니다. 실제 LLM(api_server)에서는 이 단계가 없습니다.

## 이 데모의 범위

- **대상 AI가 결정적 응답기입니다.** 거절하거나 틀리게 답하는 경우가 없습니다. 숫자는 이 응답기 가정 아래의 값입니다.
- **합성 데이터입니다.** Synthea 576명(저장소 461명, 질의 환자 풀 115명)이며 모두 Massachusetts 거주자입니다. 후보 1명은 합성 기준 집단 안에서 유일하다는 뜻까지만입니다.
- **한 사람이 쓰는 로컬 데모입니다.** 대화와 감사 기록은 서버 메모리에만 있어 서버를 끄면 지워집니다. 로그인과 권한 분리는 없고, 의료진/보안 담당자 전환은 화면 전환일 뿐입니다.
- 관제 화면의 '레드팀 시뮬레이션' 대화는 서버를 켤 때 퍼저가 만든 공격 대화입니다(T0010, T0015, T0036, T0024, T0016, T0005 각 6턴). 실제 의료진 대화가 아닙니다.
