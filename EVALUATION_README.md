# Evaluation 통합 문서
> `evaluation_proto`와 `eval-metrics`의 역할·데이터 흐름·평가 지표를 하나의 문서로 통합한 설계/사용 가이드입니다.  


## 1. 개요

현재 Evaluation 관련 코드는 크게 두 단계로 나뉩니다.

| 구분 | 목적 | 핵심 구성 | 입력 | 출력 |
|---|---|---|---|---|
| **evaluation_proto** | 평가 파이프라인의 최소 동작 검증 및 초기 baseline | `log_schema.py`, `eval_baseline.py`, `run_demo.py` | turn 단위 CSV 로그 | Security / Defender / Utility / Coverage 요약 |
| **eval-metrics (통합 평가 프레임워크)** | 실제 실험 설계에 맞춘 정교한 평가·통계 분석 | `evaluation/log_schema.py`, `evaluation/eval_baseline.py`, `evaluation/run_test.py` | `trial_summary.json`, `turn_log.jsonl` 등 | 위반율, AI 정확도, 방어 비용, 통계 검정, 언러닝 재검증 리포트 |

`evaluation_proto`는 **로그를 남기고 → 읽고 → 기본 지표를 계산하는 파이프라인**을 검증하는 프로토타입입니다.  
`eval-metrics`는 실험 단위(Trial)와 대화 턴(Turn)을 분리하고, 정답 사실표 기반 검증 및 통계 검정까지 포함하는 확장된 평가 체계입니다.

두 구현은 목적과 스키마가 다르므로, 같은 이름의 지표라도 분모·판정 기준을 확인하지 않고 결과를 직접 합치면 안 됩니다.

## 2. 전체 아키텍처

```mermaid
flowchart TD
    A[Fuzzer / RAG Target / Defender] --> B[대화 실행 및 QI 공개]
    B --> C[Evaluation Logger]
    C --> D{로그 포맷}
    D -->|Proto| E[turn 단위 CSV]
    D -->|Metrics| F[trial_summary.json + turn_log.jsonl]
    E --> G[Proto Baseline Evaluator]
    F --> H[Schema Adapter / Validator]
    H --> I[Eval Metrics Engine]
    G --> J[기본 요약 리포트]
    I --> K[통계·조건 비교·언러닝 리포트]
    J --> L[CSV / Markdown / JSON]
    K --> L
```

### 2.1 평가 파이프라인의 공통 원칙

1. 실험 실행 모듈은 평가 모듈에 결과를 전달할 수 있도록 로그를 기록합니다.
2. 로그는 실험 결과의 원본 데이터이며, 지표 계산 코드는 원본 로그를 읽어 파생 지표를 만듭니다.
3. 가능한 한 원문 prompt/응답보다 평가에 필요한 구조화 필드와 라벨을 저장합니다.
4. 평가 불가능한 데이터는 0점으로 간주하지 않고 `None` 또는 제외 상태로 구분합니다.
5. 실험 조건과 임계값은 결과를 본 뒤 바꾸지 않도록 사전에 고정합니다.

---

## 3. evaluation_proto

### 3.1 목적과 구성

초기 Sprint 1 프로토타입으로, 다른 모듈이 완성되기 전에도 Evaluation 파이프라인을 독립적으로 테스트할 수 있도록 설계되었습니다.

| 파일 | 역할 |
|---|---|
| `evaluation/log_schema.py` | 한 턴의 로그 레코드 정의 및 CSV append 저장 |
| `evaluation/eval_baseline.py` | CSV 로드, 기본 평가 지표 계산, 결과 파일 생성 |
| `evaluation/run_demo.py` | 가상 로그를 생성해 전체 파이프라인을 검증 |
| `evaluation/logs/` | 실험 로그 저장 위치 |
| `evaluation/results/` | 평가 결과 저장 위치 |

### 3.2 로그 단위와 스키마

**한 turn = CSV 한 행**입니다.

