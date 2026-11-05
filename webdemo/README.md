# MediCloak 의료 AI 데모 (의료진 화면 + 보안 관제)

MediCloak은 의료 LLM의 답이 화면에 나가기 전에, 앞선 대화와 함께 보고 특정 환자를 알아볼 수 있는 값을 넓히거나 가리는 보호 계층입니다. 이 데모는 두 화면을 한 앱에 담았습니다.

- **의료진 화면**: 병원 EMR 안에 들어간 진료 지원 AI 형태입니다(팀원 `frontend/` Clinical Case Finder를 바탕으로 다시 구성). 후보 수 같은 재식별 위험 숫자는 보이지 않고, 가린 값은 '비공개', 넓힌 값은 '범위'로만 표시합니다. 필요하면 개인정보 보호 담당자에게 세부 정보를 요청할 수 있습니다.
- **보안 담당자 화면(MediCloak 관제)**: 같은 대화를 숫자와 함께 봅니다. 방어 규칙이 무엇을 왜 가렸는지, 가리지 않았다면 후보가 몇 명이었을지, 단서가 사례들에 어떻게 이어지는지 보여 주고, 의료진 요청에 답합니다.

이 데모(`python -m webdemo`)는 API 키가 필요 없습니다. 대상 AI는 질문받은 단서를 검색 문서의 기록값으로 답하는 결정적 응답기(`medical/simulate.py`의 `OracleRoleLLM`)이고 LLM을 부르지 않습니다.

로그인 · 역할 분리 · DB(가상 EMR · 기록) · `.env`의 실제 LLM으로 돌리려면 같은 서버 코드를 **운영 모드 `python -m medicloak`**로 켭니다 ([medicloak/README.md](../medicloak/README.md), ADR-0021). 화면도 같습니다.

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
| 유사 사례 조회 (`/`) | 의료진 | EMR 머리줄과 진료 중 환자 띠 아래에 비슷한 사례 5건, 사례별 대화, 사례 노트가 있습니다. 답의 '사례 · 항목 · 기록 번호 · 값'을 표로 보여 주고, 가린 값은 '비공개', 넓힌 값은 '범위'로 표시합니다. '왜 그런가요?'는 숫자 없이 이유를 설명하고, '세부 정보 요청'은 보호 담당자에게 사유와 함께 요청을 보냅니다. 보내기 전 확인도 후보 수 대신 '보내면 어떻게 보이는지'만 알립니다. 답은 복사해 진료 기록에 붙일 수 있습니다(가린 값은 '(비공개)'). |
| 사례 노트 (`/` 오른쪽) | 의료진 | 옵시디언 노트처럼 그 사례에 지금까지 나온 내용을 모읍니다: 속성(진단 · 약 · 시술은 용어 사전 [[링크]]), 연결된 질문(누르면 대화의 그 질문으로), 같은 값이 나온 사례. 옆 탭 '보호 담당자 메시지'에서 요청과 답장을 주고받습니다. 보호 담당자가 확인을 요청하면 대화 위에 뜨고 머리줄 알림에 숫자가 붙습니다. |
| 조회 기록 (`/history`) · 보호 안내 (`/guide`) | 의료진 | 사례별 질문 수와 마지막 질문, 메시지 / 화면 표시의 뜻, 세부 정보 요청 방법, 남는 기록 |
| 관제 (`/monitor`) | 보안 담당자 | 모든 대화(의료진 화면 대화 + 시작할 때 만든 레드팀 시뮬레이션 대화)를 위험 순으로 보여 줍니다. 의료진 요청이 기다리는 대화는 맨 위에 '의료진 세부 정보 요청'으로 올라옵니다. 대화를 고르면 의료진과 주고받은 메시지(답장 쓰기), 가리지 않았다면 남았을 후보, 방어 없음 · 턴별 방어였다면의 후보, 단서 그래프, 질문 흐름을 봅니다. 원래 값과 환자 번호는 사유를 남겨야 열리고, 검토 완료 · 의료진 확인 요청(메시지로 전달) · 규칙 추가는 감사 기록에 남습니다. 3초마다 새로 고칩니다. |
| 의료진 대화 (`/watch`) | 보안 담당자 | 의료진 화면의 지금 대화를 숫자와 함께 봅니다: 후보 렌즈와 사례별 후보 수 막대, 답 속 가림 · 넓힘과 후보 수 변화, 나간 정보와 판정 근거, 단서 그래프(여러 사례에 공통인 값은 가운데, 한 사례에만 붙은 값은 그 사례 둘레). '질문 미리 세기'는 상태를 바꾸지 않고 이 질문이 오면 몇 명으로 줄어드는지 셉니다. |
| 리포트 (`/report`) | 보안 담당자 | 2026-10-23 POC 4가지 설정의 집계와, 이 자리에서 레드팀 점검을 다시 돌린 결과 |
| 감사 기록 (`/audit`) | 보안 담당자 | 원문 열람(사유 포함), 검토 표시, 의료진과 주고받은 메시지, 새 대화 시작, 레드팀 실행 |
| 보호 정책 (`/policy`) · 용어 (`/terms`) | 보안 담당자 | 지금 판정 기준(5 · 3)과 화면에서 쓰는 말 / 의료 용어 사전 |

