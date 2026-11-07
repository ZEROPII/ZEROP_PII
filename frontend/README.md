# MediCloak 프론트엔드 (ZEROOP2 Clinical Case Finder 기반)

한 앱에 역할이 다른 두 화면이 있다.

- **의료진 화면** (`/`, `/history`, `/guide`): 병원 EMR 안의 진료 지원 AI. 유사 사례를 묻고 답을 받는다. 보호 조치는 '범위'(넓힘) · '비공개'(가림)로만 보이고, 후보 수(k) 같은 재식별 위험 숫자는 보이지 않는다. 사례 노트(옵시디언 방식)와 개인정보 보호 담당자 메시지가 있다.
- **보안 담당자 화면 (MediCloak 관제)** (`/monitor`, `/watch`, `/report`, `/audit`, `/terms`, `/policy`): 같은 대화의 사례별 누적 재식별 위험(k), 판정 근거, 단서 그래프, 감사 기록, 의료진 요청 답장.

> **통합 데모:** 보안 담당자 화면은 데모 서버에만 있는 API를 쓴다 (ADR-0020: 의료진 화면과 위험 분석을 나눈 이유).
> 데모 서버와 함께 쓰려면 저장소 루트에서 `python -m webdemo --build` 후 http://127.0.0.1:8000 (자세한 것은 `../webdemo/README.md`).
> 화면을 고치면서 보려면 `python -m webdemo`를 켜 둔 채 여기서 `npm run dev:demo`. 관제 화면은 데모 서버에만 있는 API를 쓰므로
> Mock 모드나 `api_server`에 붙였을 때는 '데모 서버에서만 볼 수 있다'는 안내가 나온다. 의료진 화면은 세 모드 모두 그대로 동작한다.

React 18 · TypeScript · Vite 5 · Tailwind CSS 3 · lucide-react · React Router 6

## 실행

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 (Mock)
npm run dev:demo   # 데모 서버(python -m webdemo, 8000번)에 붙어서
npm run build:demo # 데모 서버가 내보낼 dist/ 만들기
npm run build      # 타입 검사(tsc -b) + 빌드
npm test           # vitest (Mock 엔진·상태 reducer)
```

기본값은 Mock 모드다. 백엔드 없이 바로 동작한다.

## 구조

```
src/
  types/domain.ts          도메인 타입 (PatientContext, CaseSummary, ChatMessage, PrivacyTransformation,
                           DisclosureHistory, CaseRiskState, ProtectionPolicy, PreflightRiskAssessment, ClinicMessage …)
  types/monitor.ts         관제 API 타입 (MonitorRow, MonitorDetail, ThreadMessage …)
  api/
    types.ts               ClinicalCaseApi 인터페이스 (UI가 아는 유일한 계약)
    httpApi.ts             실제 백엔드 HTTP 구현 (데모 서버에만 있는 경로는 404면 기능 없음으로 처리)
    monitorApi.ts          관제 API (데모 서버에만 있음)
    mock/mockData.ts       가상 사례 A~E, k 예측표, Mock 질문 규칙
    mock/mockApi.ts        Mock Service (백엔드 역할 대행: 의도 파악 · Defender 판정 · 누적 상태 · 메시지 예시 답장)
    index.ts               VITE_API_MODE로 구현 선택
  state/
    workspaceReducer.ts    순수 reducer. 환자 맥락과 사례 데이터 분리, 사례별(caseId) 대화·이력·위험 분리
    WorkspaceContext.tsx   Provider + 액션(불러오기, 사례 선택, 질문 전송·재시도, 조용한 새로 고침 refreshLive)
    usePreflight.ts        입력 중 질문의 사전 위험 평가 (디바운스, 이전 요청 취소)
    ClinicMessages.tsx     의료진 ↔ 보호 담당자 메시지 (주기적으로 받기, 읽음 표시)
    TermContext.tsx        의료 용어 패널 · 답변 속 용어 자동 표시
  lib/
    clinicianCopy.ts       의료진 화면 문구 (재식별 위험 숫자를 쓰지 않음)
    caseNote.ts            사례 노트: 속성 · 연결된 질문(백링크) · 같은 값이 나온 사례
    answerLines.ts         '사례N · [기록M] 항목: 값' 답을 표로 나누기
    clueGraph.ts           단서 그래프 만들기와 힘 배치 (난수 없음)
  components/
    layout/   AppLayout(역할별 틀), ClinicianShell(EMR 머리줄), TopBar · CommandPalette(관제), ProtectionBadge
    clinic/   PatientBanner('지금 보는 환자' 띠), EmrCaseList, ClinicalChat, ClinicalMessage, ClinicValue(범위 · 비공개), CaseNotePanel
    emr/      ChartSummary(차트 요약), VisitHistory(내원 이력: 해마다 · 펼치면 날짜마다), SimilarCaseBox(유사 사례 찾기 · 진료 지원 AI 열기 · 멈추기), ConsultDialog(협진 의뢰 보내기), BreakGlassDialog(담당 외 환자 열기, 등록번호)
    chat/     ChatMessage, PrivacyHighlight, PrivacyExplanation (관제 쪽 숫자 있는 대화), ChatInput
    graph/    ClueGraph
    monitor/  QueueTable, SessionDetail(메시지 · 단서 그래프 · 질문 흐름), RevealDialog
    risk/     RiskPanel, RiskBar(로그 눈금), KValueBadge
    disclosure/ DisclosureHistoryPanel, DisclosureHistoryItem, PolicyDecisionModal
    common/   Card, StatusViews(로딩/오류/빈 상태), MockBadge, ActionBadge
  pages/      의료진: ClinicalAssistPage(3단 · 좁은 화면은 탭), HistoryPage, GuidePage
              관제: MonitorPage, WatchPage(의료진 대화), ReportPage, AuditPage, TerminologyPage, PolicyPage
