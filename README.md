<p align="center">
  <img src="docs/images/banner.png" alt="MediCloak: 과거 사례는 진료에 쓰고, 그 환자는 드러나지 않게" width="100%">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/KISIA_2026-AI_보안_기술개발_개인정보반-10262e?style=flat-square" alt="KISIA 2026 AI 보안 기술개발 개인정보반">
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.11">
  <img src="https://img.shields.io/badge/FastAPI-서버-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/React-18-0b7a75?style=flat-square&logo=react&logoColor=white" alt="React 18">
  <img src="https://img.shields.io/badge/HL7_FHIR-R4-0b7a75?style=flat-square" alt="FHIR R4">
  <img src="https://img.shields.io/badge/tests-pytest_976_·_vitest_87-16a374?style=flat-square" alt="pytest 976 passed, vitest 87 passed">
  <a href="docs/adr/README.md"><img src="https://img.shields.io/badge/ADR-33건-5b5bf0?style=flat-square" alt="ADR 33건"></a>
</p>

<p align="center">
  <b>사례 검색 → 대상 AI 초안 → 단서 추출 → 누적 후보 수 계산 → 넓히거나 가림 → 다시 확인 → 화면</b><br>
  병원 진료 지원 AI의 답이 과거 환자를 드러내지 않도록, 답이 나가기 직전에 검사하는 개인정보 보호 계층
</p>

> KISIA AI 보안 기술개발 개인정보반(2026.8.17 ~ 11.6) 팀 프로젝트 · **Team Zero PII**

---

## 만들게 된 계기

병원의 진료 지원 AI는 의료진이 "지금 환자와 비슷한 과거 사례"를 대화로 찾아보게 해 줍니다. 답에서 이름과 등록번호를 지워도, 질문이 이어지면 진단 · 처방 약 · 처방 시작일 · 나이 · 거주 지역이 한 사람에 대한 단서로 쌓입니다. 이 프로젝트의 기준 집단(합성 환자 461명)으로 세어 보면, 정확한 날짜 하나만 알려 줘도 98.5%의 환자가 후보 5명 미만으로 좁혀집니다.

답 하나하나를 따로 검사해서는 이렇게 쌓이는 위험을 막지 못합니다. **MediCloak**은 답이 화면에 나가기 전에 대화 전체에서 나온 단서를 사례마다 모아, 조건이 같은 과거 환자가 몇 명 남는지(k) 셉니다. 5명 아래로 좁혀지는 값만 상위 범주로 넓히거나 가리고, 나머지는 그대로 답합니다. 모델을 다시 학습시키거나 원본 기록을 고치지 않고, RAG의 답 전달 단계에 들어갑니다.

<p align="center">
  <img src="docs/images/clinic-flow.gif" alt="의료진이 사례 1의 약과 시작 시기를 묻자 시작 시기만 비공개로 표시되는 장면" width="760">
  <br><sub>▲ 의료진이 사례 1의 약과 시작 시기를 묻자 시작 시기만 '비공개'로 나가고, '왜 그런가요?'에 그 이유가 나옵니다</sub>
</p>

---

## 한눈에 보기

<table>
<tr>
<td width="50%"><a href="docs/images/screen-clinic.png"><img src="docs/images/screen-clinic.png" alt="의료진 유사 사례 조회 화면"></a></td>
<td width="50%"><a href="docs/images/screen-monitor.png"><img src="docs/images/screen-monitor.png" alt="보안 담당자 실시간 관제 화면"></a></td>
</tr>
<tr>
<td><b>의료진 · 유사 사례 조회</b><br>비슷한 과거 사례 5건에 묻습니다. 환자를 알아볼 수 있는 값은 '비공개'나 범위로 보이고, 위험 숫자는 보이지 않습니다.</td>
<td><b>보안 담당자 · 실시간 관제</b><br>같은 대화를 숫자와 함께 봅니다. 그대로 냈다면 후보가 1명이었을 답을 157명으로 지킨 기록과 의료진 요청이 올라옵니다.</td>
</tr>
<tr>
<td><a href="docs/images/screen-watch.png"><img src="docs/images/screen-watch.png" alt="의료진 대화 위험 분석 화면"></a></td>
<td><a href="docs/images/screen-report.png"><img src="docs/images/screen-report.png" alt="레드팀 점검 리포트 화면"></a></td>
</tr>
<tr>
<td><b>의료진 대화 위험 분석</b><br>사례마다 후보가 단서별로 줄어든 과정(461 → 189 → 157)과 답마다의 판정 근거를 봅니다.</td>
<td><b>레드팀 점검 리포트</b><br>방어 없음 · 턴별 방어 · 누적 방어로 같은 공격 대화를 돌려, 기준 아래로 내려간 대화와 답변 유용도를 비교합니다.</td>
</tr>
</table>

