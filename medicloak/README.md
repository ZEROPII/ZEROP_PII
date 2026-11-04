# MediCloak 운영 모드 (`python -m medicloak`)

의료진은 로그인해 가상 EMR의 외래 목록에서 환자를 열고, `.env`에 넣은 실제 LLM에게 비슷한 과거 사례를 묻습니다. 환자를 열 때의 첫 답부터 실제 LLM이 씁니다. MediCloak은 그 답이 화면에 나가기 전에 대화 전체의 단서를 사례마다 모아 세고, 환자를 알아볼 수 있는 값은 넓히거나 가립니다. 보안 담당자는 다른 계정으로 로그인해 같은 대화를 숫자와 함께 보고, 의료진의 세부 정보 요청을 승인해 가린 값을 열어 주거나 대화에 규칙을 걸고, 레드팀 점검을 실제 LLM으로 돌립니다. 원문 열람 · 승인 · 규칙은 사유와 함께 감사 기록에 남습니다.

화면과 서버 코드는 데모(`python -m webdemo`)와 같습니다. 다른 점은 아래뿐입니다.

| | 데모 `python -m webdemo` | 운영 `python -m medicloak` |
| --- | --- | --- |
| 대상 AI | 결정적 응답기 (LLM 호출 없음) | `.env`의 실제 LLM: 첫 답(사례 검색)부터 모든 질문, 레드팀 점검까지 (기본). `--llm oracle` · `--llm dry-run`도 됨 |
| 로그인 | 없음 (화면 전환 단추) | 계정 · 역할. 의료진과 보안 담당자는 서로의 API를 못 씀 |
| 대화 | 화면 하나 = 대화 하나 | 의료진 계정마다 따로 |
| 환자 | 데모 환자 목록 (처음부터 기본 환자가 열림) | 가상 EMR 외래 목록 (DB · FHIR R4). 환자를 열기 전에는 대화가 없음 |
| 기록 | 메모리 (끄면 지워짐) | SQLite DB (다시 켜도 남음) |
| 의료진 화면 API의 위험 숫자 | 없음 | 없음 |
| 관제의 시뮬레이션 대화 | 켤 때 6개 만듦 | 없음 (실제 의료진 대화만) |
| 레드팀 · 리포트 | 결정적 응답기 | 실제 LLM, 규모를 골라 실행 · 멈춤 · DB에 남김 |

## 처음 실행

저장소 맨 위 폴더에서:

```bash
source venv/bin/activate                 # 없으면: python3 -m venv venv && source venv/bin/activate
pip install -r webdemo/requirements.txt
python -m medicloak init                 # DB · 가상 EMR(576명) · 처음 쓸 계정 3개. 비밀번호를 한 번 보여 주고 파일에도 적음
python -m medicloak check-llm            # .env를 읽어 실제 LLM에 짧은 요청을 한 번 (키 값은 출력하지 않음)
python -m medicloak serve --build        # 화면 빌드 후 서버. http://127.0.0.1:8000
```

`init`이 만든 계정과 비밀번호는 `runs/medicloak/initial_accounts.txt`(권한 600)에 있습니다. 예전 `init`으로 만들었다면 `demo_accounts.txt`입니다. `runs/`는 커밋하지 않습니다.

| 아이디 | 역할 | 이름 |
| --- | --- | --- |
| doctor1 | 의료진 | 김서연 (내과) |
| doctor2 | 의료진 | 박준호 (가정의학과) |
| privacy1 | 보안 담당자 | 이하늘 (개인정보보호팀) |

비밀번호를 정해서 만들려면 `python -m medicloak init --initial-password '원하는 비밀번호'`(셋이 같이 씀) 또는 환경변수 `MEDICLOAK_INITIAL_PASSWORD`. 이미 계정이 있으면 다시 만들지 않습니다.

### `.env`

저장소 맨 위의 `.env`(`.env.example`을 복사)에 넣습니다. 셸 환경변수가 있으면 그것이 우선합니다.

```
LLM_API_KEY=...
LLM_API_BASE=...
LLM_MODEL=...
# 선택: LLM_MAX_TOKENS · LLM_TIMEOUT_SEC · LLM_MAX_RETRIES · LLM_MIN_INTERVAL_SEC (분당 호출 제한이 있으면 간격을 줌)
```

