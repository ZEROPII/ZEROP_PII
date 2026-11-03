# Privacy Risk Defender & 의료 용어 RAG

담당: 이유진  
브랜치: `risk_defender/terminology_rag`

---

## 전체 아키텍처

```
LLM 대화 (Fuzzer 출력)
        │
        │  QIObservation 목록
        ▼
┌─────────────────────────────────┐
│        Risk Defender            │
│                                 │
│  PrivacyState (누적 QI 관리)    │
│        │                        │
│        ▼                        │
│  calculate_k(population, state) │
│        │                        │
│     k > threshold?              │
│    ┌───┴───┐                    │
│   예      아니오                │
│    │       │                    │
│  방어    allow                  │
│    │                            │
│  k ≤ suppress_threshold?        │
│    ┌───┴───┐                    │
│   예      아니오                │
│    │       │                    │
│ suppress generalize             │
└─────────────────────────────────┘
        │
        │  공개 허용된 QI (DX/MED/PROC 코드)
        ▼
┌─────────────────────────────────┐
│      의료 용어 RAG              │
│                                 │
│  terminology.db (SQLite)        │
│  ┌──────────────────────────┐   │
│  │ node_id | label | 설명   │   │
│  │ 일반화 체인 (parent_id)  │   │
│  └──────────────────────────┘   │
│        │                        │
│  search() / get()               │
│  generalization_chain()         │
└─────────────────────────────────┘
        │
        │  용어 카드 (한국어 설명 + 일반화 단계)
        ▼
   관리자 화면 (Admin Frontend)
```

---

## 모듈 1: Risk Defender

### 역할

LLM 대화에서 준식별자(QI)가 누적될 때 재식별 위험도를 계산하고, 위험하면 일반화 또는 억제로 방어.

### 파일 구조

```
risk_defender/
├── schema.py       ← PrivacyState, QIObservation 데이터 구조
├── loader.py       ← 환자 프로필 로딩, NODE_REGISTRY 구축
├── risk.py         ← k 계산, evaluate_projected_risk
├── defender.py     ← defend_candidate_qis, generalization_chain
├── demo.py         ← 재현 가능한 데모 실행
├── configs/
│   └── qi_schema.json
├── data/
│   ├── 노드_v0.9.csv                  ← 노드 계층 (ontology)
│   ├── 사건연결표_v0.9.csv            ← 원본 이벤트 테이블
│   ├── user_patient_profiles_576.json ← Synthea 기반 576명
│   └── user_patient_profiles_1000.json← 합성 확장 1000명
└── outputs/
```

### 핵심 개념

| 개념 | 설명 |
|------|------|
| **QI** | 준식별자. 단독으론 무해하지만 조합 시 개인 특정 가능 |
| **k** | 현재 QI 조합과 일치하는 population 후보군 수 |
| **Risk** | `1 / k` (k가 작을수록 위험) |
| **generalize_threshold** | k ≤ 이 값이면 일반화 시도 (기본값 5) |
| **suppress_threshold** | k ≤ 이 값이면 즉시 억제 (기본값 3) |

### 사용 QI 7종

```
AGE   - 나이 노드 (연령대 계층)
SEX   - 성별
REGION - 지역 노드
DX    - 진단 코드 (ICD-10 계층)
PROC  - 시술·처치 코드 (SNOMED 계층)
MED   - 약물 코드 (RxNorm/ATC 계층)
PLAN  - 케어플랜 노드
```

DX·PROC·MED·PLAN은 **다중값 QI** — 한 환자가 여러 이벤트를 가지므로  
`{"code": "...", "age": "...", "date": "..."}` 번들 리스트로 누적.

### 방어 흐름

```
새 QI 후보 입력
      │
      ▼
evaluate_projected_risk()
  현재 state + 새 QI → k_after 예측
      │
  k_after > generalize_threshold?
      │
    예 → allow (QI 그대로 허용)
      │
  아니오 → k_after > suppress_threshold?
                │
              예 → generalization_chain() 탐색
                    │
                   안전한 조상 노드 발견?
                    ├─ 예 → generalize (더 추상적인 값으로 대체)
                    └─ 아니오 → suppress
              아니오 → suppress (즉시 억제)
```

### 클래스 / 함수 요약

```
schema.py
  PrivacyState          - 세션별 누적 QI 상태 (qis, conflicts, pending)
  QIObservation         - 단일 QI 관찰값 (qi_type, value, confidence)
  update_state()        - 새 관찰을 state에 반영 (충돌·중복·특이도 처리)

loader.py
  PersonaRecord         - 환자 한 명의 레코드 (person_id, qis)
  load_population()     - JSON → PersonaRecord 리스트
  load_node_registry()  - 노드 CSV → NODE_REGISTRY (계층 탐색에 사용)
  NODE_REGISTRY         - {node_id: {parent_id, depth, label}} 전역 딕셔너리

risk.py
  calculate_k()         - population 필터링 → k, risk 반환
  evaluate_projected_risk() - QI 추가 전/후 k 비교

defender.py
  defend_candidate_qis()    - 메인 방어 함수 → DefenseDecision 반환
  generalization_chain()    - 노드 계층을 따라 조상 목록 반환
  DefenseDecision           - action / safe_qis / generalized_qis / suppressed_qis / log
```

