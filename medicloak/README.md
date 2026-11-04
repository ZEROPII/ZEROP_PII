# MediCloak 운영 모드 (`python -m medicloak`)

의료진은 로그인해 가상 EMR의 외래 목록에서 환자를 열고, `.env`에 넣은 실제 LLM에게 비슷한 과거 사례를 묻습니다. MediCloak은 그 답이 화면에 나가기 전에 대화 전체의 단서를 사례마다 모아 세고, 환자를 알아볼 수 있는 값은 넓히거나 가립니다. 보안 담당자는 다른 계정으로 로그인해 같은 대화를 숫자와 함께 보고, 의료진 요청에 답하고, 원문 열람은 사유와 함께 감사 기록에 남깁니다.

화면과 서버 코드는 데모(`python -m webdemo`)와 같습니다. 다른 점은 아래뿐입니다.

| | 데모 `python -m webdemo` | 운영 `python -m medicloak` |
| --- | --- | --- |
| 대상 AI | 결정적 응답기 (LLM 호출 없음) | `.env`의 실제 LLM (기본). `--llm oracle` · `--llm dry-run`도 됨 |
| 로그인 | 없음 (화면 전환 단추) | 계정 · 역할. 의료진과 보안 담당자는 서로의 API를 못 씀 |
| 대화 | 화면 하나 = 대화 하나 | 의료진 계정마다 따로 |
| 환자 | 데모 환자 목록 | 가상 EMR 외래 목록 (DB · FHIR R4) |
| 기록 | 메모리 (끄면 지워짐) | SQLite DB (다시 켜도 남음) |
| 의료진 화면 API의 위험 숫자 | 없음 | 없음 |

## 처음 실행

저장소 맨 위 폴더에서:

```bash
source venv/bin/activate                 # 없으면: python3 -m venv venv && source venv/bin/activate
pip install -r webdemo/requirements.txt
python -m medicloak init                 # DB · 가상 EMR(576명) · 데모 계정 3개. 비밀번호를 한 번 보여 주고 파일에도 적음
python -m medicloak check-llm            # .env를 읽어 실제 LLM에 짧은 요청을 한 번 (키 값은 출력하지 않음)
python -m medicloak serve --build        # 화면 빌드 후 서버. http://127.0.0.1:8000
```

`init`이 만든 계정과 비밀번호는 `runs/medicloak/demo_accounts.txt`(권한 600)에 있습니다. `runs/`는 커밋하지 않습니다.

| 아이디 | 역할 | 이름 |
| --- | --- | --- |
| doctor1 | 의료진 | 김서연 (내과) |
| doctor2 | 의료진 | 박준호 (가정의학과) |
| privacy1 | 보안 담당자 | 이하늘 (개인정보보호팀) |

비밀번호를 정해서 만들려면 `python -m medicloak init --demo-password '원하는 비밀번호'`(셋이 같이 씀) 또는 환경변수 `MEDICLOAK_DEMO_PASSWORD`. 이미 계정이 있으면 다시 만들지 않습니다.

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
| `--no-sim` | 관제 화면용 레드팀 시뮬레이션 대화(결정적 응답기)를 만들지 않음 |
| `--port 8080` · `--host 0.0.0.0` | 주소 |
| `--keep 12` | 의료진마다 메모리에 둘 대화 수 (넘는 대화는 DB에만 남고 읽기 전용) |
| `--cookie-secure` | https로만 로그인 쿠키를 보냄 (역방향 프록시 뒤 https 운영) |
| `--no-rule-extract` | 실제 LLM 대화의 나이 · 날짜 규칙 추출을 끔. 기본은 켬: 추출기가 날짜를 약 항목 안에만 적어도 날짜를 단서로 셈 (ADR-0021) |
| `--db 경로` | DB 파일 (기본 `runs/medicloak/medicloak.db`) |

## 실제 LLM 호출 수

의료진 질문 한 번에 대상 AI 1번, 추출기 1번(형식이 틀리면 다시), 값을 바꿔야 하면 재작성기 1번과 확인 추출 1번이 듭니다. 비교 갈래 C1S는 의료진 답을 보낸 뒤 뒤에서 계산하므로 의료진은 기다리지 않지만, 값을 바꿀 때 재작성 · 확인 호출이 더 듭니다(`--no-compare`로 끔). C0은 같은 원 응답을 쓰므로 호출이 없습니다.

LLM을 부르지 않는 것: 턴 0 사례 검색 답, 입력칸의 '보내기 전 확인'(기록대로 답하면 어떻게 보일지 추정), 예시 질문, 레드팀 점검, 시뮬레이션 대화, 보안 담당자의 '질문 미리 세기'. 대상 AI 이름은 관제 화면 머리줄에, 서버를 켠 뒤의 역할별 호출 수와 토큰은 보안 담당자 '보호 정책' 화면(`/api/monitor/policy`)에 나옵니다.