<sub>화면은 API 키 없이 시연용 응답기로 켠 운영 모드에서 찍었고, 공개 전 검사가 보이도록 입력 게이팅은 껐습니다. 리포트 화면의 기준 평가는 10턴까지 센 값이라 아래 검증 결과(8턴)와 숫자가 조금 다릅니다.</sub>

---

## 어떻게 막나

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/flow-dark.png">
  <img src="docs/images/flow-light.png" alt="질문부터 화면까지 답 하나가 나가는 7단계: 유사 사례 검색, 입력 게이팅, 대상 AI 초안, 단서 추출, 후보 수 k, 판정, 다시 확인" width="100%">
</picture>

- **대화 전체로 셉니다.** 이번 답의 단서에 같은 대화에서 앞서 나간 값, 같은 과거 환자에 대해 다른 대화에서 나간 값(최근 90일)까지 합쳐 판정합니다.
- **같은 진료 사건으로 묶어 셉니다.** 환자 한 명에게 진단이 평균 8.8개, 처방이 6.8개 있어서 값을 따로 맞추면 후보가 부풀려집니다. '60대에 당뇨병 진단'은 한 사건이 두 조건을 함께 만족해야 후보로 남습니다. 576명 기준으로 따로 세면 25명, 사건으로 세면 4명입니다.
- **필요한 만큼만 바꿉니다.** 기준은 후보 5명입니다. 새 단서를 모두 더해도 5명보다 많으면 그대로 내고, 아니면 의료 온톨로지의 상위 범주로 넓히고, 원래 값으로 3명 이하인 값은 가립니다. 나이는 5세 구간, 날짜는 월보다 자세히 내지 않습니다.
- **고친 답도 다시 셉니다.** 재작성한 답을 다시 추출해 처음부터 셉니다. 통과하지 못하면 값 치환, 사례 빼기, 거절 순으로 넘어갑니다.
- **사람이 열어 줄 길을 둡니다.** 진료에 꼭 필요한 값은 의료진이 세부 정보 요청을 보내고, 보안 담당자가 함께 공개했을 때의 후보 수를 확인한 뒤 승인합니다. 열람 · 승인 · 규칙은 사유와 함께 감사 기록에 남습니다.

---

## 기능

**의료진** · 진료 지원 AI

- **[외래 진료 목록](docs/images/screen-emr.png)**: 가상 EMR(FHIR R4)에서 외래 환자와 진료 목적(처방 · 시술·치료 · 경과·관리)을 골라 진료 지원 AI를 엽니다. 목록에는 생년과 거주 지역이 없습니다.
- **[유사 사례 조회](docs/images/screen-clinic.png)**: 사례별 대화, 찾은 사례 전체에 묻기, 답에 실제로 나온 값만 모으는 사례 노트, 보내기 전 확인, '왜 그런가요?', 세부 정보 요청

**보안 담당자** · MediCloak 관제

- **[실시간 관제](docs/images/screen-monitor.png)**: 세 줄 요약(위험했던 것 · 시스템이 한 일 · 내가 할 일), 방어 방식별 후보 수 눈금, 사유를 적는 원문 열람, 값 공개 승인, 대화별 규칙, 검토 보조 초안
- **[의료진 대화 분석](docs/images/screen-watch.png) · [단서 그래프](docs/images/screen-graph.png)**: 후보가 단서마다 줄어든 과정, 답마다의 판정 표(그대로였다면 몇 명이었는지), 사례와 단서의 연결
- **[레드팀 리포트](docs/images/screen-report.png)**: 실제 LLM으로 공격 대화를 돌려 방어 방식별로 비교합니다. 모델이나 판정 규칙이 바뀐 채로 서버를 켜면 점검이 자동으로 돌고 직전 결과와 비교합니다.
- **[감사 기록](docs/images/screen-audit.png) · [보호 정책](docs/images/screen-policy.png)**: 로그인 · EMR 열기 · 질문 · 열람 · 승인 · 규칙 · 레드팀 기록, 지금 걸린 판정 기준과 보호 설정