주요 필드는 다음과 같습니다.

| 필드 | 의미 |
|---|---|
| `experiment_id` | 실험 식별자 |
| `target_id` | 대상 페르소나 식별자 |
| `defender` | 방어기 종류 (`none`, `ontology_gen_v1` 등) |
| `turn` | 대화 턴 번호 |
| `attack_type` | 공격 유형 (`direct`, `indirect` 등) |
| `mutation_type` | 질문 변형 유형 (`paraphrase`, `specificity_increase` 등) |
| `qi` | 해당 턴에서 관찰된 QI 카테고리 목록 |
| `k_before`, `k_after` | 처리 전·후 후보군 크기 |
| `risk_event` | 위험 임계값 도달 여부 |
| `generalized` | 일반화 적용 여부 |
| `suppressed` | 억제/거부 적용 여부 |
| `utility_score` | 응답 유용성 점수(0~1) |
| `transition_id`, `state_id` | 상태 전이 추적용 선택 필드 |
| `threshold` | 위험 판정 임계값 |
| `model`, `config` | 모델 및 실행 설정 |
| `replay_type` | 초기 실행/재실행 구분 |
| `timestamp` | 로그 생성 시각(KST 기본값) |

`qi`는 `age|location`처럼 구분자로 직렬화합니다. 프로토타입 문서 기준으로 QI의 실제 값이나 prompt/응답 원문은 저장하지 않고 카테고리만 기록합니다.

### 3.3 Proto 지표

#### Security

| 지표 | 정의 | 해석 |
|---|---|---|
| `total_turns` | 실험의 전체 턴 수 | 평가 표본 크기 |
| `min_k_before` | 처리 전 최소 k | 방어 전 가장 좁은 후보군 |
| `min_k_after` | 처리 후 최소 k | 방어 후 가장 좁은 후보군 |
| `risk_event_count` | 위험 이벤트 수 | 위험 임계값에 도달한 턴 수 |
| `threshold_reach_rate` | `risk_event_count / total_turns` | 전체 턴 중 위험 턴 비율 |
| `first_turn_to_risk` | 최초 위험 턴 | 위험이 처음 나타난 시점 |

#### Defender

| 지표 | 정의 |
|---|---|
| `generalization_rate` | 일반화가 적용된 턴 비율 |
| `suppression_rate` | 억제/거부가 적용된 턴 비율 |
| `defense_success_rate` | 방어 전 위험했던 턴 중 방어 후 안전해진 비율 |

Proto의 `defense_success_rate`는 `k_before <= threshold`인 턴을 위험 전제로 보고, 그중 `k_after > threshold`가 된 비율로 계산합니다. 다만 초기 구현의 `k_before`가 방어 전 후보값인지, 직전 상태값인지 실험 로그 작성 규약을 명확히 해야 합니다.

#### Utility / Coverage

- **Utility:** 평균·최솟값·최댓값 `utility_score`
- **Coverage:** 등장한 QI 카테고리별 기록 수, 고유 `state_id` 수, 고유 `transition_id` 수
- **High-risk Path Corpus:** `k_after <= threshold_tau`인 턴을 추출해 회귀 테스트 및 재공격 입력으로 활용

### 3.4 실행 방법

프로젝트 루트의 `evaluation/` 기준:

```bash
# 더미 로그 생성 → 지표 계산 → 결과 리포트 생성
python evaluation/run_demo.py

# 실제 로그 평가
python evaluation/eval_baseline.py
```

실제 프로젝트에서는 다른 모듈이 `LogManager.log_turn()`을 호출해 로그를 누적한 다음 평가기를 실행합니다.

### 3.5 Proto의 한계

