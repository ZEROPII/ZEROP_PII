# Privacy Risk / Defender Module

이 모듈은 이유진 담당 범위인 Privacy State, 후보군 크기 `k`, 재식별 위험도, projected risk, Defender 일반화/억제 동작을 구현한 코드.

## QI Set

Synthea 합성 환자 기반 의료 시나리오에서 다음 7개 QI를 사용한다. 명칭은 fuzzer 코드와 통일된 영어 대문자 약어를 사용한다.

| 약어 | 의미 | 저장 형태 | 출처 |
|------|------|-----------|------|
| `SEX` | 성별 | 단일 문자열 | `sex_node` |
| `REGION` | 거주/진료 지역 | 단일 문자열 | `region_node` |
| `DX` | 진단명 (SNOMED CT / ICD) | 이벤트 번들 리스트 | `code_node` (CONDITION) |
| `PROC` | 시술/처치 (SNOMED CT) | 이벤트 번들 리스트 | `code_node` (PROCEDURE, PROCEDURE_HISTORY) |
| `MED` | 투약 정보 | 이벤트 번들 리스트 | `code_node` (MEDICATION) |
| `PLAN` | 케어플랜 | 이벤트 번들 리스트 | `code_node` (CAREPLAN) |

`PERIOD`는 독립 QI 필드 없이 각 이벤트 번들의 `"date"` (시작일) / `"date_end"` (종료일) 키로 내포된다.
환자 레벨 `AGE`는 제거됨 — 나이 정보는 각 이벤트 번들의 `"age"` 키로만 존재한다.

### 이벤트 번들 구조

DX/PROC/MED/PLAN은 각 이벤트를 `{"code", "age", "date", "date_end"}` 번들로 저장한다. 종료일(`date_end`)이 없는 이벤트(예: 진행 중 투약)는 해당 키를 생략한다.

```json
{
  "SEX": "SEX_MALE",
  "REGION": "REGION_DATASET_LOCALITY_...",
  "DX": [
    {"code": "DX_SCT_66383009", "age": "AGE_Y22", "date": "PERIOD_CONDITION_START_DATE_DAY_2019-03-24", "date_end": "PERIOD_CONDITION_END_DATE_DAY_2019-04-07"},
    {"code": "DX_ICD_CODE_J329", "age": "AGE_Y25", "date": "PERIOD_CONDITION_START_DATE_DAY_2022-11-07"}
  ],
  "PROC": [
    {"code": "PROC_SCT_1260009003", "age": "AGE_Y22", "date": "PERIOD_PROCEDURE_START_UTC_DAY_2019-04-06", "date_end": "PERIOD_PROCEDURE_END_UTC_DAY_2019-04-06"}
  ],
  "MED": [
    {"code": "MED_RX_1535362", "age": "AGE_Y22", "date": "PERIOD_MEDICATION_START_UTC_DAY_2019-03-24", "date_end": "PERIOD_MEDICATION_END_UTC_DAY_2019-09-30"}
  ]
}
```

### 이벤트 수 분포 (576명 기준)

사건표(사건연결표_v0.9.csv)의 전체 이벤트를 상한 없이 포함한다. 고유 코드 기준 중복 제거 후 날짜순 정렬.

| QI | 총 이벤트 | 환자당 평균 |
|----|----------|------------|
| DX | 5,032 | 8.7 |
| MED | 3,848 | 6.7 |
| PROC | 2,742 | 4.8 |
| PLAN | 1,738 | 3.0 |

PROC는 `PROCEDURE`와 `PROCEDURE_HISTORY` 이벤트를 모두 포함한다.

## 데이터 파일

`risk_defender/data/`에 포함되어 있다. 별도 설정 없이 바로 실행 가능하다.

| 파일 | 설명 |
|------|------|
| `risk_defender/data/노드_v0.9.csv` | 69,034개 노드와 계층 구조 (node_id, parent_id, depth, canonical_label) |
| `risk_defender/data/사건연결표_v0.9.csv` | 576명 환자의 51,759개 의료 이벤트 |
| `risk_defender/data/user_patient_profiles_576.json` | 576명 환자 프로필 **(기본값)** |

`user_patient_profiles_576.json`은 `사건연결표_v0.9.csv`에서 재생성할 수 있다.

```bash
python3 -c "
from risk_defender.loader import load_population_from_csv
import json, pathlib
records = load_population_from_csv(seed=None)  # 상한 없음, 사건표 전체
out = [{'person_id': r.person_id, 'qis': r.qis} for r in records]
pathlib.Path('risk_defender/data/user_patient_profiles_576.json').write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8'
)
"
```

## Risk 정의

```text
K_t = 현재 Privacy State에 저장된 QI 조합과 일치하는 reference population 후보군
k_t = |K_t|
Risk_t = 1 / k_t
RiskGain_t = Risk_after - Risk_before
```

`k_after <= threshold`이면 해당 QI 추가가 위험하다고 판단한다. 후보가 0명인 경우(`k = 0`)도 상태가 모순되었거나 지나치게 구체화된 것으로 보고 위험 transition으로 처리한다.

## Defender 정책

두 개의 threshold를 사용한다: `generalize_threshold=5`, `suppress_threshold=3`

