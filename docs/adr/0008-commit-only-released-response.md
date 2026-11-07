---
id: ADR-0008
title: 실제로 공개한 응답의 단서만 State에 반영한다
status: accepted
date: 2026-10-05
deciders: [양승준, 이유진]
sprint: S3
area: risk
jira: [ZP-21]
tags: [privacy-state, defender, information-boundary]
supersedes: []
superseded_by: []
sources: [orchestrator/, docs/research_harness.md, ext:개발의사결정_요약보고서_v1.0#Stage11]
---
# ADR-0008. 실제로 공개한 응답의 단서만 State에 반영한다

## 배경

전체 루프를 처음 연결했을 때(ZP-17), Defender가 고치기 전 원 응답에서 뽑은 단서까지 Privacy State에 들어갔다. 공격자가 보지 못한 정보로 k가 줄어들어, 이후 턴의 판정이 실제보다 위험하게 나왔다.

## 결정

- 공개된 응답(Released Response)에서 다시 추출한 단서만 State에 반영한다.
- 원 응답과 그 단서는 평가 기록(trace)에만 남긴다.
- Fuzzer도 공개된 응답만 본다.
- State ID는 State에 반영된 값으로 만든다.

## 근거

- State는 "공격자가 지금까지 알게 된 것"이어야 한다. 원 응답은 공격자에게 가지 않았다.
- PoC에서 누적 State를 쓰는 방어는 위험 사건 0/20, State 없는 방어는 13/20이었다. 누적 State가 방어의 핵심이라 State에 들어가는 값이 정확해야 한다.

## 검토한 대안

- 원 응답 기준 State 유지: 더 보수적이지만, 보지 않은 정보 때문에 이후 응답을 과하게 막는다.
- 공개 응답 원문만 저장하고 매 턴 전체를 다시 추출: 턴이 길어질수록 추출 비용이 늘어난다.

## 결과와 영향

- 재작성 뒤 남은 단서 검사를 붙였다. 지운 값의 근거 문구가 글자 그대로 남아 있으면 다시 고친다.
- State ID 계산 방식이 바뀌어, 이전 실행의 `state_id`와 값이 다르다.