## 계정

```bash
python -m medicloak users                                  # 목록
python -m medicloak users add kim --name 김의사 --role clinician --department 소아청소년과
python -m medicloak users add sec2 --name 박보안 --role security
python -m medicloak users passwd doctor1                   # 비밀번호 바꾸기 (그 계정의 로그인 세션은 모두 끊김)
```

## 화면 흐름

1. **의료진** 로그인 → **외래 진료 목록**(`/emr`). 환자를 고르면 FHIR로 읽은 진단 · 처방 기록이 나옵니다. 진료 목적(처방 · 시술·치료 · 경과·관리)을 골라 **진료 지원 AI 열기**.
2. **유사 사례 조회**(`/`)에서 사례에 묻습니다. 답은 실제 LLM이 쓰고, 환자를 알아볼 수 있는 값은 '범위'나 '비공개'로 보입니다. 숫자는 보이지 않습니다. 필요하면 **세부 정보 요청**.
3. **보안 담당자** 로그인 → **관제**(`/monitor`). 의료진 이름이 붙은 대화와 요청이 맨 위에 옵니다. **의료진 대화**(`/watch`)에서 대화를 골라 후보 수 · 판정 근거 · 단서 그래프를 보고, 관제에서 답장합니다. 원문은 사유를 적어야 열립니다.
4. **감사 기록**(`/audit`)에 로그인 · 로그아웃 · 실패, EMR 열기, 의료진 질문(사례 · 보호한 값 수 · 공개 방식, 질문 본문은 넣지 않음), 열람 · 검토 · 메시지가 남습니다.

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

로그인 없이 부르면 401, 다른 역할의 경로는 403입니다. 의료진 화면 API(`/api/workspace` · `/api/cases/…` · `/api/risk-states` …)의 후보 수 · 기준값 필드는 null로 오고, `/api/cases/{id}/policy-decision`은 403입니다.

## 보안 동작

- 비밀번호: PBKDF2-HMAC-SHA256 200,000회, 계정마다 16바이트 salt. 원문은 저장하지 않습니다.
- 세션: 임의 토큰 32바이트를 HttpOnly · SameSite=Lax 쿠키로 주고, DB에는 SHA-256만 둡니다. 12시간이 지나거나 60분 동안 쓰지 않으면 끝납니다.
- 역할 검사: 미들웨어(라우터와 같은 경로)와 API 경로마다 붙인 검사, 두 곳에서 합니다. 하위 경로 프록시 · `--root-path` 뒤에서도 같습니다. API 문서(`/docs` · `/openapi.json`)는 운영 모드에서 열지 않습니다.
- 로그인 제한: 같은 계정 · 주소에서 10분 안에 5번, 같은 계정에서 20번 틀리면 막습니다(429). 시도는 비밀번호 확인 전에 세므로 한꺼번에 보내도 넘지 못합니다. 없는 아이디는 감사 기록에 입력값을 남기지 않습니다.
- 세션 직접 조작 경로(`/api/sessions/…`, POC 재현 · 테스트용)는 의료진 대화를 열거나 바꾸지 못합니다. 의료진 대화는 관제(사유를 남긴 열람)와 의료진 대화 분석으로만 봅니다.
- API 키: `.env`에서만 읽고 화면 · 로그 · 감사 기록 · 오류 문구에 넣지 않습니다. `check-llm`도 설정 여부만 보여 줍니다.
- 과거 기록 환자: 유사 사례 검색 대상(461명)은 FHIR로 열 수 없습니다(404). 그 기록은 진료 지원 AI 답과 MediCloak 판정을 거쳐서만 보입니다.
- 원 응답 · 가린 원래 값: DB의 턴 기록과 대화 스냅숏에만 있고, 보안 담당자 API에서도 사유를 남긴 열람 때만 나갑니다.

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
tests/medicloak/              운영 모드 테스트 (가짜 HTTP 세션으로 실제 LLM 경로)
```

## 범위와 한계

- 실제 모델 호출은 이 저장소 작업 환경에서 확인하지 못했습니다(키 없음). 가짜 HTTP 세션으로 같은 코드 경로를 테스트했고, 처음 켤 때 `check-llm`으로 확인합니다.
- 합성 데이터(Synthea 576명, 모두 Massachusetts)입니다. 실제 환자 정보는 없습니다.
- 서버 한 대 · SQLite입니다. 병원 SSO, 실제 EMR(SMART on FHIR) 연동, https 종단은 아직 없습니다.
- 서버를 다시 켜면 진행 중이던 대화는 이어 갈 수 없고 읽기 전용으로 남습니다.
- 개인정보보호법 · 의료법상 검토(가명정보 처리, 접속기록 보관 기간 등)는 코드 밖에서 해야 합니다.
- 결정은 [ADR-0021](../docs/adr/0021-medicloak-production-mode.md)에 있습니다.
