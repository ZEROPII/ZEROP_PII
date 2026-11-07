---
id: ADR-0009
title: 비교 갈래끼리 같은 질문과 같은 원 응답을 쓴다 (--paired)
status: accepted
date: 2026-10-06
deciders: [양승준]
sprint: S3
area: experiment
jira: [ZP-22]
tags: [troubleshooting, reproducibility, paired]
supersedes: []
superseded_by: []
sources: [README.md, orchestrator/shared_raw.py]
---
# ADR-0009. 비교 갈래끼리 같은 질문과 같은 원 응답을 쓴다 (--paired)

## 배경

트러블슈팅 기록이다. 기본 실행에서는 갈래(C0 · C1 · C1S)마다 Fuzzer가 따로 질문을 만들어서, Defender가 개입하지 않은 턴에도 갈래 간 k가 달랐다. 같은 질문을 던지도록 맞춰도 [ADR-0001](0001-fix-experiment-conditions.md)의 temperature 0에서 원 응답이 호출마다 달랐다. 10월 6일 실행에서 같은 질문 12개 중 8개가 다른 답을 받았다.

## 결정

`--paired` 옵션을 둔다.

- 첫 갈래(보통 C0)의 질문 순서를 나머지 갈래에 그대로 던진다.
- 같은 질문의 원 응답과 그 추출 결과를 갈래들이 함께 쓴다. 함께 쓴 응답은 trace에 토큰 0으로 기록한다.
- 그러면 갈래 간 차이는 공개 게이트(Defender 판정 → 재작성 → 재추출)에서만 생긴다.

## 근거

- 방어 효과를 비교하려면 갈래 간 차이가 방어에서만 나와야 한다.
- Target은 대화 기록 없이 질문만 보고 답하므로, 같은 질문에는 같은 원 응답이 맞다.
- 원 응답을 한 번만 받으니 LLM 호출도 줄어든다.

## 검토한 대안

- 반복 횟수를 늘려 평균: 토큰 비용이 반복 수만큼 든다. PoC에서 시드만 바꾼 반복은 공격 경로가 87.4–89.1% 겹쳐 독립 표본으로 보기 어려웠다.
- 응답 캐시를 질문 문자열로만 공유: 갈래마다 질문이 달라지면 쓸 수 없다.

## 결과와 영향

- `--paired`에서는 나머지 갈래의 공격자가 자기 갈래 응답에 반응하지 않는다. "방어된 응답을 보고 질문을 바꾸는 공격자" 결과가 필요하면 `--paired` 없이 돌린다.
- README의 실행 옵션 표에 두 경우를 나눠 적었다.