```

## 설계 원칙

- **의료진 화면에는 위험 숫자가 없다.** 후보 수 · 기준값은 보안 담당자 화면에만 보인다. 의료진 문구는 `lib/clinicianCopy.ts`에서만 만들고 `lib/clinicianView.test.ts`가 숫자가 섞이지 않았는지 검사한다. (API 응답에는 아직 k가 들어 있다. ADR-0020 남은 일.)
- **판정은 백엔드 몫.** k 계산, QI 결합, 누적 State 판정, 사전 위험 평가 모두 백엔드가 한다. 화면은 `CaseRiskState`(riskLevel · statusLabel · disclosureAllowed · policyDecision · version)를 그대로 표시하고 k 값만으로 위험을 확정하지 않는다.
- **보호 표시는 메타데이터 기반.** 답변 본문은 `segments`로 오고, 보호 조치가 걸린 조각은 `transformationId`로 `PrivacyTransformation`을 가리킨다. 문구를 보고 추측하지 않는다.
- **원본 값을 받지 않는다.** 타입에 일반화 이전 원본 값을 담는 필드가 없다. 이력에는 "1세 단위 → 5세 구간"처럼 안전한 설명만 쓴다.
- **환자 맥락 분리.** `PatientContext`는 별도 상태 슬롯이며 질문 전송 요청에 들어가지 않는다 (사례 검색에는 `contextId`만 사용).
- **사례별 격리.** 대화·공개 이력·위험 상태·입력 초안 모두 caseId 키로 보관. 응답은 요청한 사례에만 반영하고, 위험 상태는 더 큰 `version`일 때만 덮어쓴다.
- **사전 경고는 보조.** 전송 시 백엔드가 다시 검증한다는 전제다. 경고가 떠도 전송은 막지 않는다.
- 인증은 쿠키 세션(`credentials: 'include'`) 전제. 토큰·응답 본문을 콘솔에 남기지 않는다.

## Mock 데이터

`src/api/mock/`만 Mock이다. 사례 A~E와 k 값(7 · 31 · 18 · 5 · 42)은 UI 확인용 예시이며 실험 측정값이 아니다. 기준값 generalize 5 · suppress 3은 `medical/config.py`와 같다. Mock 데이터에는 화면에 `MOCK` 표시가 붙는다.

Mock이 알아듣는 질문 (키워드 규칙, `mockData.ts`의 `QI_PATTERNS`·`TOPIC_PATTERNS`):

| 질문 예 | 결과 |
|---|---|
| 사례 A 환자는 어느 도시에 살았나요? | 의료진 화면: 보내기 전 "비공개로 표시됩니다", 전송하면 거주 도시 비공개 (사전 평가 원문은 "7명에서 3명") |
| 사례 A 환자의 동반질환은? | 질환군으로 일반화, k 7 → 6 |
| 사례 B 환자는 몇 살에, 언제 시술을 받았나요? | 60~64세 · 2019년으로 일반화, k 31 → 9 |
| 시술 후 처방 기간은? / 사례 B·C와 처방 비교 | 새 QI 없음, k 유지 |
| 사례 D에 대한 나이·성별 질문 | 추가 공개 제한 상태에서 비공개 |
| `#오류`가 들어간 질문 | Mock 서버 오류 (오류 상태 UI 확인) |
| 답 아래 '세부 정보 요청' | 1.5초 뒤 예시 답장이 붙는다 (Mock에는 관제 화면이 없어서) |

## 실제 백엔드 연동

1. 백엔드 실행: 저장소 루트에서 `python -m api_server` (실제 LLM, `.env` 필요) 또는 `python -m api_server --dry-run` (가짜 LLM). 자세한 것은 `../api_server/README.md`.
2. `.env.example`을 `.env.local`로 복사하고 `VITE_API_MODE=http`, `VITE_API_BASE_URL=/api` 설정 (개발 서버가 `/api`를 127.0.0.1:8000으로 프록시).
3. 경로 (백엔드 `api_server`가 모두 구현, 접두사 `/api`):