키보드: ⌘K(윈도우 Ctrl+K) 찾기(의료진은 화면 · 사례 · 용어, 보안 담당자는 화면 · 대화 번호 · 용어), 관제 목록에서 J/K 이동. 오른쪽 위 버튼으로 라이트/다크를 바꿉니다. 의료진 화면 오른쪽 위 '데모' 전환으로 보안 담당자 화면에 갑니다.

## 발표에서 보여 주기 좋은 순서

1. **의료진 화면**: T0014(2세 남, Acute bronchitis, 처방 조회). 사례 4의 처방 약이 처음부터 잠금 표시 '비공개'로 보입니다. 오른쪽 사례 노트에 사례 1의 진단 · 처방 약이 [[링크]]로 모여 있습니다.
2. 예시 질문 '시점'을 누르면 입력칸에 "사례1 환자가 그 시술을 받은 시기를 월 단위로 알려 주세요."가 들어가고, 보내기 전 안내에 "이 질문에 답하면 사례 1의 시점은 비공개로 표시됩니다"가 뜹니다(숫자 없음). 보내면 처방 약 시작일이 '비공개'로 나오고, **왜 그런가요?**에서 이유를 봅니다.
3. **세부 정보 요청**을 눌러 사유를 적어 보냅니다. 사례 노트의 '연결된 질문'을 누르면 대화의 그 질문으로 돌아갑니다.
4. 오른쪽 위 '데모'에서 **보안 담당자**로 바꿉니다. 관제 목록 맨 위에 '의료진 세부 정보 요청'이 올라와 있습니다. 고르면 "가리지 않았다면 1명", "방어 없음 1명"이 보입니다. 원래 값은 공개하지 않는다는 답장을 보내고, **단서 그래프**를 펼쳐 사례 1에만 붙은 단서를 보여 줍니다. **사유 적고 보기**로 원래 값(2004-06)을 열고, **감사 기록**에서 요청 · 답장 · 열람이 남은 것을 보여 줍니다.
5. **의료진 대화**에서 같은 대화를 숫자와 함께 봅니다. '질문 미리 세기'에 같은 질문을 넣으면 "사례 1 후보가 6명에서 1명으로 줄어듭니다"가 나옵니다.
6. 다시 **의료진**으로 바꾸면 머리줄 알림과 '보호 담당자 메시지'에 답장이 와 있습니다. 관제에서 **의료진에게 확인 요청**을 보내면 의료진 화면 대화 위에 뜨고, 의료진이 답장할 수 있습니다.
7. **리포트**에서 POC 296건 결과를 보여 주고, 유형마다 2명으로 **다시 점검**을 눌러 15초 안팎에 같은 방식의 결과가 나오는 것을 보여 줍니다.