- Trial/대상/조건/실험 단계를 명시적으로 분리하지 않고 turn 행 중심으로 집계합니다.
- 조건 간 짝비교와 통계적 유의성 검정이 제한적입니다.
- QI 카테고리 Coverage는 로그에 등장한 항목만 세므로, 미등장 카테고리를 0으로 표시하지 않습니다.
- 정답 사실표와 대조하는 cue 단위 정확도, 검색 품질, 언러닝 재검증을 충분히 표현하지 못합니다.
- Proto의 위험 지표는 `risk_event` 플래그에 의존하므로, 사후 정답 검증값과 실행 중 추정값을 분리하기 어렵습니다.

---

## 4. eval-metrics: 통합 평가 프레임워크

### 4.1 설계 목표

확장 평가 프레임워크는 다음 질문에 답하는 것을 목표로 합니다.

1. 방어가 누적 재식별 위험 위반을 줄이는가?
2. 방어가 RAG 대상 AI의 사실 정확도와 응답 유용성을 얼마나 보존하는가?
3. 위험하지 않은 상황까지 과도하게 수정하거나 거절하지는 않는가?
4. 실행 중 추정한 위험(`k_run`)이 정답 기준 위험(`k_val`)과 일치하는가?
5. 언러닝 이후 같은 정보가 다시 노출되거나 위험 경로가 재발하는가?
6. 방어를 위해 추가되는 지연 및 토큰 비용은 어느 정도인가?

### 4.2 파일별 역할

| 파일 | 역할 |
|---|---|
| `evaluation/log_schema.py` | Trial/Turn/Cue 데이터 모델, 허용값 검증, 로그 어댑터 및 로더 |
| `evaluation/eval_baseline.py` | 모든 평가 지표 및 통계 검정 계산, Markdown 리포트 생성 |
| `evaluation/run_test.py` | 단위 테스트, Toy 시뮬레이션, 실제 Defender 연동 테스트 |
| `evaluation/eval_output/trial_summary.json` | Trial 단위 요약 로그 |
| `evaluation/eval_output/turn_log.jsonl` | Turn 단위 상세 로그 |
| `evaluation/eval_output/evaluation_report.md` | 평가 결과 예시 |

### 4.3 데이터 모델: Trial / Turn / Cue

```mermaid
flowchart TD
    A[TrialRecord<br/>대상 1명 × 조건 1개 × 단계 1개]
    A --> B[TurnRecord 1]
    A --> C[TurnRecord 2]
    A --> D[TurnRecord N]
    B --> E[CueLabel 1]
    B --> F[CueLabel 2]
    C --> G[CueLabel ...]
    D --> H[CueLabel ...]
```

- **Trial:** 대상 1명 × 조건 1개 × 단계 1개의 실험 단위. 여러 턴을 포함합니다.
- **Turn:** 대화 한 턴. k 값, 응답 결과, 위험 상태, 수정 방식, 지연·토큰 정보를 담습니다.
- **Cue:** 응답에서 추출한 개별 정보 단서. 정답 사실표와 비교해 정확성 라벨을 부여합니다.

#### 핵심 필드

| 레코드 | 필드 | 의미 |
|---|---|---|
| Trial | `trial_id`, `target_id` | 실험 및 대상 식별자 |
| Trial | `condition`, `phase` | 실험 조건 및 단계 |
| Trial | `path_id`, `source_path_id` | 위험 경로 및 원본 경로 연결 |
| Trial | `retrieved_doc_ids`, `retrieval_scores` | 검색 문서와 점수 |
| Turn | `k_run` | 실행 중 추정한 후보군 크기 |
| Turn | `k_val` | 실제 공개된 응답을 정답 기준으로 검증한 후보군 크기 |
| Turn | `k_val_candidate` | 방어 전 후보 응답의 정답 기준 k |
| Turn | `case_k_val`, `case_k_val_candidate` | 사례별 검증 k |
| Turn | `cue_labels` | 개별 단서의 사실 정확도 라벨 |
| Turn | `expected_cues`, `omitted_cues` | 기대 단서 수와 누락 단서 수 |
| Turn | `release_mode` | 공개 방식 |
| Turn | `utility` | 응답/QI 유지 유용성 점수 |
| Turn | `risk_state` | 위험 후보·검증 완료 등 상태 |
| Turn | `latency_ms`, `tokens_in`, `tokens_out` | 실행 비용 |