---

## 시스템 구성

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/arch-dark.png">
  <img src="docs/images/arch-light.png" alt="의료진 화면과 보안 담당자 관제가 FastAPI 서버에 붙고, 서버는 SQLite · FHIR · 사례 문서 · LLM을 쓰며 판정은 연구 하네스 코드를 그대로 쓰는 구성" width="100%">
</picture>

- 화면 두 개(의료진, 보안 담당자)와 서버 하나로 이루어집니다. 역할은 로그인 계정으로 나뉘고, 의료진 화면 API로는 후보 수 같은 위험 숫자를 보내지 않습니다.
- 서버의 판정은 연구 하네스(`medical/`)의 후보 수 계산(kcalc)과 Defender를 그대로 불러 씁니다. 실험에서 잰 방어와 화면에서 도는 방어가 같은 코드입니다.
- 데이터는 Synthea 합성 환자 576명입니다. 461명은 과거 기록(검색 대상이자 기준 집단)으로, 나머지는 외래 환자로 씁니다. 실제 환자 정보는 없습니다.

---

## 검증 결과

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/results-dark.png">
  <img src="docs/images/results-light.png" alt="공격 대화 296건에서 방어 없음 95.6%, 턴별 방어 83.1%, 누적 방어 0%가 기준 아래로 좁혀졌고, 누적 방어는 의료정보 87.2%를 그대로 냈다" width="100%">
</picture>

| 측정 | 조건 | 결과 |
| --- | --- | --- |
| 기준 아래로 좁혀진 대화 | 모의 POC, 공격 대화 296건 × 3갈래, 8턴, 결정적 응답기 | 방어 없음 95.6% · 턴별 방어 83.1% · **누적 방어 0%**. 방어 없음과 누적 방어의 짝 검정(exact McNemar) 283 : 0 |
| 누적 방어의 정보 유지 | 같은 실행의 판정 8,840건 | 의료정보는 87.2%를 그대로 냈고, 개인정보는 34.9%를 가렸습니다(시기는 70.3%). 공개 단서 유지율 0.65 |
| 단서 추출 정확도 | 규칙을 고정한 뒤 처음 보는 질의 환자 13명, claude-haiku-4.5, 팀 고정본 채점 | 정밀도 97.0% · 재현율 89.2% · F1 0.929 |
| 실제 LLM 소규모 측정 | 질의 환자 6명, 8턴, claude-haiku-4.5 | 방어 없음 5/6, 누적 방어 0/6(시스템 판정). 원본 사실표와 대조해 다시 세니 누적 방어 2/6이었습니다. 날짜 단서가 정규화되지 않아 위험으로 세어지지 않은 것이 원인이었고, 판정 규칙 v8에서 고쳤습니다([ADR-0033](docs/adr/0033-rag-remeasure-tooling-and-period-value-fix.md)) |
| 처리 시간 | 같은 실측, 턴 1 이후 평균 | 방어 없음 12.4초 · 누적 방어 19.4초. 늘어난 시간은 대부분 재작성과 다시 확인 추출입니다 |

<details>
<summary>다시 세는 명령 (LLM 호출 없음)</summary>

```bash
python -m medical.simulate --out runs/medical/sim_staged --profile staged --fuzzer uniform   # 모의 POC, 약 30분
python scripts/verify_result3.py runs/medical/sim_staged                                     # 위 표의 위반율과 판정 비율
```

단서 추출 정확도의 기록과 채점 방법은 [medical/scoring/결과_기록.md](medical/scoring/결과_기록.md)에 있습니다.
</details>

**읽을 때 알아 둘 점**

