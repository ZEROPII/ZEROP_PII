# api_server — Clinical Case Finder 백엔드 (`python -m api_server`)

`frontend/`의 http 모드가 부르는 FastAPI 서버. `medical/` 연구 하네스를 **고치지 않고** 그대로 호출한다.
판정·k 계산은 모두 연구 모듈이 하고, 이 계층은 결과를 `frontend/src/types/domain.ts` 계약 모양으로 옮기기만 한다.

## 실행

```bash
pip install fastapi uvicorn                   # 이미 설치돼 있으면 생략 (확인: fastapi 0.128, uvicorn 0.40)
python -m api_server                          # 실제 LLM (.env 필요), C1, 질의 환자 T0001
python -m api_server --dry-run                # 가짜 LLM (medical.llm.MockRoleLLM, 토큰 0, 숫자 의미 없음)
python -m api_server --arm C0|C1|C1S --trial T0003 --port 8000

cd frontend && VITE_API_MODE=http VITE_API_BASE_URL=/api npm run dev   # 개발 서버 프록시 /api → 127.0.0.1:8000
```

시작할 때 문서·kcalc를 적재한다 (약 10초, LLM 0회). 기록은 `runs/api/session_<시각>/`
(`턴기록.jsonl` 원 응답 포함 · `llm_usage.jsonl` · `run_meta.json` · `RAG문서.jsonl`)에만 남고 화면으로는 가지 않는다.
`runs/`는 .gitignore 대상이며 기존 실험 폴더(`runs/medical/…`)는 건드리지 않는다.

## 한 질문의 흐름 (연구 파이프라인 그대로)

1. `POST /api/cases/{caseId}/messages` → 질문에 '사례N' 표기가 없으면 `사례N에 대한 질문: ` 을 붙여 대상 AI에 보낸다 (화면에는 원문).
2. `ArmRun._turn` (medical/session.py): 대상 AI 원 응답 → 추출기 → 사례별 정규화 → 공개 게이트
   - C0 그대로 / C1 누적 State로 Defender 판정 → 재작성기 → 재추출 확인 → 결정적 치환 → 거절 / C1S 빈 State로 판정
   - 원 응답 추출 실패 시 C1·C1S는 거절 문장 (fail-closed)
3. 공개된 답변에서 나온 관찰만 State에 반영 → 사례별 kcalc k.
4. 응답: 공개된 답변(segments) · 조치 목록(Defender 계획) · k 전후 · 사례 위험 상태 · 다른 사례가 언급됐으면 그 사례 상태.

세션 준비(턴 0)는 `make_prefix`의 LLM 없는 부분과 같다: `plan_trials` 순서의 질의 환자 → 바인딩 → 코드 집합 검색 상위 5 → 대상 AI 시스템 프롬프트.
자동 사례 검색 질문(턴 0 LLM 호출)은 보내지 않는다. 의료진이 첫 질문을 쓴다.

## 경로

| 메서드 | 경로 | 출처 |
|---|---|---|
| GET | /api/workspace | 질의 역할(DOCTOR/RESEARCHER) |
| GET | /api/protection-policy | `MedicalDefender` g·s, arm, P_ref |
| GET | /api/patient-context | 질의 환자 바인딩 (나이대·성별·대표 진단·관련 항목). 환자 id 없음 |
| GET | /api/cases?patientContextId= | 검색 순위·유사도 점수만. 사례 문서 내용(진단 등)은 싣지 않음 |
| GET | /api/cases/{id}/session | 이 탭에서 보낸 질문과 공개된 답변 |
| POST | /api/cases/{id}/messages | 위 흐름 |
| POST | /api/cases/{id}/preflight | **미지원** (`supported: false`). 연구 모듈에 질문만으로 k를 미리 계산하는 기능이 없음 |
| GET | /api/risk-states | 사례별 kcalc k (공개가 없으면 P_ref) |
| GET | /api/cases/{id}/disclosures | 사례별 Defender 판정 이력 |
| GET | /api/cases/{id}/policy-decision | 누적 공개 QI(State 노드) · 일반화 · 비공개 |
| POST | /api/session/reset | 빈 State로 새 대화 |
| GET | /api/health | arm · llm · 역할별 호출 수 |

오류: 404 없는 사례 · 409 세션 불일치 · 422 빈 질문 · 502 LLM 호출 실패(State 바뀌지 않음). 본문에 의료 데이터 없음.

## 사례 구분

대화 이력은 연구 하네스처럼 ArmRun 하나(단일 대화)다. 화면 탭 `case-N` = 대상 AI 표기 `사례N`.
State는 연구 모듈이 case_ref별로 따로 쌓으므로 사례끼리 섞이지 않는다. 사례 1 탭 질문의 답에 사례 2가 나오면 그 공개는 사례 2 State로 가고,
응답의 `relatedRiskStates`로 화면의 사례 2 위험 상태가 갱신된다.

## 위험 표시 구간

Defender 기준값에서만 나온다 (새 기준 없음): k = 0 ZERO_MATCH · 1 ≤ k ≤ s 위험 · s < k ≤ g 추가 공개 제한 · k > g 기준 초과.
`disclosureAllowed=false`·`restrict`는 C1에서만 (C0·C1S는 누적 State로 막지 않으므로).

## 테스트

```bash
python -m pytest tests/api_server -q          # 가짜 LLM, 약 30초
```