| projected k | 동작 |
|-------------|------|
| k > 5 | **allow** — 그대로 허용 |
| 3 < k ≤ 5 | **generalize** — 일반화 시도, 실패 시 suppress |
| k ≤ 3 | **suppress** — 일반화 없이 바로 억제 |

k ≤ suppress_threshold이면 어떤 일반화도 시도하지 않고 즉시 해당 QI를 제거한다. k가 위험 구간(3 < k ≤ 5)일 때만 일반화를 거친다.

## QI별 일반화 규칙

일반화는 노드 계층(노드_v0.9.csv)을 따라 parent_id 방향으로 올라간다. 번들 이벤트에서는 `"code"` 필드가 일반화 대상이다.

| QI | 일반화 예시 |
|----|------------|
| `AGE` | `AGE_Y22` → `AGE5_20` (20~24세) → `AGE10_20` (20대) → `ANY_AGE` |
| `SEX` | `SEX_MALE` / `SEX_FEMALE` → `ANY_SEX` |
| `REGION` | `REGION_DATASET_LOCALITY_*` (도시) → `REGION_DATASET_STATE_*` (주) → `ANY_REGION` |
| `DX` | `DX_SCT_65363002` → 상위 개념 → `ANY_DX` |
| `PROC` | `PROC_SCT_*` → 상위 개념 → `ANY_PROC` |
| `MED` | `MED_RX_*` → 상위 분류 → `ANY_MED` |
| `PLAN` | `PLAN_SCT_*` → 상위 분류 → `ANY_PLAN` |

## 실행 예시

```bash
# 프로젝트 루트에서
python3 -m risk_defender.demo --generalize-threshold 5 --suppress-threshold 3

# risk_defender 폴더 안에서
python3 demo.py --generalize-threshold 5 --suppress-threshold 3

# 특정 환자 지정 (UUID 또는 1-based 인덱스)
python3 -m risk_defender.demo --target-id ae3336a0-1686-b8a7-bc13-ccc2967a3f73
python3 -m risk_defender.demo --target-id 2

# 데이터 경로 직접 지정
python3 -m risk_defender.demo \
  --profiles /path/to/user_patient_profiles_576.json \
  --node-data /path/to/노드_v0.9.csv
```

실행 결과는 `outputs/demo_single_target.csv`에 저장된다. 각 turn마다 원본 QI를 그대로 넣었을 때의 `k_after_raw`, Defender 적용 후의 `k_after_defense`, 일반화 또는 억제 결과가 기록된다.

## Demo 동작 방식

`demo.py`는 재현 가능한 검증을 위해 QI 입력 순서를 고정해서 실행한다.

```python
DEMO_QI_ORDER = ["AGE", "SEX", "REGION", "DX", "PROC", "MED", "PLAN"]
```

`--target-id`를 지정하지 않으면 population에서 첫 번째 환자를 기본 target으로 사용한다. 대상 환자에 특정 QI(예: PLAN)가 없으면 해당 turn은 건너뛴다.

## 지금까지 한 것

- Privacy State / k / Defender 핵심 모듈 구현 완료
- Synthea 합성 환자 576명을 reference population으로 로딩
- 노드 계층(노드_v0.9.csv)을 활용한 계층적 QI 매칭 및 일반화 구현
- 6개 의료 QI(SEX/REGION/DX/PROC/MED/PLAN)가 누적될 때 k와 risk gain 계산
- threshold 이하 QI는 노드 계층을 따라 일반화하거나 억제
- 이벤트 번들 구조 도입: DX/PROC/MED/PLAN 각 항목에 해당 시점 `age`, `date`, `date_end` 함께 저장
- 환자 레벨 `AGE` 제거 → 나이 정보는 각 이벤트 번들 내 `"age"` 키로만 보유
- 프로필 이벤트 수 상한 제거: 사건표 전체와 1:1 매칭 (DX 8.7개 / MED 6.7개 / PROC 4.8개 / PLAN 3.0개)
- `PROCEDURE_HISTORY` 이벤트를 `PROC`으로 통합 (PROC 총계 2,742개)

## 다음에 할 것



## 핵심 인터페이스

```python
from risk_defender.loader import load_population
from risk_defender.schema import PrivacyState, QIObservation
from risk_defender.risk import evaluate_projected_risk
from risk_defender.defender import defend_candidate_qis

population = load_population()  # 기본값: user_patient_profiles_576.json

state = PrivacyState(target_id="<patient-uuid>", session_id="s1")

# 코드만 전달 → 해당 코드 가진 환자 전원 후보
projected = evaluate_projected_risk(
    population,
    state,
    [QIObservation("DX", {"code": "DX_SCT_65363002"})],
    threshold=5,
)

# 코드 + 나이 같이 전달 → 더 좁은 후보군
projected = evaluate_projected_risk(
    population,
    state,
    [QIObservation("DX", {"code": "DX_SCT_65363002", "age": "AGE_Y22"})],
    threshold=5,
)

decision = defend_candidate_qis(
    population,
    state,
    [QIObservation("REGION", "REGION_DATASET_LOCALITY_E0E1225FF2456D89")],
    generalize_threshold=5,
    suppress_threshold=3,
)
```