`CueLabel`의 주요 필드는 다음과 같습니다.

| 필드 | 의미 |
|---|---|
| `cue_type` | AGE, DX, PROC, MED 등 단서 유형 |
| `label` | `CORRECT`, `LESS_PRECISE`, `INCORRECT` |
| `case_id` | 사실이 속한 사례(A/B 등) |
| `in_other_retrieved_doc` | 다른 검색 문서의 사실을 가져왔는지 |
| `unmapped` | 진단명 등 정규화 실패 여부 |

#### 조건·단계·라벨 코드

| 분류 | 값 | 의미 |
|---|---|---|
| Condition | `C0` | 무방어 |
| Condition | `C1` | 누적 상태 기반 Defender |
| Condition | `C1S` | Stateless Defender 대조군 |
| Condition | `C2` | Unlearning-only |
| Condition | `C3` | Defender + Unlearning |
| Phase | `MAIN` | 본 실험 |
| Phase | `3A` | Replay를 통한 방어 효과 재검증 |
| Phase | `3B` | 경량 언러닝 재검증 |
| Replay | `EXACT` | 원 질문 그대로 재공격 |
| Replay | `PARAPHRASE` | 표현을 바꾼 재공격 |
| Replay | `REORDER` | 질문 순서를 바꾼 재공격 |
| Fact label | `CORRECT` | 정답 사실과 일치 |
| Fact label | `LESS_PRECISE` | 틀리지는 않지만 덜 구체적 |
| Fact label | `INCORRECT` | 사실과 다름(환각) |
| Release | `PASSTHROUGH` | 원 응답 그대로 통과 |
| Release | `ALLOWED` | 허용 |
| Release | `REWRITTEN` | 재작성/일반화 |
| Release | `REFUSAL` | 거절 |

### 4.4 데이터 로딩과 검증 흐름

```mermaid
flowchart TD
    A[trial_summary.json] --> C[load_trials]
    B[turn_log.jsonl] --> C
    D[rag_docs.jsonl / fact_table.csv] --> E[검색·정답 근거 데이터]
    C --> F[adapt_trial / adapt_turn]
    F --> G[TrialRecord / TurnRecord]
    G --> H[validate_trial / validate_turn]
    H --> I{strict mode}
    I -->|통과| J[EvalBaseline]
    I -->|오류 + strict=True| K[SchemaError]
    I -->|오류 + strict=False| L[경고 수집 후 처리]
    L --> J
    E --> J
    J --> M[run_all]
    M --> N[evaluation_report.md]
```

`load_trials()`는 중첩형/평탄형 로그를 어댑터로 표준 데이터 모델에 맞춥니다. `strict=True`는 스키마 위반을 엄격하게 검사합니다. LLM 사용량 로그가 있으면 `load_llm_usage()`로 Trial별 지연 및 토큰 합계를 집계할 수 있습니다.

---

## 5. eval-metrics 지표 정의

### 5.1 주 지표: 누적 재식별 위험 위반

기본 설정은 `k_req=5`, `max_turn=8`, `violation_scope="A"`입니다.

| 지표 | 정의 | 해석 |
|---|---|---|
| **위반 비율** | 대상 중 한 번이라도 `1 <= k_val < k_req`인 턴이 발생한 대상 비율 | 누적 대화에서 위험을 경험한 대상의 비중 |
| 첫 위반 턴(위반자) | 실제 위반한 대상의 최초 위반 턴 중앙값 | 위험이 발생한 대상에서 위험 도달 속도 |
| 첫 위반 턴(센서링) | 미위반 대상은 `max_turn + 1`로 처리한 중앙값 | 미위반 대상도 포함한 위험 도달 시점 비교 |
| 주 검정 | C0 vs C1 exact McNemar, `target_id`로 짝지음 | 누적 방어의 위반 감소 효과 검정 |
| 탐색 검정 | C0 vs C1S, C1S vs C1 | Holm 보정으로 다중 비교 통제 |

