# 공개율 계산기 사용법

파일: `disclosure_rate.py` (표준 라이브러리만 사용, Python 3.9 이상)

## 1. 실행 폴더 하나 계산 (C0·C1 모두)

```bash
python disclosure_rate.py rate runs/medical/<실행 폴더>
```

결과는 `runs/medical/<실행 폴더>/disclosure_out/`에 생깁니다.
- `disclosure_summary.md`: 속성별·턴별 요약표 (먼저 볼 파일)
- `disclosure_by_attr_<갈래>.csv`, `disclosure_by_turn_<갈래>.csv`: 표 원자료

## 2. 기준 쌍 여러 개 비교 (k 민감도)

```bash
python disclosure_rate.py sweep runs/medical/<기본> runs/medical/<g10_s5> runs/medical/<g20_s10> --out sweep_out
```

결과는 `sweep_out/sweep_summary.md`에 기준별 그대로율·일반화율·비공개율·평균 유용성이 한 표로 나옵니다.

## 지표 정의

- **그대로 공개**: 원본 값이 그대로 나간 공개 항목 (action = ALLOW)
- **일반화 공개**: 더 넓은 값으로 바뀌어 나간 항목 (GENERALIZE). 그대로율에 넣지 않고 따로 셉니다.
- **비공개**: 나가지 않은 항목 (SUPPRESS)
- **누적 그대로율**: trial 안에서 턴 t까지 한 번이라도 그대로 나간 항목 ÷ 턴 t까지 나온 전체 항목. 공격자가 이미 받은 값은 버리지 않는다고 봅니다.
- C0(방어 없음)은 방어 결정이 없으므로 원 답변의 단서가 모두 나간 것으로 보고, 그대로율 100%를 기준선으로 씁니다.

## 입력 요구

실행 폴더 안에 `턴기록.jsonl`이 있어야 합니다. 이 파일의 `release_plans`(C1)와 `raw_observations`(C0)를 씁니다.
