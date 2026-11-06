# Dataset — 기준 집단(reference population)의 변화와 현재 데이터셋 선정 과정

이 브랜치는 Zero PII 프로젝트에서 재식별 위험도 `k`를 계산하는 **기준 집단(reference population)** 데이터와, 그 데이터를 만들고 검증한 코드를 한곳에 모은 것이다. 데이터셋 작업은 이유진(dataset·risk_defender 담당)이 진행했다. 아래 내용은 모두 커밋 기록과 당시 README·실험 결과에서 확인한 것이며, 각 단계에 근거 커밋을 적었다.

> **현재 기준 데이터셋**: Synthea 합성 환자 **576명**, 의료 이벤트 **51,759건**  
> `노드_v0.9.csv` + `사건연결표_v0.9.csv` → `user_patient_profiles_576.json` (합성 확장 없음, 사건표 전체 반영)

---

## 1. 한눈에 보는 변화

| 단계 | 날짜 | 기준 집단 | QI | 핵심 결정 | 커밋 |
|---|---|---|---|---|---|
| ① | 2026-09-11 | SynthPAI 300명 | AGE·LOC·OCCP·EDU·REL (5개) | 첫 프로토타입 | `dbb964d` |
| ② | 2026-09-23 | SynthPAI 300 → **300,000명** (합성) | 같음 | 분포 보존 합성으로 확장 | `a65f593` |
| ③ | 2026-09-23 | 300,000명 | 같음 | threshold 실험 → **3** 선정 | `ea6b675` |
| ④ | 2026-10-02 ~ 10-04 | 300,000명 | 같음 | 기준을 일반화 **5** / 억제 **3** 두 단계로 분리 | `6ac21fa`, `ac1407a` |
| ⑤ | 2026-10-11 | **Synthea 576명** (의료) | AGE·SEX·REGION·DX·PROC·PERIOD·MED·PLAN (8개) | 의료 시나리오로 전환, 노드 계층 기반 일반화 | `7bf76c4` |
| ⑥ | 2026-10-12 | 576 → **1,000명** (합성 424명) | 같음 | 분포 보존 합성으로 확장 | `a241eb5` |
| ⑦ | 2026-10-19 | 576명 | — | 기준 집단 사전 점검: 단서별 독립 합성은 사건 단위 k에서 못 씀 | `0b44873` |
| ⑧ | 2026-10-20 | **576명으로 복귀** | 7개 (PERIOD를 이벤트에 내포) | 이벤트 번들 구조 도입 | `c7dc058` |
| ⑨ | 2026-10-21 | **576명 (현재)** | SEX·REGION·DX·PROC·MED·PLAN (나이·날짜는 이벤트 안) | 이벤트 상한 제거, 사건표와 1:1 일치 | `98665c0` |

---

## 2. 단계별 과정

### ① SynthPAI 300명으로 시작 (`dbb964d`, 2026-09-11)