### Population

| 파일 | 규모 | 설명 |
|------|------|------|
| `user_patient_profiles_576.json` | 576명 | Synthea 기반 원본 |
| `user_patient_profiles_1000.json` | 1000명 | 합성 확장 (`generate_synth_population.py`) |

### 실행

```bash
# 기본 데모 (threshold=5)
python3 -m risk_defender.demo --threshold 5

# 특정 환자 지정
python3 -m risk_defender.demo --target-id pers2 --threshold 5
```

---

## 모듈 2: 의료 용어 RAG

### 역할

Defender가 공개 허용한 DX·MED·PROC 코드를 환자·보호자가 이해할 수 있는 **한국어 설명**으로 변환.  
관리자 화면이 용어 카드를 표시할 때 이 모듈을 통해 설명과 일반화 체인을 조회.

### 파일 구조

```
medical/
└── terminology.py      ← TerminologyDB 클래스 (검색·조회·일반화 체인)

scripts/
└── build_terminology_db.py  ← DB 최초 생성 (LLM으로 설명 생성)

api_server/
└── app.py              ← /api/terminology/* 엔드포인트 3개

data/
└── medical/
    └── terminology.db  ← SQLite DB (.gitignore 처리, 스크립트로 재생성)
```

### DB 스키마 (terminology 테이블)

```
terminology
├── node_id          PK  온톨로지 노드 ID
├── attribute            DX / MED / PROC
├── canonical_label      의료 용어 원문
├── plain_explanation    LLM 생성 한국어 설명
├── standard_code        RxNorm / ICD-10 / SNOMED / ATC 코드
├── k_patients           이 값을 가진 환자 수
├── total_patients       전체 환자 수 (분모)
├── parent_id            일반화 체인 부모 노드
├── level                계층 깊이
├── is_sensitive         민감 분류 (0/1, 팀이 직접 지정)
├── review_status        검토대기 / 검토완료
├── reviewer             검토자
├── reviewed_at          검토 날짜
├── llm_model            설명 생성에 쓴 모델
└── created_at
```

등록 용어: **DX 709개 / MED 752개 / PROC 133개 (총 1,594개)**

### 일반화 체인 예시

```
fexofenadine 60mg tablet
        │ parent_id
        ▼
   fexofenadine
        │ parent_id
        ▼
  2세대 항히스타민제
        │ parent_id
        ▼
    항히스타민제 (루트)
```

`generalization_chain(node_id)` → 현재 노드부터 루트까지 단계 목록 반환

### API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/terminology/search?q=심근&limit=20` | FTS 키워드 검색. `attribute` 필터 가능 |
| GET | `/api/terminology/{node_id}` | 단건 조회 + 일반화 체인 포함 |
| GET | `/api/terminology` | 목록 조회 (limit / offset 페이지네이션) |

### DB 생성

```bash
# 처음 생성 (LLM 호출 포함)
python scripts/build_terminology_db.py

# LLM 없이 메타데이터만 먼저 저장
python scripts/build_terminology_db.py --no-llm

# 중단 후 이어서 (설명 없는 노드만 처리)
python scripts/build_terminology_db.py --resume

# 특정 분류만
python scripts/build_terminology_db.py --attributes DX
```

`.env`에 `LLM_API_KEY` / `LLM_API_BASE` / `LLM_MODEL` 필요.

### 준수 규칙

- LLM에는 **용어명과 코드만** 전달 — 환자 ID·날짜·대화 내용 없음
- 설명마다 `llm_model`·`source` 기록, `review_status` 초기값 `검토대기`
- `is_sensitive`는 코드로 자동 판정하지 않음 — 팀이 DB에서 직접 지정

---

## 두 모듈 연결 흐름

```
[Fuzzer / LLM 응답]
        │
        │  QIObservation(qi_type="DX", value={"code":"SCT_22298006"})
        ▼
[Risk Defender]
  update_state() → PrivacyState 갱신
  defend_candidate_qis() 실행
        │
        ├─ action="allow"  → DX 코드 공개
        ├─ action="generalize" → 더 추상적인 코드로 대체 후 공개
        └─ action="suppress"   → 코드 비공개 (용어 RAG 조회 안 함)
        │
        │  공개 허용된 node_id (예: "SCT_22298006")
        ▼
[의료 용어 RAG]
  get("SCT_22298006") → {label, plain_explanation, generalization_chain}
        │
        ▼
[관리자 화면]
  용어 카드 표시: "심근경색 — 심장 근육에 혈액 공급이 막혀..."
```

---

## 노드 계층 (공유 ontology)

두 모듈은 **동일한 노드 계층**을 공유한다.

```
노드_v0.9.csv
  node_id | attribute | canonical_label | parent_id | depth

Risk Defender  → NODE_REGISTRY (loader.py)  → k 계산·일반화 탐색
의료 용어 RAG  → terminology.db (parent_id) → generalization_chain()
```

같은 `node_id`를 기준으로 두 모듈이 일관성을 유지.
