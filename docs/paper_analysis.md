# 논문용 분석 (python -m analysis)

기록(trace.jsonl)만으로 논문의 표와 그림을 만든다. LLM을 부르지 않는다.

## 0. 사전 분석 계획

`docs/analysis_plan_v1.json`에 주 기준 집단(SynthPAI 300명, 설계서의 P_ref), 평가 기준(k = 5), 주 가설과 검정, 최적 운영점 규칙을
새 실행 전에 고정해 두었다. `python -m analysis`는 이 파일을 기본으로 읽고, 옵션으로 바꾼 설정은 보고서와 manifest에 "계획과 다름"으로 남긴다.
계획을 바꾸려면 새 실행을 보기 전에 v2 파일을 만들고 `--plan`으로 지정한다.

## 1. 지금 있는 기록으로 (토큰 0)

```bash
python -m analysis run_multi10 --targets-file runs/target_selection.json
```

결과: `runs/paper_run_multi10/`
- `paper_report.md` : 표 1~5와 해석 방법, 결과를 쓸 때 함께 적어야 할 가정
- `tables/*.csv`    : 모든 수치 (논문 표를 다시 만들 때 이 파일을 쓴다)
- `figures/fig1~3.(png|pdf)` : 위험 궤적 / 보호–유용성 / 민감도
- `manifest.json`   : git 커밋, 설정, 입력 파일 해시, 기준 집단 지문, 라이브러리 버전 (재현 정보)

빠른 점검은 `--quick` (부트스트랩 500회, 누락 반복 3회).

## 2. 대상을 늘릴 때 (새로 추가되는 대상만 실행)

```bash
# 기존 10명을 그대로 두고 30명이 되도록 새로 뽑는다. 새 대상만 따로 적는다
python -m validation.select_targets --count 30 --include-from runs/target_selection.json \
  --output runs/target_selection_30.json --new-output runs/target_selection_30_new.json

# 새 대상만 실행 (논문 기준 k_req 5 = --threshold 4)
python -m orchestrator --targets-file runs/target_selection_30_new.json \
  --arms C0 C1 C1S --backend ontology --turns 12 --paired --threshold 4 --resume \
  --experiment-id run_multi30_add

# 두 실행을 합쳐 분석
python -m analysis run_multi10 run_multi30_add --targets-file runs/target_selection_30.json
```

대상 1명(12턴, 세 갈래 짝 실행)에 약 7만 토큰이 든다. 20명 추가 ≈ 140만 토큰.

## 3. 반복 실험 (선택)

같은 대상을 질문 경로만 바꿔 한 번 더 돌린다. 분석은 대상 단위로 묶어 부트스트랩하므로 반복을 독립 표본으로 부풀리지 않는다.

```bash
python -m orchestrator --targets-file runs/target_selection.json --arms C0 C1 C1S --backend ontology \
  --turns 12 --paired --threshold 4 --rng-seed 43 --resume --experiment-id run_multi10_s43
python -m analysis run_multi10 run_multi30_add run_multi10_s43 --targets-file runs/target_selection_30.json
```

## 4. 왜 다시 돌리지 않아도 되는가

짝 실행에서는 모든 갈래가 같은 질문과 같은 원래 답변을 쓴다. 대상 AI의 답변은 방어 조건과 무관하므로, 원래 답변에서 뽑은 관찰만 있으면
k_req, 기준 집단, 일반화 한도, 추출 누락 같은 조건을 바꿔 다시 판정할 수 있다. 실제 실행과 같은 설정으로 다시 판정한 결과가 실제
실행과 일치하는지는 보고서 1절(재현성 확인)에 나온다. 고친 답변의 문장은 다시 만들지 않으므로, 조건을 바꾼 결과는
"Defender가 허용한 값만 공개된다"는 가정 아래의 값이다.

## 5. 정상 질문 과잉 차단 실험 (약 90만 토큰, 두 개 동시 실행 시 약 15분)

개인정보를 묻지 않는 정상 질문 6개(`data/benign_questions_v1.json`)를 30명에게 같은 순서로 던지고,
누적 방어가 정상 사용에 얼마나 끼어드는지 잰다. 질문은 LLM으로 변형하지 않는다.

```bash
# 터미널 1
caffeinate -i python -m orchestrator --targets-file runs/benign_targets_a.json \
  --questions-file data/benign_questions_v1.json --arms C0 C1 C1S --backend ontology \
  --paired --threshold 4 --resume --experiment-id run_benign_a
# 터미널 2 (동시에)
caffeinate -i python -m orchestrator --targets-file runs/benign_targets_b.json \
  --questions-file data/benign_questions_v1.json --arms C0 C1 C1S --backend ontology \
  --paired --threshold 4 --resume --experiment-id run_benign_b

python -m analysis run_benign_a run_benign_b --title "정상 질문 과잉 차단 실험" \
  --targets-file runs/target_selection_30.json --out runs/paper_benign
```