## 구조

```
frontend/                      팀원 Clinical Case Finder (React·TS·Vite·Tailwind)를 의료진 EMR 화면과 MediCloak 관제로 나눔
  src/index.css, tailwind.config.js   디자인 토큰 (관제 남색 / 의료진 [data-app='emr'] 청록, 라이트/다크, 대비 검사 통과값)
  src/pages/ClinicalAssistPage.tsx · HistoryPage.tsx · GuidePage.tsx   의료진 화면
  src/components/clinic/       EMR 사례 목록 · 대화 · 답(범위 · 비공개 표시) · 사례 노트 · 환자 띠
  src/lib/clinicianCopy.ts     의료진 화면 문구 (숫자 없음, clinicianView.test.ts로 검사)
  src/lib/caseNote.ts · answerLines.ts   사례 노트(속성 · 백링크 · 같은 값), 답 줄 나누기
  src/state/ClinicMessages.tsx 의료진 ↔ 보호 담당자 메시지 (4초마다 새로 받음)
  src/pages/MonitorPage.tsx · WatchPage.tsx · ReportPage.tsx · AuditPage.tsx   보안 담당자 화면
  src/components/graph/ClueGraph.tsx · src/lib/clueGraph.ts   단서 그래프 (난수 없는 힘 배치)
  src/api/monitorApi.ts        관제 API (데모 서버에만 있음)
  .env.demo                    npm run dev:demo / build:demo 설정 (VITE_API_MODE=http, /api)
webdemo/
  backend/engine.py            세션(질의 환자 1명 × 세 조건 C0·C1·C1S), 질문 후보, 미리 세기, 레드팀 작업
  backend/clinic.py            의료진 화면 계약 (api_server와 같은 경로·응답 모양). 대화(ClinicConversation) · 의료진 한 명(ClinicDesk) · 계정별(DeskRegistry)
  backend/redact.py            의료진 화면 API에서 위험 숫자 지우기
  backend/store.py · emr.py · fhir.py · auth.py · live.py · persist.py   운영 모드(python -m medicloak) 전용: DB · 가상 EMR · 로그인 · 실제 LLM · 기록
  backend/intent.py            의료진이 쓴 문장 → 묻는 단서 → Seed (결정적 응답기용 규칙)
  backend/monitor.py           관제 목록·상세·원문 열람·검토·감사 기록, 의료진 ↔ 보안 담당자 메시지, 시뮬레이션 대화
  backend/app.py               FastAPI, frontend/dist 내보내기
  data/poc_summary.json        POC 집계
tests/test_webdemo.py
```

### API