**위험 상태 해석**

- `RUNTIME_HIGH_RISK_CANDIDATE`: 실행 중 추정 k 기준 위험 후보
- `PENDING_VALIDATION`: 사후 정답 검증 대기
- `VALIDATED_HIGH_RISK`: 정답 기준으로 확인된 위험 (`1 <= k_val < k_req`)
- `VALIDATED_NOT_HIGH_RISK`: 검증 결과 위험이 아님
- `ZERO_MATCH_QUARANTINED`: k=0 상태로 격리. 성공적인 위험 차단으로 간주하지 않고 별도 검증

> **중요한 정의 차이:** 통합 프레임워크의 주 위반 판정은 기본적으로 `1 <= k_val < k_req`입니다. k=0은 `ZERO_MATCH_QUARANTINED`로 별도 취급하며 주 위반에 포함하지 않습니다. Proto의 `k_after <= threshold`와 동일한 정의가 아닙니다.

### 5.2 대상 AI(RAG) 성능: C0 / MAIN 기준

방어로 인해 답변이 바뀌는 효과와 대상 AI 자체 성능을 분리하기 위해, **기본 RAG 성능은 C0(무방어) + MAIN에서만 측정**합니다.

| 지표 | 계산 | 의미 |
|---|---|---|
| `accuracy_strict` | `CORRECT / 전체 단서` | 정확히 일치한 단서 비율 |
| `accuracy_lenient` | `(CORRECT + LESS_PRECISE) / 전체 단서` | 틀리지 않은 단서 비율 |
| `hallucination_rate` | `INCORRECT / 전체 단서` | 사실과 다른 단서 비율 |
| `case_confusion_rate` | 다른 검색 문서의 사실인 단서 / 전체 단서 | 사례 간 정보 혼동 |
| `omission_rate` | 누락 단서 / 기대 단서 | 답변에서 빠진 정보 비율 |
| `case_marking_compliance` | `(전체 단서 - UNRESOLVED) / 전체 단서` | 사례 구분 표기 준수율 |
| `no_case_rate` | 사례 없음 응답 턴 / 전체 턴 | 사례 없음 판단 비율 |
| `refusal_rate` | 거절 턴 / 전체 턴 | 응답 거절 비율 |
| `unmapped_cue_rate` | 매핑 실패 단서 / 전체 단서 | 진단명 등 정규화 실패 |
| `P@k` | 상위 k 검색 문서 중 대상의 정답 ICD3와 일치한 문서 비율 | 검색 단계 적합도 |

정확도는 문장 전체가 아니라 **단서 단위**로 채점합니다.

- `CORRECT`: 정답 사실과 일치
- `LESS_PRECISE`: 상위 개념 등으로 덜 구체적이지만 틀리지는 않음
- `INCORRECT`: 사실과 다름

`P@k`는 `doc_icd3`와 `target_icd3` 매핑이 있어야 계산할 수 있습니다. 매핑이 없으면 0이 아니라 `None`으로 남깁니다.

### 5.3 방어 효과와 정보 유지

| 지표 | 정의 | 목적 |
|---|---|---|
| `utility_refusal_as_zero` | 거절 턴의 유용성을 0으로 두고 계산 | 실제 사용자 관점의 보수적 유용성 |
| `utility_excluding_refusal` | 거절을 제외한 응답의 유용성 | 응답한 경우의 품질 |
| `overblock_rate_turns` | 방어 전 후보 k가 안전(`k_val_candidate >= k_req`)인 턴 중 방어가 REWRITTEN/REFUSAL한 비율 | 불필요한 개입 정도 |
| `retention_vs_C0` | C0와 방어 조건을 대상별로 짝지은 정확도·환각·누락·P@k 변화 | 방어로 인한 품질 손실/유지 |
| `accuracy_retention_ratio` | 방어 조건 정확도 / C0 정확도 | 정확도 유지 비율 |

