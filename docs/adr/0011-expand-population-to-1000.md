---
id: ADR-0011
title: 의료 기준 집단에 합성 424명을 더해 1,000명으로 늘린다
status: superseded
date: 2026-10-12
deciders: [이유진]
sprint: S4
area: data
jira: []
tags: [reference-population, synthetic]
supersedes: []
superseded_by: [ADR-0014]
sources: [docs/개발기록_의료전환.md#3]
---
# ADR-0011. 의료 기준 집단에 합성 424명을 더해 1,000명으로 늘린다

## 배경

risk_defender를 의료 시나리오(Synthea 576명)로 옮긴 뒤, 지역 하나만 물어봐도 k가 낮게 나와 Defender가 지나치게 자주 개입했다.

## 결정

단서별로 값을 뽑아 합성 환자 424명을 만들고, 기준 집단을 1,000명으로 늘린다(risk_defender).

## 근거

기준 집단이 커지면 같은 단서에서도 후보가 늘어, Defender가 과하게 개입하는 일이 줄어든다.

## 검토한 대안

- 576명 유지: 지역 하나만 물어도 k가 낮아 Defender가 과하게 개입한다.

## 결과와 영향

확인해 보니 두 가지가 맞지 않았다.

- 합성 424명은 단서별로 따로 뽑아서 진단 · 나이 · 날짜가 같은 사건으로 묶여 있지 않다. 사건 단위로 세는 k 계산기([ADR-0012](0012-event-level-kcalc.md))로는 계산할 수 없다.
- k가 낮은 원인도 규모보다 지역 분포였다. 576명이 모두 매사추세츠 주 사람이고 도시가 187개라, 도시당 환자가 중앙값 2명이었다.

그래서 의료 본실험에서는 쓰지 않기로 하고 [ADR-0014](0014-grow-population-keeping-event-links.md)로 대체했다.