`check-llm`이 `[설정 오류]`를 내면 빈 변수 이름을 알려 줍니다. `[호출 실패] LLMHTTPError: HTTP 401`이면 키, `404`면 주소나 모델 이름을 확인합니다.

## 서버 옵션

```bash
python -m medicloak serve [옵션]          # serve는 생략해도 됨
```

| 옵션 | 뜻 |
| --- | --- |
| `--llm real` | 의료진 대화의 대상 AI를 `.env`의 실제 모델로 (기본) |
| `--llm oracle` | 키 없이: 결정적 응답기 (데모와 같은 답) |
| `--llm dry-run` | 키 없이 배선만 확인: 가짜 LLM (답 내용에는 의미가 없음) |
| `--llm-concurrency 1` | 동시에 보내는 LLM 요청 수 |
| `--no-compare` | 비교 갈래(방어 없음 C0 · 턴별 방어 C1S) 계산을 끔. 관제 화면의 '다른 방식이었다면'이 비고, LLM 호출이 줄어듦 |
| `--port 8080` · `--host 0.0.0.0` | 주소 |
| `--keep 12` | 의료진마다 메모리에 둘 대화 수 (넘는 대화는 DB에만 남고 읽기 전용) |
| `--cookie-secure` | https로만 로그인 쿠키를 보냄 (역방향 프록시 뒤 https 운영) |
| `--no-rule-extract` | 실제 LLM 대화 · 레드팀의 나이 · 날짜 규칙 추출을 끔. 기본은 켬: 추출기가 날짜를 약 항목 안에만 적어도 날짜를 단서로 셈 (ADR-0021) |
| `--db 경로` | DB 파일 (기본 `runs/medicloak/medicloak.db`) |

## 실제 LLM 호출 수

- **환자를 열 때(첫 답, 턴 0)**: 대상 AI 1번, 추출기 1번(형식이 틀리면 다시), 가릴 값이 있으면 재작성기 1번과 확인 추출 1번. 사례 검색 질문 문장만 결정적 응답기가 만듭니다. 세 갈래의 첫 판정은 요청이 같아서 앞 갈래가 받은 답을 다시 씁니다(형식 오류 뒤 다시 보내는 요청은 새로 부름).
- **다시 확인을 통과하지 못했을 때**: 두 번째 재작성에는 무엇이 남았는지 알려 주고, 값만 바꾼 답까지 통과하지 못하면 통과하지 못한 사례만 빼고 한 번 더 확인합니다(추출 1번 더). 그래도 안 되면 거절 문장입니다.
- **의료진 질문 한 번**: 위와 같습니다. 비교 갈래 C1S는 의료진 답을 보낸 뒤 뒤에서 계산하므로 의료진은 기다리지 않지만, 값을 바꿀 때 재작성 · 확인 호출이 더 듭니다(`--no-compare`로 끔). C0은 같은 원 응답을 쓰므로 호출이 없습니다.
- **레드팀 점검**: 질의 환자 한 명마다 갈래 3개 × 최대 10턴, 턴마다 공격 질문 만들기 · 확인 · 대상 AI · 추출 · 재작성 · 다시 확인으로 약 6번으로 어림합니다. 유형마다 1명(3명)이면 약 540번입니다. 위험에 닿은 대화는 일찍 끝나 줄고, 형식 오류로 다시 부르면 늘어납니다. 의료진 질문 호출이 기다리면 그쪽을 먼저 보냅니다.

LLM을 부르지 않는 것: 입력칸의 '보내기 전 확인'과 보안 담당자의 '질문 미리 세기'(사례 기록대로 답한다고 보고 세는 추정), 예시 질문. 대상 AI 이름은 관제 화면 머리줄에, 서버를 켠 뒤의 역할별 호출 수와 토큰은 '보호 정책' 화면(`/api/monitor/policy`)에, 레드팀 실행의 호출 수 · 토큰은 리포트 화면에 나옵니다.

## 계정

```bash
python -m medicloak users                                  # 목록
python -m medicloak users add kim --name 김의사 --role clinician --department 소아청소년과
python -m medicloak users add sec2 --name 박보안 --role security
python -m medicloak users passwd doctor1                   # 비밀번호 바꾸기 (그 계정의 로그인 세션은 모두 끊김)
```