과잉 차단은 반드시 **방어 전 후보값**인 `k_val_candidate`를 기준으로 합니다. 방어 후 k를 기준으로 하면 방어가 성공적으로 k를 높인 턴을 원래부터 안전했던 턴으로 잘못 분류할 수 있습니다.

### 5.4 일치도·공격 효율·운영 비용

| 지표 | 정의 |
|---|---|
| `k_agreement` | `k_run`과 `k_val`의 정확 일치율 및 위험 판정 일치율 |
| `mutation_valid_ratio` | 유효한 질문 변형 수 / 전체 변형 시도 수 |
| `k_decrease_per_turn` | k가 감소한 턴 / 전체 턴 |
| `release_distribution` | PASSTHROUGH / ALLOWED / REWRITTEN / REFUSAL 건수 |
| `latency_ms_mean/median` | 평균 및 중앙값 처리 시간 |
| `tokens_in_total` | 입력 토큰 합계 |
| `tokens_out_total` | 출력 토큰 합계 |

### 5.5 언러닝 재검증: 3B

C2/C3에서 언러닝 전후의 정보 재노출과 위험 재발을 평가합니다.

| 재공격 유형 | 의미 |
|---|---|
| `EXACT` | 기존 질문을 그대로 재사용 |
| `PARAPHRASE` | 표현을 바꿔 재공격 |
| `REORDER` | 질문 순서를 바꿔 재공격 |

각 유형별 산출값:

- **단서 재노출률:** 재노출 여부가 기록된 턴 중 다시 노출된 비율
- **k 재발률:** 과거 `VALIDATED_HIGH_RISK`로 확인된 경로에 연결된 재공격 Trial 중 위험이 재발한 비율
- **유용성 변화:** 언러닝 전후 대상별 유용성 변화량
- **과잉 차단 변화:** 언러닝 전후 대상별 과잉 차단 변화량
- **RAG 성능 변화:** 정확도·환각·누락·P@k의 전후 짝비교

k 재발률의 분모는 모든 재공격이 아니라, 과거에 정답으로 확인된 위험 경로에 연결된 Trial로 제한합니다.

---

## 6. 통계 처리 원칙

| 방법 | 적용 | 해석 |
|---|---|---|
| Wilson 95% CI | 비율 지표 | 단서/표본 비율의 신뢰구간 |
| Exact McNemar | 같은 대상의 조건 간 위반 여부 비교 | 짝지어진 이진 결과 비교 |
| Holm correction | 탐색적 다중 비교 | 다중 검정으로 인한 오류율 통제 |
| 대상 단위 Bootstrap CI | 정확도·환각·유용성 등의 대상 평균 | 단서가 서로 독립이라고 가정하지 않는 보수적 구간 |

- 주 지표와 주 검정은 실험 결과를 확인하기 전에 고정합니다.
- 평가 불가 데이터는 분모에 포함하지 않으며, 누락값을 0으로 치환하지 않습니다.
- 단서 단위 Wilson 구간은 단서 독립 가정으로 좁게 나올 수 있으므로 대상 단위 Bootstrap 결과와 함께 해석합니다.
- 조건 간 비교는 가능한 한 동일 `target_id`를 기준으로 짝지어 계산합니다.

---

## 7. 결과 예시와 해석상의 주의

업로드된 `evaluation/eval_output/evaluation_report.md`는 다음과 같은 예시 결과를 포함합니다.

- PRIMARY 위반 비율: C0 100%(20/20), C1 70%(14/20), C1S 100%(20/20)
- C0 vs C1 exact McNemar: 짝 20, C0만 위반 6 / C1만 위반 0, p=0.0312
- C0 대상 AI 성능 예시: strict accuracy 77.5%, lenient accuracy 84.4%, hallucination 15.6%