- 출처: [SynthPAI](https://github.com/eth-sri/SynthPAI) `user_bot_profiles_300.json` (LLM 합성 페르소나 300명)
- QI 5개: 나이(10년 구간), 거주지, 직업, 학력, 관계 상태
- `author`는 내부 식별자 `person_id`로만 쓰고, `username`은 직접식별자로 보고 k 계산에서 제외했다.
- 문제: 300명이면 QI를 **하나만** 공개해도 k가 너무 작아 Defender가 거의 항상 발동했다.

### ② 300명 → 300,000명 합성 확장 (`a65f593`, 2026-09-23)

- `scripts/generate_synth_population.py`
- 원본 300명의 필드별 빈도 비율로 **가중치 샘플링**해 299,700명을 추가했다 (`seed=42`, 재현 가능).
- 대상 필드: age, sex, city_country, birth_city_country, education, occupation, income_level, relationship_status
- 결과 파일 `user_bot_profiles_300000.json`은 약 70MB라서 `.gitignore`로 저장소에서 제외했다. 같은 seed로 다시 만들 수 있다.

### ③ threshold 실험 → 3 선정 (`ea6b675`, 2026-09-23)

- `scripts/threshold_experiment.py`: 300,000명 기준, 원본 300명 전원을 타겟으로 threshold 후보 7개를 배치 실험했다 (판정 1,500건씩).
- 같은 커밋에서 QI 이름을 fuzzer 코드와 맞춰 `AGE/LOC/OCCP/EDU/REL`로 통일했다.

| threshold | allow | generalize | suppress | median k | min k | 평균 허용 QI 수 |
|---|---|---|---|---|---|---|
| **3** | 66.9% | 18.2% | **14.9%** | 5 | 4 | **4.26** |
| 5 | 62.7% | 20.8% | 16.5% | 7 | 6 | 4.17 |
| 10 | 56.0% | 23.4% | 20.6% | 14 | 11 | 3.97 |
| 15 | 57.5% | 20.5% | 22.1% | 22 | 16 | 3.90 |
| 20 | 57.7% | 20.1% | 22.1% | 30 | 21 | 3.89 |
| 30 | 60.0% | 16.8% | 23.2% | 45 | 31 | 3.84 |
| 50 | 57.9% | 16.0% | 26.1% | 80 | 51 | 3.69 |

선정 이유: 억제율이 가장 낮고(정보 손실 최소), QI 5개 중 평균 4.26개가 통과하며, 최소 k=4로 항상 k > threshold를 보장했다. threshold를 높일수록 억제가 늘어 유용성이 떨어졌다.

이후 `scripts/poc_defender.py`(`c6d26f7`, 09-25)로 누적 State Defender(C1)와 무상태(Stateless) 대조군을 비교하는 PoC를 돌렸다.

### ④ 기준을 두 단계로 분리 (`6ac21fa` 10-02, `ac1407a` 10-04)

threshold 하나로는 "넓혀서 공개"와 "아예 막기"를 구분할 수 없어서 둘로 나눴다. 이 정책은 현재까지 유지된다.

| projected k | 동작 |
|---|---|
| k > 5 | allow — 그대로 허용 |
| 3 < k ≤ 5 | generalize — 일반화 시도, 실패하면 억제 |
| k ≤ 3 | suppress — 일반화 없이 바로 억제 |

### ⑤ Synthea 576명 의료 시나리오로 전환 (`7bf76c4`, 2026-10-11)

- 기준 집단을 SynthPAI 페르소나에서 **Synthea 합성 환자 576명**으로 바꿨다.
- 전환 이유: <!-- TODO(이유진): SynthPAI → Synthea 의료 시나리오로 바꾼 이유. 커밋·문서에 기록이 없음 -->
- 데이터 파일
  - `노드_v0.9.csv`: 노드 69,034개와 계층 구조 (`node_id, attribute, canonical_label, parent_id, depth, …, k_patients`)
  - `사건연결표_v0.9.csv`: 576명의 의료 이벤트 51,759건 (`event_id, patient_id, event_type, code_node, period_start_node, age_node, sex_node, region_node, …`)
  - `user_patient_profiles_576.json`: 사건연결표를 환자 단위로 묶은 프로필
- 두 CSV의 구축 과정: <!-- TODO(이유진): Synthea 원본 → 노드표·사건연결표 v0.9를 만든 방법과 코드 위치. map_trace에 v0.6이 남아 있음. 이 저장소에는 생성 코드가 없음 -->
- QI가 8개로 바뀌었다: AGE·SEX·REGION·DX·PROC·PERIOD·MED·PLAN
- 일반화를 QI별 하드코딩 규칙에서 **노드 계층(`parent_id`)을 따라 올라가는 방식**으로 바꿨다.
  - 예: `AGE_Y22` → `AGE5_20` → `AGE10_20` → `ANY_AGE`
  - 예: 도시(`REGION_DATASET_LOCALITY_*`) → 주(`REGION_DATASET_STATE_*`) → `ANY_REGION`

### ⑥ 576명 → 1,000명 합성 확장 (`a241eb5`, 2026-10-12)

- ②와 같은 이유로 확장했다. 576명만으로는 REGION 하나만 물어봐도 k가 낮아 Defender가 과하게 발동했다.
- `risk_defender/scripts/generate_synth_population.py` (`seed=42`)
  - AGE·SEX·REGION·DX·PROC·MED: 원본 빈도 비율로 가중치 샘플링
  - PERIOD: 원본 날짜가 거의 모두 고유해서 재샘플링하면 중복 문제가 생겼다. 그래서 원본 범위(1923-02-26 ~ 2026-08-13) 안에서 무작위로 생성했다.
- 결과: `user_patient_profiles_1000.json` (원본 576 + 합성 424)

### ⑦ 기준 집단 사전 점검 (`0b44873`, 2026-10-19)

의료 하네스(`python -m medical`)를 붙이면서 k를 **사건 단위**(kcalc)로 세게 됐다. "60대에 제2형 당뇨병 진단"처럼 같은 사건의 진단·나이·날짜를 **한 사건이 함께** 만족해야 후보로 남는다.

| 예 (576명 전체) | 후보 수 |
|---|---|
| 당뇨병 + 60대, 같은 사건으로 셈 | 4명 |
| 당뇨병 + 60대, 따로 셈 | 25명 |

이 기준에서 ⑥의 확장은 쓸 수 없다. 단서마다 따로 뽑은 합성 환자는 진단·나이·날짜 사이의 **사건 관계가 끊겨 있기** 때문이다 (`docs/medical.md`).

같은 커밋의 사전 점검 결과 (저장소 461명, k_req=5): 도시 하나만으로 54.7%, 정확한 날짜 하나만으로 98.5%, 성별+도시로 70.9%가 1 ≤ k < 5에 들어갔다. 데이터 전체가 한 주(Massachusetts)라 주 단위로 넓혀도 후보가 늘지 않는다.

### ⑧ 576명 복귀 + 이벤트 번들 구조 (`c7dc058`, 2026-10-20)

- 기본 기준 집단을 `user_patient_profiles_576.json`으로 되돌렸다. ⑦에서 확인한 대로 독립 샘플링 합성 데이터는 사건 단위 k와 맞지 않기 때문이다. <!-- TODO(이유진): 복귀 이유가 이것이 맞는지 확인. 커밋 메시지에는 이유가 적혀 있지 않음 -->
- DX·PROC·MED·PLAN을 `{"code", "age", "date"}` **이벤트 번들 리스트**로 저장하도록 바꿨다. 진단·시술·투약·케어플랜마다 그 시점의 나이와 날짜가 함께 묶인다.
- PERIOD를 독립 QI에서 빼고 각 번들의 `"date"`로 넣었다 (QI 8개 → 7개).
- 이때는 환자별로 QI당 1~5개 이벤트만 샘플링했다 (`seed=42`, 평균 약 2.5개).

### ⑨ 이벤트 상한 제거 — 현재 데이터셋 (`98665c0`, 2026-10-21)

- 1~5개 샘플링 상한을 없애고, 사건연결표의 이벤트를 **전부** 프로필에 넣었다 (코드 기준 중복 제거, 날짜순 정렬). 이제 프로필과 사건표가 정확히 일치한다.
- `PROCEDURE_HISTORY`도 PROC에 포함했다 (PROC 2,681 → 2,742건).
- 종료일 `date_end`를 추가했다 (`period_end_node`). 종료일이 없는 이벤트(예: 진행 중 투약)는 키를 생략한다.
- 환자 단위 AGE를 없앴다. 나이는 각 이벤트 번들의 `"age"`에만 있다.

| QI | 총 이벤트 | 환자당 평균 |
|---|---|---|
| DX | 5,032 | 8.7 |
| MED | 3,848 | 6.7 |
| PROC | 2,742 | 4.8 |
| PLAN | 1,738 | 3.0 |

```json
{
  "SEX": "SEX_MALE",
  "REGION": "REGION_DATASET_LOCALITY_...",
  "DX": [
    {"code": "DX_SCT_66383009", "age": "AGE_Y22",
     "date": "PERIOD_CONDITION_START_DATE_DAY_2019-03-24",
     "date_end": "PERIOD_CONDITION_END_DATE_DAY_2019-04-07"}
  ],
  "MED": [
    {"code": "MED_RX_1535362", "age": "AGE_Y22",
     "date": "PERIOD_MEDICATION_START_UTC_DAY_2019-03-24",
     "date_end": "PERIOD_MEDICATION_END_UTC_DAY_2019-09-30"}
  ]
}
```

---

## 3. 현재 데이터셋을 선정한 이유 (요약)

1. **사건 관계 보존**: 의료 시나리오의 k는 사건 단위로 센다. 진단·나이·날짜가 한 사건으로 묶여 있어야 하므로, 단서별 독립 샘플링으로 늘린 합성 데이터(300,000명, 1,000명)는 쓸 수 없다.
2. **사건표와 1:1 일치**: 이벤트 상한을 없애 프로필이 `사건연결표_v0.9.csv`와 정확히 같다. 의료 하네스(kcalc)와 risk_defender가 같은 데이터를 본다.
3. **계층 기반 일반화**: `노드_v0.9.csv`의 계층을 따라 올라가므로 QI마다 규칙을 따로 짤 필요가 없다.

알려진 한계: 576명(저장소 461명)은 도시·날짜 단서 하나만으로 k가 5 아래로 떨어지는 경우가 많다. 기준 집단을 키우려면 **Synthea로 사건연결표 형식의 환자를 추가 생성**해야 한다 (⑦ 사전 점검의 권고).

---

## 4. 파일 목록

### 데이터

| 파일 | 상태 | 설명 |
|---|---|---|
| `risk_defender/data/노드_v0.9.csv` | **현재** | 노드 69,034개와 계층 |
| `risk_defender/data/사건연결표_v0.9.csv` | **현재** | 576명, 이벤트 51,759건 |
| `risk_defender/data/user_patient_profiles_576.json` | **현재 (기본값)** | 사건연결표에서 만든 환자 프로필 |
| `risk_defender/data/user_patient_profiles_1000.json` | 이전 (⑥) | 576 + 합성 424명. 사건 단위 k에 쓸 수 없음 |
| `risk_defender/data/user_bot_profiles_300.json` | 이전 (①) | SynthPAI 원본, 실행 시 자동 다운로드 |
| `user_bot_profiles_300000.json` | 이전 (②) | 약 70MB, 저장소 제외. 스크립트로 재생성 |

### 코드

| 파일 | 단계 | 역할 |
|---|---|---|
| `risk_defender/loader.py` | ⑤·⑧·⑨ | 사건연결표 CSV → 환자 프로필 (`load_population_from_csv`) |
| `scripts/generate_synth_population.py` | ② | SynthPAI 300 → 300,000 합성 |
| `scripts/threshold_experiment.py` | ③ | threshold 후보 7개 배치 실험 |
| `scripts/poc_defender.py` | ③ 이후 | C0 / C1 / Stateless 비교 PoC |
| `risk_defender/scripts/generate_synth_population.py` | ⑥ | Synthea 576 → 1,000 합성 |

---

## 5. 재현 방법

현재 프로필을 사건연결표에서 다시 만들기:

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

이전 단계 데이터 재생성 (모두 `seed=42`):

```bash
python3 scripts/generate_synth_population.py --n 300000 --seed 42                 # ②
python3 scripts/threshold_experiment.py                                           # ③
python3 -m risk_defender.scripts.generate_synth_population --n 1000 --seed 42     # ⑥
```