- k는 고정된 기준 집단(461명) 안에서 후보가 몇 명 남는지입니다. 실제 신원 확인 여부나 법적 안전성을 보장하는 값이 아닙니다.
- 데이터는 한 주(Massachusetts)의 합성 환자이고, 실제 LLM 측정은 6명 규모입니다.
- 후보 전원이 같은 값을 가지면 그 값은 알려질 수 있습니다(동질성). k로는 막지 못하는 부분입니다.

---

## 보안 설계

- **역할 분리.** 의료진과 보안 담당자는 서로의 API를 쓰지 못합니다. 미들웨어와 경로별 검사 두 곳에서 확인하고, 로그인 없이 부르면 401, 다른 역할의 경로는 403입니다.
- **비밀번호와 세션.** 비밀번호는 PBKDF2-HMAC-SHA256 200,000회와 계정별 salt로 저장합니다. 세션 토큰은 HttpOnly 쿠키로 주고 DB에는 SHA-256만 둡니다. 12시간이 지나거나 60분 동안 쓰지 않으면 끝나고, 같은 계정 · 주소에서 10분에 5번 틀리면 막습니다.
- **원문 열람.** 보안 담당자도 사유를 고르고 확인하려는 내용을 적어야 원 응답과 가린 값을 봅니다. 감사 기록과 관제 화면에는 환자 번호 대신 HMAC으로 만든 기호(`P-3f9a1c`)가 남습니다.
- **과거 기록 환자.** 검색 대상 461명은 FHIR로 열 수 없고, 진료 지원 AI의 답과 MediCloak 판정을 거쳐서만 보입니다.
- **민감 정보.** 물질 사용 · 정신 건강 · 생식 · HIV 관련 값은 후보가 10명 이상일 때만 내고, 미성년 시기 물질 사용 장애 환자는 검색 대상에서 뺍니다.
- **답 시간 한도.** 45초 안에 확인을 마치지 못한 답은 내보내지 않고 안내 문장을 보냅니다.
- **API 키.** `.env`에서만 읽고 화면 · 로그 · 감사 기록 · 오류 문구에 넣지 않습니다.

자세한 동작과 운영할 때 정해야 할 것(외부 LLM으로 나가는 데이터, 승인 당직, 감사 기록 보관)은 [medicloak/README.md](medicloak/README.md)에 있습니다.

---

## 실행

Python 3.10 이상(3.11 · 3.13에서 확인)과 화면 빌드용 Node.js 18 이상이 필요합니다.

```bash
git clone https://github.com/ZEROPII/ZEROP_PII.git
cd ZEROP_PII
python3 -m venv .venv && source .venv/bin/activate
pip install -r webdemo/requirements.txt
```

**운영 모드** (로그인 · 가상 EMR · `.env`의 실제 LLM)

```bash
cp .env.example .env                  # LLM_API_KEY · LLM_API_BASE · LLM_MODEL 채우기
python -m medicloak init              # DB · 가상 EMR 576명 · 처음 계정 3개
python -m medicloak check-llm         # 실제 LLM에 짧은 요청 한 번 (키 값은 출력하지 않음)
python -m medicloak serve --build     # 화면 빌드 후 서버, http://127.0.0.1:8000
```

계정은 의료진 `doctor1` · `doctor2`, 보안 담당자 `privacy1`이고 비밀번호는 `runs/medicloak/initial_accounts.txt`에 적힙니다. 키 없이 같은 화면을 보려면 `python -m medicloak serve --llm oracle --build`(결정적 응답기), 로그인 없이 둘러보려면 `python -m webdemo --build`를 씁니다.

**테스트**

```bash
python -m pytest -q                   # 976 passed, 3 skipped (LLM은 가짜 HTTP 세션)
cd frontend && npm test               # vitest 87 passed
```

---

## 저장소 구성