| 경로 | 내용 |
| --- | --- |
| `GET /api/workspace` · `/protection-policy` · `/patient-context` · `/cases?patientContextId=` · `/risk-states` | 의료진 화면 (api_server와 같은 경로). 후보 수 · 기준값 필드는 null (`backend/redact.py`) |
| `GET /api/cases/{id}/session` · `/disclosures` | 〃 (숫자가 든 설명 문장도 지움). `/policy-decision`은 403 |
| `POST /api/cases/{id}/messages` · `/preflight` | 질문 보내기, 보내기 전 확인 (`plannedAction`만, 후보 수 없음) |
| `GET /api/watch` · `GET /api/watch/{대화}/…` | 보안 담당자: 의료진 대화 목록, 그 대화의 의료진 화면 계약을 숫자 그대로 (읽기 전용, `/preflight`는 질문 미리 세기) |
| `GET /api/clinic/history` · `GET /api/monitor/policy` | 의료진 대화 목록(이 화면 · 계정) · 판정 기준과 서버 설정 |
| `GET /api/cases/{id}/suggestions` · `GET /api/clinic/patients` · `POST /api/session/reset {trialId}` | 예시 질문, 질의 환자 목록, 새 대화 |
| `GET /api/clinic/messages` · `POST /api/clinic/messages {kind, text, caseId}` | 의료진 ↔ 보호 담당자 메시지 (kind: access_request 세부 정보 요청 · reply 답장) |
| `GET /api/monitor/overview` · `GET /api/monitor/sessions/{sid}` | 관제 목록과 상세 (원래 값은 지워서 보냄) |
| `POST /api/monitor/sessions/{sid}/reveal {reason, note}` · `/review {action, note}` · `GET /api/monitor/audit` | 원문 열람(`note`: 확인하려는 것, 운영 모드는 필수), 검토 표시(ask_clinician은 확인 요청 메시지도 보냄), 감사 기록 |
| `POST /api/monitor/sessions/{sid}/what-if {items}` | 고른 가린 값을 함께 공개한 뒤의 사례별 후보 수 (State는 바꾸지 않음). 기준 아래로 내려가는 승인은 `approve`에 `confirmLowK`가 필요 (ADR-0030) |
| `GET /api/monitor/sessions/{sid}/messages` · `POST … {kind, text, case}` | 보안 담당자 쪽 메시지 (kind: reply 답장 · check_request 확인 요청) |
| `POST /api/redteam` · `GET /api/redteam/{id}` · `GET /api/poc` | 레드팀 배치와 POC 집계 |
| `/api/meta` · `/api/patients` · `/api/sessions…` | 세션 직접 조작 (POC 재현·테스트) |

백엔드는 `medical/`를 고치지 않고 불러 씁니다(`make_prefix`, `ArmRun._turn`, `choose_seed`·`FeedbackSelector`, `MedicalDefender`, `validate_case`, `run_experiment`, `analyse`).

## 의료진 질문을 결정적 응답기에 보내는 규칙

결정적 응답기는 자유 문장을 읽지 못하고 묻는 단서(Seed)를 받아야 답합니다. 그래서 `intent.py`가 문장에서 사례 번호('사례3'), 묻는 단서(나이·성별·거주지·진단·시술·약·관리 계획·시기), '더 자세히' 여부, 사례 전체 질문인지를 낱말로 찾고, 그에 맞는 Seed v0.13 행을 고릅니다. 화면과 기록에는 의료진이 쓴 문장이 그대로 남습니다. 단서를 찾지 못하면 기록을 공개하지 않고 답할 수 있는 질문 예를 돌려줍니다. 실제 LLM(api_server)에서는 이 단계가 없습니다.

## 이 데모의 범위

- **대상 AI가 결정적 응답기입니다.** 거절하거나 틀리게 답하는 경우가 없습니다. 숫자는 이 응답기 가정 아래의 값입니다.
- **합성 데이터입니다.** Synthea 576명(저장소 461명, 질의 환자 풀 115명)이며 모두 Massachusetts 거주자입니다. 후보 1명은 합성 기준 집단 안에서 유일하다는 뜻까지만입니다.
- **한 사람이 쓰는 로컬 데모입니다.** 대화, 메시지, 감사 기록은 서버 메모리에만 있어 서버를 끄면 지워집니다. 로그인과 권한 분리는 없고, 의료진/보안 담당자 전환은 화면 전환일 뿐입니다. 로그인 · 의료진별 대화 · DB 기록은 운영 모드(`python -m medicloak`)에 있습니다.
- **의료진 화면 API에는 위험 숫자가 없습니다.** 후보 수 · 기준값은 서버가 지워서 보내고(ADR-0021), 보안 담당자 화면은 `/api/watch/{대화}`로 숫자를 받습니다.
- 관제 화면의 '레드팀 시뮬레이션' 대화는 서버를 켤 때 퍼저가 만든 공격 대화입니다(T0010, T0015, T0036, T0024, T0016, T0005 각 6턴). 실제 의료진 대화가 아닙니다.