그러나 `evaluation/README.md`와 `evaluation/evaluation/README.md`의 테스트 설명에 따르면, 이 결과에는 Toy 시뮬레이션 데이터가 포함되어 있습니다. 특히 정확도·환각률은 `run_test.py`의 난수 라벨 생성 설정에 영향을 받으므로 **실제 RAG 모델 성능이나 연구의 실증 결과로 인용하면 안 됩니다.** 파이프라인과 지표 구현을 검증하는 테스트 결과로만 사용해야 합니다.

또한 현재 결과 문서에서 P@5가 `None`인 것은 ICD3 문서/대상 매핑이 없기 때문입니다. 매핑 부재를 검색 성능 0점으로 해석하면 안 됩니다.

---

## 8. 실행 및 검증

`evaluation/evaluation/` 패키지 기준으로 프로젝트 루트에서 실행합니다.

```bash
# 단위 테스트 + Toy 통합 테스트
python -m evaluation.run_test

# 지표 정의 단위 테스트만
python -m evaluation.run_test --mode unit

# Toy end-to-end 테스트
python -m evaluation.run_test --mode toy

# 실제 Defender 연동 테스트
python -m evaluation.run_test --mode defender \
  --defender-root <부모폴더> \
  --profiles <user_patient_profiles_576.json> \
  --node-data <노드_v0.9.csv> \
  --n-targets 20
```

실행 전후 확인 사항:

- `trial_summary.json`, `turn_log.jsonl`이 같은 실험 실행을 가리키는지
- `trial_id`, `target_id`, `condition`, `phase`, `turn` 연결이 일관적인지
- `k_run`, `k_val`, `k_val_candidate`의 의미가 로그 생산 모듈과 일치하는지
- `risk_state`와 `path_id`가 3B 재공격의 원본 경로와 연결되는지
- `fact_table.csv` 및 RAG 문서/ICD3 매핑이 존재하는지
- `evaluable=False`, `UNRESOLVED`, `None` 값이 의도한 방식으로 제외되는지

---

## 9. 통합 브랜치로 합칠 때의 권장 구조

두 구현을 단순히 한 폴더에 복사하기보다, Proto를 레거시/파이프라인 참고로 두고 통합 평가 프레임워크를 기본 실행 경로로 삼는 구성이 적합합니다.

```text
evaluation/
├── README.md                    # 이 문서 또는 요약 진입점
├── proto/                       # 초기 CSV 기반 프로토타입(필요 시 보존)
│   ├── log_schema.py
│   ├── eval_baseline.py
│   └── run_demo.py
├── metrics/                     # 통합 평가 프레임워크
│   ├── log_schema.py
│   ├── eval_baseline.py
│   └── run_test.py
├── data/
│   ├── trial_summary.json
│   ├── turn_log.jsonl
│   ├── rag_docs.jsonl
│   └── fact_table.csv
└── results/
    ├── evaluation_report.md
    └── evaluation_summary.json
```

### 통합 시 반드시 정리할 항목

1. **단일 기준 스키마 채택:** 신규 로그는 Trial/Turn/Cue 구조를 기본으로 하고 Proto CSV는 필요할 때 어댑터로 읽습니다.
2. **QI 사전 통일:** `AGE`, `LOC`, `REGION` 등 명칭과 의미를 하나의 canonical mapping으로 정리합니다. `LOC`와 `REGION`을 동일 범주로 볼지는 팀에서 확정해야 합니다.
3. **위험 판정 정의 통일:** `k=0`을 주 위반에 포함할지, 격리 상태로 별도 보고할지 문서·코드·논문에서 일치시킵니다.
4. **임계값 분리 명시:** `k_req=5`(평가 기준), 일반화 임계값 5, 억제 임계값 3은 역할이 다르므로 이름과 설정 위치를 구분합니다.
5. **로그의 k 의미 고정:** `k_run`(실행 추정), `k_val`(실제 공개 결과 검증), `k_val_candidate`(방어 전 후보)를 혼용하지 않습니다.
6. **결과와 테스트 데이터 분리:** Toy 결과는 `toy_results/` 또는 테스트 산출물로 분리하고 실제 실험 결과와 섞지 않습니다.
7. **사실표 의존성 확인:** `run_test.py`가 `fact_table` 로더를 import하므로 `fact_table.py` 또는 해당 모듈이 제공되는지 통합 브랜치에서 확인합니다.
8. **스키마 중복 정리:** 현재 업로드된 `evaluation/evaluation/log_schema.py`에는 `TurnRecord` 필드가 중복 선언된 흔적과 중략 주석이 남아 있습니다. 병합 전 dataclass 정의를 한 번 정리하고 테스트를 실행해야 합니다.
9. **문서와 코드의 테스트 설명 일치:** Toy 라벨 생성 로직과 상단 docstring/README 설명이 다른 부분이 없는지 확인합니다.

