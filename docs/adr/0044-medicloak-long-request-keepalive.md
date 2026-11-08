---
id: ADR-0044
title: 오래 걸리는 POST(진료 지원 AI 열기 · 질문 · 사례 보고서)는 20초를 넘기면 공백으로 연결을 살려 두어 데스크톱 앱 창이 60초에 끊지 않게 한다
status: accepted
date: 2026-11-08
deciders: [양승준]
sprint: S5
area: system
jira: []
tags: [medicloak, desktop, latency, http]
supersedes: []
superseded_by: []
sources: [webdemo/backend/keepalive.py, webdemo/backend/app.py, frontend/src/api/types.ts, frontend/src/api/httpApi.ts, frontend/src/api/emrApi.ts, frontend/src/api/reportApi.ts, tests/medicloak/test_keepalive.py, frontend/src/api/streamed.test.ts]
---
# ADR-0044. 오래 걸리는 요청의 연결 유지

## 배경

2026-11-08 실제 LLM(Claude Haiku 4.5)을 연결한 데스크톱 앱(macOS)에서 '유사 사례 찾기'를 누르면 '진료 지원 AI를 열지 못했습니다 · 서버에 연결할 수 없습니다'가 떴다. 앱 기록과 DB를 보면 서버는 첫 답을 끝까지 만들어 대화를 열었다. 앱 창(pywebview → WKWebView)은 응답이 60초 동안 한 바이트도 오지 않으면 요청을 끊는다. 실제 LLM으로 첫 답을 만들거나 답을 고쳐 쓰면 60초를 넘길 수 있다 (답 시간 한도 90초, ADR-0043). 같은 요청이 웹 브라우저에서는 끊기지 않았다. Cloudflare 같은 프록시도 응답 대기 제한(100초)이 있다.

## 결정

- `keepalive.run`: 진료 지원 AI 열기(`POST /api/emr/launch`), 질문(`POST /api/cases/{id}/messages`), 사례 보고서 만들기(`POST /api/clinic/report`)의 처리를 따로 돌린다. 20초 안에 끝나면 전과 같은 응답(상태 코드 · 머리글 그대로)이다.
- 20초를 넘기면 200으로 먼저 열고(`X-MediCloak-Stream: 1`) 10초마다 공백 한 칸을 보낸 뒤 JSON 본문을 보낸다. JSON 앞의 공백은 읽는 쪽이 무시한다.
- 이때 실패(멈춤 409, 대상 AI 오류 502 등)는 상태 코드 대신 본문 `{detail, _status, _state}`로 보낸다. 예상하지 못한 서버 오류는 고정 문장만 보낸다 (내부 오류 문장은 내보내지 않는다).
- 앞단 `streamedFailure`가 그 본문을 알아보고 전과 같은 오류(같은 안내 문장 · 상태 · `X-MediCloak-State` 값)로 바꾼다 (`httpApi` · `emrApi` · `reportApi`).

## 근거

- 창의 제한은 '응답이 오지 않는 시간'이라, 오는 바이트가 있으면 끊지 않는다. 진행 상황은 이미 따로 묻고 있어(`/progress`) 화면 흐름을 바꿀 필요가 없다.
- 20초 안에 끝나는 요청(시연 모드 · 대부분의 질문)은 응답 모양이 전과 같아, 기존 화면 · 시험 · 감사 기록이 그대로다.

## 검토한 대안

- 요청을 '시작'과 '결과 묻기'로 나누기: 더 깔끔하지만 세 흐름(열기 · 질문 · 보고서)의 화면 상태와 멈추기 처리를 모두 바꿔야 한다.
- 창의 요청 제한을 늘리기: pywebview가 WKWebView의 fetch 제한을 바꾸는 방법을 주지 않는다.

## 결과와 영향

- 시험: `test_keepalive.py` 3건(빠른 요청은 전과 같음 · 느린 요청은 공백 뒤 JSON · 느린 실패는 본문으로, 내부 오류 문장은 숨김), 앞단 `streamed.test.ts` 2건. 점검 서버에서 대기 시간을 줄여 열기 · 질문 · 보고서가 모두 공백 응답으로 가게 하고 화면에서 답이 보이는 것을 확인했다.
- 웹 브라우저에서도 같은 방식으로 돈다 (끊기지 않던 곳은 그대로).
- 연구 하네스(`medical/`) · 고정본(`medical/bundle/`)은 바꾸지 않았다.
