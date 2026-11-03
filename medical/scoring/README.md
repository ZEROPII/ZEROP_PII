# medical/scoring — 단서 추출 · 위험 판정 채점과 보류 검증

의료 실행 기록(`runs/medical/<실행>/`)만으로 채점한다. LLM을 부르지 않는다.
저장소 루트에서 실행하고, 고정본 채점은 실행마다 단서 1~2개씩 달라지지 않도록 `PYTHONHASHSEED=0`을 붙인다.

## 무엇을 재나

| 지표 | 정의 | 스크립트 |
|---|---|---|
| 단서 추출 정밀도 | 확정(commit)된 값 중 그 사례 기록의 노드(또는 상위 노드)와 맞는 비율 | `frozen/extract_eval_v4.py` |
| 단서 추출 재현율 | 답에 드러난 단서 중 추출기가 같은 종류로 뽑은 비율 (확정 여부와 상관없이) | `frozen/extract_eval_v4.py` |
| 확정 재현율 | 답에 드러난 단서 중 확정되어 실제로 k 계산에 들어간 비율 | `check_committed_recall.py` |
| 위험 판정 정밀도 · 재현율 · F1 | 가드레일의 위험 판정(release_plans.risky)을 실제로 드러난 단서로 다시 센 k와 대조 | `risk_decision_f1.py` |
| 호출 지연 | 역할별 LLM 호출 지연시간 | `llm_latency.py` |

고정본의 단계 1 재현율은 확정하지 못한 추출도 맞은 것으로 센다. 정규화가 좋아져도 이 숫자는 그대로라서,
`check_committed_recall.py`의 확정 재현율 · F1(확정 기준)을 함께 적는다.

## 파일

| 파일 | 내용 |
|---|---|
| `frozen/extract_eval_v4.py` | 팀 고정본 채점, 단계 0~4. **수정 금지** |
| `frozen/extractor_recall.py` | 팀 고정본 정답 정의 v2.1 (넓혀 말한 나이 · 날짜 · 지역 포함). **수정 금지** |
| `frozen/normalize_bridge_v0.11.2.patch` | 참고용. 같은 규칙이 채점 스크립트와 `medical/normalize_ext.py`에 들어 있다 |
| `frozen/고정본_해시.txt` | 위 세 파일의 sha256. `tests/medical/test_scoring.py`가 확인한다 |
| `frozen/보류검증_요청.md` | 보류 검증 요청서 (규칙 고정 · 새 기록 · 결과 그대로 보고) |
| `보정_내역.md` | holdout_2 전에 넣은 보정(규칙 추출 · 정규화 v2 · 추출 바로잡기 · 나열 귀속)과 효과 |
| `check_committed_recall.py` | 고정본과 같은 단계에 확정 재현율을 더해 출력 |
| `check_same_extractor.py` | 두 실행의 코드 · 프롬프트 해시와 모델 비교 (추출기 고정 확인) |
| `reprocess.py` | 기록을 지금 코드(`--code v2`) 또는 이전 코드(`--code v1`)로 다시 처리. 같은 답으로 코드 차이만 비교 |
| `miss_breakdown.py` | trial별 재현율, 놓친 유형, 출처별 정밀도, 확정하지 못한 이유 |
| `extractor_recall.py` | 정답 정의 v2. `risk_decision_f1.py`가 이 정의를 쓴다 |
| `patients/before_holdout_N.json` | holdout_N 이전에 쓴 질의 환자. 채점 `--exclude`와 실행 `--exclude-patients`에 같이 쓴다 |
| `결과_기록.md` | 지금까지 잰 값 |

## 보류 검증 순서

규칙을 만들 때 본 기록(개발 기록)으로 잰 값은 발표 숫자로 쓰지 않는다. 규칙을 고정한 뒤 처음 보는 질의 환자로 새 기록을 만들어 잰다.

1. **고정 확인:** `python -m pytest tests/medical -q` (고정본 해시 포함)
2. **새 기록:** 이전에 쓴 질의 환자를 빼고 실행한다. 설정은 이전 기록과 같게 둔다.
3. **채점:** 고정본 → 확정 재현율 → 같은 추출기 확인 순서로 돌려 출력을 그대로 남긴다.
4. **보고:** 결과가 나빠도 그대로 보고한다. 이 기록의 오답을 보고 규칙을 고치면 이 기록도 개발 기록이 되고, 다음 holdout으로 다시 잰다.

holdout_3 예시 (`--trials-per-cell 4`로는 24칸이 모두 이미 쓴 환자라 6으로 늘린다. 새 환자 24명, trial 25개):

```bash
caffeinate -i python -m medical run --arms C0 --mode exploration --budget 4 --docs template --trials-per-cell 6 \
  --rule-extract --exclude-patients medical/scoring/patients/before_holdout_3.json --out runs/medical/holdout_3

E=medical/scoring/patients/before_holdout_3.json
PYTHONHASHSEED=0 python medical/scoring/frozen/extract_eval_v4.py runs/medical/holdout_3 medical/scoring/frozen/extractor_recall.py --exclude $E | tee runs/medical/holdout_3/보류검증_결과.txt
PYTHONHASHSEED=0 python medical/scoring/check_committed_recall.py runs/medical/holdout_3 medical/scoring/frozen/extractor_recall.py --exclude $E | tee -a runs/medical/holdout_3/보류검증_결과.txt
python medical/scoring/check_same_extractor.py runs/medical/holdout_2 runs/medical/holdout_3 | tee -a runs/medical/holdout_3/보류검증_결과.txt
PYTHONHASHSEED=0 python medical/scoring/miss_breakdown.py runs/medical/holdout_3 --exclude $E
```

`caffeinate -i`는 맥에서 잠자기를 막는다. 다른 운영체제에서는 빼고 실행한다.

## 같은 기록, 다른 코드 비교

```bash
python medical/scoring/reprocess.py runs/medical/holdout_2 runs/medical/h2_v1 --code v1
PYTHONHASHSEED=0 python medical/scoring/check_committed_recall.py runs/medical/h2_v1 medical/scoring/frozen/extractor_recall.py --exclude medical/scoring/patients/before_holdout_2.json
```

## 주의

- 고정본은 `variants()`가 집합을 돌려줘서 `PYTHONHASHSEED`와 파이썬 버전에 따라 재현율이 단서 1~2개씩 달라질 수 있다.
- `--dry-run` 기록은 가짜 추출기가 사실표를 읽으므로 숫자가 의미 없다 (배선 확인용).
- 맥에서 만든 실행 폴더는 한글 파일 이름이 NFD로 저장될 수 있다. 위 스크립트는 NFC · NFD 둘 다 찾는다 (고정본 제외).
- `runs/`는 커밋하지 않는다. 결과는 `결과_기록.md`에 숫자로 남긴다.