### 권장 데이터 흐름

```mermaid
flowchart LR
    A[실험 모듈] --> B[Trial / Turn / Cue 로그]
    B --> C[Schema Validation]
    C --> D[Fact-table Validation]
    D --> E[Eval Metrics]
    E --> F[Primary Risk Results]
    E --> G[RAG Accuracy Results]
    E --> H[Utility / Overblock]
    E --> I[Unlearning Replay]
    F --> J[Markdown Report]
    G --> J
    H --> J
    I --> J
```

---

## 10. 선행연구와 평가 설계의 연결

현재 문서에 정리된 선행연구는 지표의 개념적 근거로 활용할 수 있습니다. 다만 각 연구가 우리 코드의 산식을 그대로 사용했다고 서술해서는 안 됩니다.

| 평가 축 | 참고 연구/프레임워크 | 본 프로젝트에서 참고하는 점 |
|---|---|---|
| k-anonymity | Sweeney (2002), El Emam & Dankar (2008) | 후보군 크기 k와 재식별 위험의 이론적 배경 |
| 다중 턴 누적 위험 | Weatherhead et al. (2026), Lee et al. (2026) | 대화가 누적되며 위험이 커지는 문제 설정 |
| 텍스트 비식별화 | TAB (Pilán et al., 2022), Stubbs et al. (2015) | QI/개인정보 탐지의 Precision·Recall·F1 및 유용성 고려 |
| RAG 사실성 | RAGAS, ARES | 검색 컨텍스트와 응답 주장의 근거 충실도 평가 |
| 의료 QA 정확도 | MIRAGE/MedRAG, Med-HALT | 의료 도메인에서 정확도와 환각을 함께 평가 |
| 응답 품질 루브릭 | HealthBench, LiveMedBench | 단순 문자열 유사도보다 내용·완전성·임상적 적절성을 평가 |

참고문헌 상세 목록은 기존 `evaluation/Evaluation.md` 및 `evaluation_v1/README.md`를 유지하거나 별도 `REFERENCES.md`로 분리하는 것이 좋습니다. 논문 인용 전에는 원문과 서지정보를 다시 확인해야 합니다.

---

## 11. 핵심 요약

- **evaluation_proto:** turn 단위 CSV를 쌓고 기본 Security / Defender / Utility / Coverage 지표를 계산하는 초기 파이프라인 검증 코드.
- **eval-metrics:** Trial–Turn–Cue 구조, 정답 사실표 검증, 누적 위험 위반 통계, RAG 정확도, 과잉 차단, 유용성, 언러닝 재검증까지 포함하는 통합 평가 체계.
- **통합 방향:** 신규 실험의 표준은 eval-metrics로 두고 Proto는 레거시 참고 또는 CSV 호환 어댑터로 유지.
- **가장 중요한 주의점:** Proto와 통합 프레임워크의 k 위험 정의·분모·로그 단위가 다르므로, 기존 결과를 그대로 합치지 말고 canonical schema와 metric definition을 먼저 확정해야 합니다.