## 화면 흐름

1. **의료진** 로그인 → **외래 진료 목록**(`/emr`). 환자를 고르면 FHIR로 읽은 진단 · 처방 기록이 나옵니다. 진료 목적(처방 · 시술·치료 · 경과·관리)을 골라 **진료 지원 AI 열기**. 열기 전에는 유사 사례 조회 화면이 '열린 환자가 없습니다'로 보입니다.
2. **유사 사례 조회**(`/`)에서 사례에 묻습니다. 첫 답과 이후 답 모두 실제 LLM이 쓰고, 환자를 알아볼 수 있는 값은 '범위'나 '비공개'로 보입니다. 숫자는 보이지 않습니다. 필요하면 **세부 정보 요청**.
3. **보안 담당자** 로그인 → **관제**(`/monitor`). 의료진 이름이 붙은 대화와 요청이 맨 위에 옵니다. 상세에서
   - **후보 수**: 의료진 화면(누적 방어) · 턴별 방어 · 방어 없음의 대화 끝 후보 수를 한 눈금에, 초점 사례에서 후보가 단서마다 어떻게 줄었는지(가린 값은 '그대로였다면')를 봅니다.
   - **값 공개 승인**: 세부 정보 요청이 오면 가린 값을 골라 사유를 적고 공개합니다. 값은 그 의료진의 그 대화에만 '공개 승인' 메시지로 가고, 누적 판정에 더해집니다. 관제 화면에서는 공개한 값도 원문 열람 뒤에만 보입니다.
   - **이 대화에 규칙 걸기**: 사례와 단서 종류를 고르면 다음 질문부터 그 단서는 늘 가립니다. 풀 수 있습니다.
   - 승인과 규칙은 의료진이 지금 열어 둔 대화에만 됩니다. 의료진이 다른 환자를 열었거나 지난 대화이면 막힙니다(409).
4. **의료진 대화**(`/watch`)에서 대화를 골라 후보가 줄어든 과정, 답마다의 판정 표(단서 · 조치 · 그대로였다면 · 고친 답 다시 확인)와 단서 그래프를 봅니다. 원문은 관제에서 사유를 적어야 열립니다.
5. **리포트**(`/report`)에서 레드팀 점검을 실제 LLM으로 돌립니다. 규모(유형마다 1 · 2 · 5 · 10명, 전체)를 고르면 어림 호출 수를 보여 주고, 진행 · 호출 수 · 토큰 · 남은 시간을 보며 멈출 수 있습니다. LLM 호출이 실패한 질의 환자는 집계에서 빼고 그 수를 보이며, 처음 세 명이 모두 실패하면 오류로 멈춥니다. 결과는 DB에 남고, 결정적 응답기 POC는 참고로 고를 수 있습니다.
6. **감사 기록**(`/audit`)에 로그인 · 로그아웃 · 실패, EMR 열기, 의료진 질문(사례 · 보호한 값 수 · 내보낸 답, 질문 본문은 넣지 않음), 열람 · 검토 · 메시지, 공개 승인(항목 · 사유, 값은 넣지 않음), 규칙 걸기 · 풀기, 레드팀 시작 · 멈춤이 남습니다.

서버를 다시 켜면 지난 대화는 관제 · 의료진 대화 화면에 '지난 대화'로 남습니다. 열람과 검토 표시는 되지만 메시지는 보낼 수 없습니다. 의료진은 새 대화부터 시작하고, '조회 기록'에 지난 진료가 나옵니다.

## API

