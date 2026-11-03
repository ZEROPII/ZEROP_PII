---
id: ADR-0016
title: SynthPAI 경로와 의료 경로를 코드와 실행 명령에서 나눈다
status: accepted
date: 2026-10-23
deciders: [양승준]
sprint: S4
area: system
jira: [ZP-29]
tags: [merge, repository-structure]
supersedes: []
superseded_by: []
sources: [docs/medical.md, docs/개발기록_의료전환.md#4, risk_defender_synthpai/]
---
# ADR-0016. SynthPAI 경로와 의료 경로를 코드와 실행 명령에서 나눈다

## 배경

main의 `risk_defender/`가 의료판으로 바뀌었다. 그런데 SynthPAI 경로(학회 논문 실험)는 이전 SynthPAI판 risk_defender를 쓴다. main(cb5b23b)을 그대로 병합하면 SynthPAI 경로가 import 단계에서 깨진다.

## 결정

- 병합 전 판(ac1407a)을 `risk_defender_synthpai/`에 고정 사본으로 두고, SynthPAI 쪽 import만 그쪽으로 돌린다. `risk_defender/`는 그대로 둔다.
- 의료 경로(`medical/`)는 risk_defender를 import하지 않는다. 판정 정책만 `medical/defense.py`로 옮겨 쓴다.
- 실행 명령을 나눈다: SynthPAI는 `python -m orchestrator`, 의료는 `python -m medical`.
- `evaluation/run_test.py`처럼 테스트가 아닌 파일이 pytest에 잡히지 않게 `pytest.ini`로 `tests/`만 모은다.

## 근거

- 논문 결과를 다시 돌릴 수 있어야 한다.
- 팀원 코드를 고치지 않아야 각자 브랜치 작업과 충돌하지 않는다.

## 검토한 대안

- risk_defender 안에서 플래그로 두 판을 분기: 팀원 코드를 고쳐야 하고 두 판이 같이 바뀔 위험이 있다.
- SynthPAI 경로 폐기: 논문 실험을 재현할 수 없다.

## 결과와 영향

- 병합 뒤에도 두 경로가 함께 돌아간다. 이후 통합 브랜치(11월 3일)에서 pytest 882개가 통과했다.
- 고정 사본은 SynthPAI판 수정이 생기면 따로 관리해야 한다.
