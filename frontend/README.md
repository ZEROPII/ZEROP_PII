# ZEROOP2 Clinical Case Finder (프론트엔드)

의료진이 유사 사례를 AI에게 묻고, 답변에 적용된 개인정보 보호 조치(그대로 · 일반화 · 비공개)와 사례별 누적 재식별 위험(k)을 확인하는 화면이다.

React 18 · TypeScript · Vite 5 · Tailwind CSS 3 · lucide-react · React Router 6

## 실행

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
npm run build      # 타입 검사(tsc -b) + 빌드
npm test           # vitest (Mock 엔진·상태 reducer)
```

기본값은 Mock 모드다. 백엔드 없이 바로 동작한다.

## 구조

```
src/
  types/domain.ts          도메인 타입 (PatientContext, CaseSummary, ChatMessage, PrivacyTransformation,
                           DisclosureHistory, CaseRiskState, ProtectionPolicy, PreflightRiskAssessment …)
  api/
    types.ts               ClinicalCaseApi 인터페이스 (UI가 아는 유일한 계약)
    httpApi.ts             실제 백엔드 HTTP 구현 (경로는 제안 명세)
    mock/mockData.ts       가상 사례 A~E, k 예측표, Mock 질문 규칙
    mock/mockApi.ts        Mock Service (백엔드 역할 대행: 의도 파악 · Defender 판정 · 누적 상태)
    index.ts               VITE_API_MODE로 구현 선택
  state/
    workspaceReducer.ts    순수 reducer. 환자 맥락과 사례 데이터 분리, 사례별(caseId) 대화·이력·위험 분리
    WorkspaceContext.tsx   Provider + 액션(불러오기, 사례 선택, 질문 전송·재시도)
    usePreflight.ts        입력 중 질문의 사전 위험 평가 (디바운스, 이전 요청 취소)
  components/
    layout/   AppLayout, Header, ProtectionBadge
    patient/  PatientContextCard
    cases/    CaseList, CaseListItem
    chat/     ChatPanel, ChatMessage, PrivacyHighlight, PrivacyExplanation, ChatInput, PreflightWarning
    risk/     RiskPanel, RiskBar(로그 눈금), KValueBadge
    disclosure/ DisclosureHistoryPanel, DisclosureHistoryItem, PolicyDecisionModal
    common/   Card, StatusViews(로딩/오류/빈 상태), MockBadge, ActionBadge
  pages/      CaseFinderPage(3단 · 좁은 화면은 탭), HistoryPage(조회 기록), PolicyPage(보호 정책)
```

## 설계 원칙

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
| 사례 A 환자는 어느 도시에 살았나요? | 사전 경고 "7명에서 3명", 전송하면 거주 도시 비공개 |
| 사례 A 환자의 동반질환은? | 질환군으로 일반화, k 7 → 6 |
| 사례 B 환자는 몇 살에, 언제 시술을 받았나요? | 60~64세 · 2019년으로 일반화, k 31 → 9 |
| 시술 후 처방 기간은? / 사례 B·C와 처방 비교 | 새 QI 없음, k 유지 |
| 사례 D에 대한 나이·성별 질문 | 추가 공개 제한 상태에서 비공개 |
| `#오류`가 들어간 질문 | Mock 서버 오류 (오류 상태 UI 확인) |

## 실제 백엔드 연동

1. `.env.example`을 `.env.local`로 복사하고 `VITE_API_MODE=http`, `VITE_API_BASE_URL=<주소>` 설정.
2. 이 저장소에는 아직 HTTP API가 없다. `src/api/httpApi.ts`의 경로는 제안 명세다:

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

3. 백엔드 명세가 다르면 `httpApi.ts`(필요하면 응답 변환 함수)만 고친다. UI 컴포넌트는 `ClinicalCaseApi`만 쓰므로 바꿀 필요가 없다.
4. 백엔드 쪽 대응 관계: `PrivacyAction`은 `medical/defense.py`의 allow · generalize · suppress, `ProtectionPolicy.minK/suppressK`는 `generalize_threshold/suppress_threshold`, `arm`은 C0 · C1 · C1S.