데모 서버 API([webdemo/README.md](../webdemo/README.md#api))에 아래가 더해집니다. 역할은 경로 접두사로 정합니다(`webdemo/backend/auth.py`의 `ROUTE_ROLES`).

| 경로 | 누가 | 내용 |
| --- | --- | --- |
| `POST /api/auth/login {username, password}` · `POST /api/auth/logout` · `GET /api/auth/me` | 누구나 | 로그인 (쿠키 `mc_session`) |
| `GET /api/emr/worklist` · `POST /api/emr/launch {fhirId, purpose}` | 의료진 | 외래 목록, 진료 지원 AI 열기 |
| `GET /fhir/metadata` · `/fhir/Patient` · `/fhir/Patient/{id}` · `/fhir/{Condition·MedicationRequest·Procedure·CarePlan}?patient=` | 의료진 | 가상 EMR FHIR R4 (외래 환자만) |
| `GET /api/clinic/history` | 의료진 | 이 계정의 대화 목록 |
| `GET /api/watch` · `GET /api/watch/{대화}/…` | 보안 담당자 | 의료진 대화 목록, 그 대화의 의료진 화면 계약을 숫자 그대로 |
| `GET /api/monitor/policy` | 보안 담당자 | 판정 기준과 서버 설정 |
| `GET /api/watch/{대화}/cases/{사례}/narrowing` | 보안 담당자 | 후보가 줄어든 과정 (단서마다 전 → 후, 가린 값의 그대로였다면, 규칙) |
| `GET /api/monitor/sessions/{대화}/hidden` · `POST …/approve {items, reason}` | 보안 담당자 | 가린 값 목록(값 없음), 골라서 공개 승인 |
| `POST /api/monitor/sessions/{대화}/rules {case, attribute, note}` · `DELETE …/rules/{규칙}` | 보안 담당자 | 이 대화에 규칙 걸기 · 풀기 |
| `POST /api/redteam {per_type, fuzzer, llm}` · `POST /api/redteam/{실행}/cancel` · `GET /api/redteam` | 보안 담당자 | 레드팀 점검 (운영 모드는 실제 LLM), 멈춤, 실행 목록 (DB) |
| `GET /api/monitor/sessions/{대화}/messages` | 보안 담당자 | 의료진과 주고받은 메시지 (공개 승인 본문의 값은 지움) |

로그인 없이 부르면 401, 다른 역할의 경로는 403입니다. 의료진 화면 API(`/api/workspace` · `/api/cases/…` · `/api/risk-states` …)의 후보 수 · 기준값 필드는 null로 오고, 고친 답을 다시 확인한 기록 · '그대로였다면' 수는 빠지며, `/api/cases/{id}/policy-decision`은 403입니다. 환자를 열기 전에는 이 경로들이 409와 머리글 `X-MediCloak-State: no-conversation`을 돌려줍니다.

## 보안 동작

- 비밀번호: PBKDF2-HMAC-SHA256 200,000회, 계정마다 16바이트 salt. 원문은 저장하지 않습니다.
- 세션: 임의 토큰 32바이트를 HttpOnly · SameSite=Lax 쿠키로 주고, DB에는 SHA-256만 둡니다. 12시간이 지나거나 60분 동안 쓰지 않으면 끝납니다.
- 역할 검사: 미들웨어(라우터와 같은 경로)와 API 경로마다 붙인 검사, 두 곳에서 합니다. 하위 경로 프록시 · `--root-path` 뒤에서도 같습니다. API 문서(`/docs` · `/openapi.json`)는 운영 모드에서 열지 않습니다.
- 로그인 제한: 같은 계정 · 주소에서 10분 안에 5번, 같은 계정에서 20번 틀리면 막습니다(429). 시도는 비밀번호 확인 전에 세므로 한꺼번에 보내도 넘지 못합니다. 없는 아이디는 감사 기록에 입력값을 남기지 않습니다.
- 세션 직접 조작 경로(`/api/sessions/…`, POC 재현 · 테스트용)는 의료진 대화를 열거나 바꾸지 못합니다. 의료진 대화는 관제(사유를 남긴 열람)와 의료진 대화 분석으로만 봅니다.
- API 키: `.env`에서만 읽고 화면 · 로그 · 감사 기록 · 오류 문구에 넣지 않습니다. `check-llm`도 설정 여부만 보여 줍니다.
- 과거 기록 환자: 유사 사례 검색 대상(461명)은 FHIR로 열 수 없습니다(404). 그 기록은 진료 지원 AI 답과 MediCloak 판정을 거쳐서만 보입니다.
- 원 응답 · 가린 원래 값: DB의 턴 기록과 대화 스냅숏에만 있고, 보안 담당자 API에서도 사유를 남긴 열람 때만 나갑니다.
- 공개 승인: 사유 5자 이상, 공개 목록(`/hidden`)과 승인 응답에는 값이 없고, 값은 승인 메시지로 그 의료진의 그 대화에만 갑니다. 관제 상세 · 메시지 목록은 열람 전에 공개한 값을 지웁니다. 감사 기록에는 항목과 사유만 남습니다. '공개 승인' 메시지는 승인 경로로만 보낼 수 있습니다.
- 고친 답 다시 확인: 가리거나 넓히기로 한 원래 값이 글자 그대로 남았거나, 사례 표기가 사라져 사례를 찾지 못하면 통과시키지 않고 값만 바꾼 답 · 거절로 넘어갑니다. 실제 LLM 레드팀도 같은 확인을 씁니다(ADR-0022).
- 거절 전에 사례 단위로 빼기: 재작성 · 값 치환이 모두 통과하지 못하면, 통과하지 못한 사례를 가리키는 머리줄 묶음과 문장만 빼고 다시 확인합니다. 통과하면 그 답을 내고(공개 방식 `CASE_DROPPED`), 뺀 사례는 의료진 화면에 '(비공개)'로 보입니다. 낸 답은 늘 다시 확인을 거칩니다. 재작성기 지시에는 같은 값이 요약 문장 · 줄인 이름으로 다시 나와도 고치라는 규칙을 더하고, 두 번째 재작성에는 남은 표현을 알려 줍니다. 실제 LLM 대화와 레드팀에만 적용합니다(ADR-0023).

## 구조

```
medicloak/cli.py              init · serve · users · check-llm
webdemo/backend/store.py      SQLite (가상 EMR · 계정 · 세션 · 대화 · 턴 기록 · 메시지 · 감사 기록)
webdemo/backend/emr.py        CSV → DB 적재, DB → 위험 계산용 CSV 스냅숏, FHIR 자원 만들기
webdemo/backend/fhir.py       /fhir 경로 (외래 환자만), 외래 목록
webdemo/backend/auth.py       비밀번호 · 세션 · 로그인 제한 · 경로별 역할
webdemo/backend/redact.py     의료진 화면 API에서 위험 숫자 지우기
webdemo/backend/live.py       실제 LLM 만들기 · 네트워크 대기 중 엔진 잠금 풀기 · check-llm
webdemo/backend/persist.py    대화 스냅숏 · 턴 기록 저장, 지난 대화 읽기, 번호 잇기
webdemo/backend/clinic.py     의료진 대화(ClinicConversation) · 의료진 한 명(ClinicDesk) · 계정별 목록(DeskRegistry)
webdemo/backend/review.py     규칙(RuleDefender · RuledArmRun) · 가린 값 목록 · 재작성 지시 보강 · 사례 단위로 빼기 (공개 승인 · 후보가 줄어든 과정은 engine.Session)
tests/medicloak/              운영 모드 테스트 (가짜 HTTP 세션으로 실제 LLM 경로)
```

## 범위와 한계

- 실제 모델 호출은 이 저장소 작업 환경에서 확인하지 못했습니다(키 없음). 가짜 HTTP 세션으로 같은 코드 경로(첫 답 · 질문 · 레드팀)를 테스트했고, 처음 켤 때 `check-llm`으로 확인합니다.
- 레드팀 전체(296명)는 호출이 수만 번입니다. 유형마다 1명부터 돌려 보고 늘리세요. 서버를 끄면 돌던 실행은 '끊김'으로 남고 집계하지 못합니다.
- 승인 공개는 그 대화에서 계속 유효하고, 지금은 취소할 수 없습니다.
- 합성 데이터(Synthea 576명, 모두 Massachusetts)입니다. 실제 환자 정보는 없습니다.
- 서버 한 대 · SQLite입니다. 병원 SSO, 실제 EMR(SMART on FHIR) 연동, https 종단은 아직 없습니다.
- 서버를 다시 켜면 진행 중이던 대화는 이어 갈 수 없고 읽기 전용으로 남습니다.
- 개인정보보호법 · 의료법상 검토(가명정보 처리, 접속기록 보관 기간 등)는 코드 밖에서 해야 합니다.
- 결정은 [ADR-0021](../docs/adr/0021-medicloak-production-mode.md) · [ADR-0022](../docs/adr/0022-medicloak-real-llm-everywhere-and-review-feedback.md) · [ADR-0023](../docs/adr/0023-medicloak-drop-failing-case-before-refusal.md)에 있습니다.