```text
ZEROP_PII/
├─ medicloak/              # 운영 모드 실행: init · serve · users · check-llm
├─ webdemo/backend/        # FastAPI 서버: 로그인 · 진료 대화 · 공개 전 검사 · 관제 · 레드팀
├─ frontend/               # React 화면: 진료 지원 AI(의료진) · MediCloak 관제(보안 담당자)
├─ medical/                # 의료 시나리오 하네스: 문서 · 검색 · 대상 AI · 추출 · kcalc · Defender · 퍼저
│  ├─ bundle/              # 팀 전달 고정본 (정규화 · 하네스 참조 구현 · 검증)
│  ├─ scoring/             # 단서 추출 채점과 보류 검증
│  └─ terminology.py       # 의료 용어 RAG (이유진)
├─ risk_defender/          # Privacy State · k 계산 · 판정 정책 (이유진)
├─ fuzzer/                 # k 피드백으로 변형 전략을 고르는 공격 질문 생성 (한재이)
├─ evaluation/             # 평가 지표 정의 · 통계 검정, eval-metrics (이정민)
├─ eval_demo/              # 평가 지표 22개 대시보드 (이정민)
├─ data/medical/           # 의료 온톨로지 노드 · 사건연결표 · 표현-노드 매핑표 · Seed Registry
├─ core/                   # .env 설정 · LLM 호출 (모든 갈래가 같이 씀)
├─ scripts/                # 측정 · RAG 재측정 · 결과 다시 세기 · ADR 도구
├─ tests/                  # pytest 979개 (가짜 HTTP 세션으로 LLM 경로까지)
└─ docs/                   # ADR 33건 · 의료 시나리오 · 평가 통합 문서 · README 그림
```

SynthPAI(일반 게시글) 단계의 모듈(`target_llm/` · `qi_extractor/` · `normalizer/` · `attack/` · `ontology/` · `adapters/` · `orchestrator/` · `validation/` · `api_server/` · `analysis/` · `evaluation_v1/` · `risk_defender_synthpai/`)은 그대로 두었습니다. 의료로 옮기기 전 실험을 재현할 때 쓰며, 설명은 [docs/research_harness.md](docs/research_harness.md)에 있습니다. 평가 프로토타입(`eval/`과 루트의 `eval_baseline.py` · `log_schema.py` · `run_demo.py`)은 [docs/evaluation.md](docs/evaluation.md)를 보세요.

## 문서

- [medicloak/README.md](medicloak/README.md): 운영 모드의 옵션, 화면 흐름, API, 보안 동작, 운영 가이드
- [docs/medical.md](docs/medical.md): 의료 시나리오 하네스와 기준 집단 사전 점검
- [docs/adr/](docs/adr/README.md): 설계 결정 기록 33건
- [docs/evaluation.md](docs/evaluation.md): 평가 통합 문서(evaluation_proto · eval-metrics)
- [docs/rag_remeasure/](docs/rag_remeasure/README.md): RAG 기준 재측정 도구와 원본 대조 검증기
- [docs/README.md](docs/README.md): 나머지 문서 안내

---

## 팀

**Team Zero PII**

| 이름 | 역할 | 맡은 일 |
| --- | --- | --- |
| 양승준 | System Integration · Development Lead | 대상 AI(RAG)와 단서 추출, 모듈 통합, MediCloak 서버와 화면, 실험 자동화 |
| 한재이 | Privacy Fuzzing · Offensive Security Lead | 공격 시나리오, Seed와 변형, k 피드백 퍼저 |
| 이유진 | Privacy Risk · Defense Lead | Privacy State와 k 계산, 판정 정책, 의료 용어 RAG |
| 이정민 | Evaluation · Assurance Lead | 실험 설계, 평가 지표, 평가 대시보드 |
| 배성윤 | Research · Policy & Privacy Model Lead | 위협 모델, 준식별정보 정의, 온톨로지와 연구 논리 |

- 주간 스크럼과 Jira 백로그로 진행했고, 기준 · 구조 · 실험 방식을 바꾼 결정은 [ADR](docs/adr/README.md)로 남겼습니다.
- 논문: 「대화형 의료 AI의 누적 준식별정보 노출에 대한 공개 전 방어」, 한국융합보안학회 2026 추계학술대회

<sub>모든 환자 데이터는 Synthea로 만든 합성 데이터입니다. 화면의 의료진 · 보안 담당자 이름과 계정은 시연용입니다.</sub>
