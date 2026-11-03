---
id: ADR-0002
title: 억제 기준을 k ≤ 3으로 둔다
status: superseded
date: 2026-09-23
deciders: [이유진]
sprint: S2
area: risk
jira: [ZP-11]
tags: [defender, threshold]
supersedes: []
superseded_by: [ADR-0007]
sources: [docs/modules.md, scripts/threshold_experiment.py]
---
# ADR-0002. 억제 기준을 k ≤ 3으로 둔다

## 배경

Defender 첫 버전(ZP-2)은 일반화 · 억제를 시작하는 k 기준이 정해지지 않은 상태였다. 기준을 높이면 지워지는 정보가 늘고, 낮추면 후보가 지나치게 좁아진 뒤에야 개입한다. 6주 차 스크럼에서 "억제 기준을 몇 명으로 둘지 근거가 없다"는 문제가 나왔다.

## 결정

기준 집단 300,000명, 대상 300명 전체에 기준 후보 7개(3 · 5 · 10 · 15 · 20 · 30 · 50)를 실험하고 threshold = 3을 택한다.

## 근거

| threshold | 허용 | 일반화 | 억제 | 최소 k | 평균 허용 QI 수 |
| --- | --- | --- | --- | --- | --- |
| 3 | 66.9% | 18.2% | 14.9% | 4 | 4.26 |
| 5 | 62.7% | 20.8% | 16.5% | 6 | 4.17 |
| 10 | 56.0% | 23.4% | 20.6% | 11 | 3.97 |

- 억제 비율이 가장 낮아 정보 손실이 가장 적다.
- 단서 5개 중 평균 4.26개가 통과한다.
- 최소 k가 4로, 항상 k > threshold가 보장된다.

상세 결과는 `risk_defender/outputs/poc_01_threshold_sensitivity_summary.csv`.

## 검토한 대안

- threshold = 5: 억제 16.5%, 최소 k 6. 정보 손실이 조금 더 크다.
- threshold = 10 이상: 억제가 20%를 넘고 허용 QI 수가 줄어 유용성이 떨어진다.

## 결과와 영향

기준 하나로는 "k가 3보다는 크지만 여전히 좁은 응답"을 넓혀서 내보낼지 그대로 둘지 정할 수 없었다. 8주 차에 판정을 세 단계로 나누면서 [ADR-0007](0007-three-level-release-decision.md)로 대체됐다. k ≤ 3이면 바로 억제한다는 부분은 ADR-0007에 그대로 남았다.
