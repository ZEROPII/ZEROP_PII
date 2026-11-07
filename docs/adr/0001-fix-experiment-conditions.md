---
id: ADR-0001
title: 실험 조건을 고정하고 실행마다 설정을 기록한다
status: accepted
date: 2026-09-20
deciders: [이정민, 양승준]
sprint: S2
area: experiment
jira: [ZP-12]
tags: [reproducibility, llm, run-config]
supersedes: []
superseded_by: []
sources: [docs/research_harness.md, medical/config.py, ext:개발의사결정_요약보고서_v1.0#Stage1-2-8]
---
# ADR-0001. 실험 조건을 고정하고 실행마다 설정을 기록한다

## 배경

S2 첫 주 실험에서 같은 질문 순서를 다시 돌려도 Target 답이 매번 달라졌다. 그래서 C0(방어 없음)와 C1(공개 전 방어)의 k 차이가 방어 때문인지, 응답이 우연히 흔들려서인지 가릴 수 없었다. 실행 기록도 모듈마다 열 이름과 형식이 달라 결과를 합칠 때마다 변환 코드를 따로 짰다.

5주 차 스크럼에서 이 문제를 "막힌 것"으로 올렸고, 정규화기 작업(ZP-15)을 S3로 미루고 실험 조건 통일을 먼저 하기로 했다.

## 결정

- Target 응답의 temperature 기본값을 0으로 둔다 (`--temperature`, 음수를 주면 서버 기본값).
- 난수 시드를 고정한다. 의료 실행은 `medical/config.py`의 `seed = 20261009`.
- 실행마다 `run_config.json`에 모델, 프롬프트 버전, temperature, 기준 집단, Seed 파일 해시, 위험 기준, 백엔드, 온톨로지 버전 · 해시를 남긴다.
- 턴 로그는 하나의 형식(턴별 k, 조치, 공개 여부)으로 맞춘다.

## 근거

- 의사결정 요약보고서 Stage 1 · 2 · 8은 모델 버전, 프롬프트 버전, temperature, random seed를 실행 기록에 남기도록 정했다.
- 재실행(Exact Replay)과 다시 계산(recompute)은 원래 실행의 설정을 그대로 가져와야 같은 조건이 된다. 설정이 파일에 없으면 재현할 방법이 없다.

## 검토한 대안

- 서버 기본 temperature를 두고 반복 횟수를 늘려 평균: 토큰 비용이 반복 수만큼 늘어난다. 팀 예산상 대상 수를 늘리는 것보다 호출을 아끼는 쪽을 택했다.
- 기록 형식은 각자 두고 집계 단계에서 변환: 모듈이 바뀔 때마다 변환 코드도 같이 고쳐야 한다.

## 결과와 영향

- 재실행 · 다시 계산 명령이 `run_config.json`에서 백엔드, 위험 기준, 기준 집단, temperature를 읽는다.
- temperature 0에서도 응답이 완전히 같아지지는 않았다(10월 6일 실행에서 같은 질문 12개 중 8개가 다른 답). 이 문제는 [ADR-0009](0009-paired-branches-share-raw-response.md)에서 따로 다뤘다.