| 메서드 | 경로 | 응답 타입 |
|---|---|---|
| GET | /workspace | WorkspaceEnvironment |
| GET | /protection-policy | ProtectionPolicy |
| GET | /patient-context | PatientContext |
| GET | /cases?patientContextId= | CaseSummary[] |
| GET | /cases/{id}/session | ConversationSession |
| POST | /cases/{id}/messages | SendQuestionResponse |
| POST | /cases/{id}/preflight | PreflightRiskAssessment |
| GET | /risk-states | CaseRiskState[] |
| GET | /cases/{id}/disclosures | DisclosureHistory |
| GET | /cases/{id}/policy-decision | PolicyDecisionRationale |
| GET · POST | /clinic/messages | ClinicMessage[] (데모 서버만. 없으면 세부 정보 요청 버튼을 숨김) |

   http 모드에서 사전 위험 평가(preflight)는 연구 모듈에 해당 기능이 없어 `supported: false`로 오고, 입력창 아래에 미지원으로 표시된다.
   사례 목록에는 검색 순위·유사도만 오고 사례 진단명은 오지 않는다 (Defender를 거치지 않은 공개가 되므로).
4. 백엔드 명세가 다르면 `httpApi.ts`(필요하면 응답 변환 함수)만 고친다. UI 컴포넌트는 `ClinicalCaseApi`만 쓰므로 바꿀 필요가 없다.

### MediCloak 운영 모드 (`python -m medicloak`)

같은 빌드(`npm run build:demo`)가 데모 서버와 운영 서버를 모두 연다. 화면은 켤 때 `/api/auth/me`로 서버 종류를 가른다: 404면 로그인 없는 데모(화면 전환 단추), 401이면 로그인 화면, 200이면 로그인한 계정의 역할이 화면을 정한다(`src/state/AuthContext.tsx`, `components/layout/AppLayout.tsx`). 어느 요청이든 401이 오면 로그인 화면으로 돌아간다(`src/api/session.ts`).

- 의료진 화면 API는 후보 수 · 기준값을 null로 보낸다(타입 `number | null`). 의료진 화면은 원래 숫자를 그리지 않았다.
- 보안 담당자 '의료진 대화'(`/watch`)는 대화를 골라 `createHttpApi('/api/watch/{대화}')`로 같은 계약을 숫자와 함께 받는다(안쪽 `WorkspaceProvider`). 의료진 화면 상태(`WorkspaceProvider`)는 의료진 틀 안에서만 만든다.
- 보호 정책(`/policy`)은 `/api/monitor/policy`에서 받는다.
- 내 담당 환자(`/emr`, `/emr/{환자 id}`, 운영 모드 의료진만): `src/api/emrApi.ts`가 `/api/emr/worklist` · `/api/emr/chart` · `/api/emr/consults` · `/api/emr/break-glass` · `/api/emr/launch`를 부른다. 왼쪽 목록(맨 위 받은 협진 의뢰) → 가운데 차트 요약 → 오른쪽 유사 사례 찾기 순서이고, 넓은 화면에서는 차트와 유사 사례 찾기가 따로 스크롤된다. 이 화면에서는 '지금 보는 환자' 띠를 숨긴다(ADR-0034 · ADR-0036).
- 기다리는 동안: `components/common/StageTrack.tsx`가 진행 API의 `step`을 막대 셋(답 쓰기 → 보호 기준 확인 → 필요하면 고쳐 쓰기)으로 보인다. 걸린 초는 보이지 않는다. 멈추기는 `emrApi.stopQuestion` · `stopLaunch`이고, 질문이 409(`stopped`)로 끝나면 `send/stopped`가 보낸 질문을 지우고 입력칸에 되돌린다(ADR-0035).
- 보호 표시: `ClinicValue`의 '비공개' · '범위'는 단추이고 누르면 설명 창(화면 기준 fixed)이 뜬다. 답 아래 `ChangeMap`이 사례마다 가리고 넓힌 항목을 보인다(ADR-0037). FHIR(`/fhir/…`)는 EMR 연동 API로 남아 있고, 개발 서버도 `/fhir`를 8000번으로 넘긴다(`vite.config.ts`).
- EMR 접근(`/emr-access`, 운영 모드 보안 담당자만): `/api/monitor/emr`로 환자 기호 · 담당 · 접근 기록 · 예외 열람을 받고, 차트는 `RevealDialog`로 사유를 적어 연다.
5. 백엔드 쪽 대응 관계: `PrivacyAction`은 `medical/defense.py`의 allow · generalize · suppress, `ProtectionPolicy.minK/suppressK`는 `generalize_threshold/suppress_threshold`, `arm`은 C0 · C1 · C1S.
