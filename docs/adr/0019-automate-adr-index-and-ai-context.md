---
id: ADR-0019
title: ADR 색인과 AI용 문맥 파일을 스크립트와 CI로 자동 생성한다
status: accepted
date: 2026-11-03
deciders: [양승준]
sprint: S5
area: process
jira: [ZP-42]
tags: [adr, automation, github-actions, ai-context]
supersedes: []
superseded_by: []
sources: [scripts/adr.py, .github/workflows/adr.yml, .github/pull_request_template.md, tests/test_adr_tool.py]
---
# ADR-0019. ADR 색인과 AI용 문맥 파일을 스크립트와 CI로 자동 생성한다

## 배경

ADR이 18건으로 늘면서 손으로 관리하는 부분에서 문제가 생겼다.

- 번호를 각자 매기면 겹친다. 이전 프로젝트(003.projectdoc)에서는 ADR 0007이 2건, 0008이 3건 겹쳤고, 목록은 Notion에 따로 있어 실제 파일과 어긋났다.
- 대체 관계를 한쪽 파일에만 적으면, 옛 결정이 아직 유효한 것처럼 보인다.
- AI 도구에 질문하거나 코드 리뷰를 맡길 때마다 팀 결정(예: k는 kcalc 하나로 센다, 실행 중 코드는 정답을 보지 않는다)을 프롬프트로 다시 설명해야 했다. 사람마다 설명하는 범위가 달라, 대체된 기준이 섞여 들어갈 수 있었다.

## 결정

`scripts/adr.py`(표준 라이브러리만 사용)를 둔다.

| 명령 | 하는 일 |
| --- | --- |
| `new` | 다음 번호로 템플릿에서 초안을 만든다 |
| `supersede OLD --by NEW` | 옛 ADR을 "대체됨"으로 바꾸고 양쪽 파일에 대체 관계를 적는다 |
| `lint` | 번호 중복, 필수 필드, 상태 값, 날짜, Jira 키 형식, 필수 절, 대체 관계 양방향, 근거 경로 존재를 검사한다 |
| `index` | `README.md`(색인 · 현황 · 대체 관계 · 스프린트별 그림), `index.json`, `ADR_CONTEXT.md`를 만든다 |

GitHub Actions(`.github/workflows/adr.yml`):

- PR: `lint`를 돌려 형식이 틀리면 병합 전에 막는다.
- `main` · `system_integration`에 병합되면 `index`를 돌려 생성 파일이 바뀌었을 때 봇이 커밋한다.

AI용 파일:

- `ADR_CONTEXT.md`: 유효한 결정은 결정 · 결과 본문을, 대체 · 폐기된 결정은 한 줄만 담는다. AI 대화나 프로젝트 지식에 이 파일 하나를 붙인다.
- `index.json`: ADR마다 필드와 절을 나눈 데이터. 검색(RAG)용으로 ADR 단위로 잘라 넣는다.

PR 템플릿에 "이 PR이 바꾸는 결정과 ADR 번호" 칸을 둔다.

## 근거

- 사람이 읽는 색인과 AI가 읽는 요약을 같은 원본(`docs/adr/*.md`)에서 만들면 둘이 어긋나지 않는다.
- 생성 파일에 실행 시각을 넣지 않아, 같은 ADR이면 항상 같은 결과가 나온다. 바뀐 것이 없으면 봇 커밋도 없다.
- 표준 라이브러리만 쓰면 CI와 팀원 노트북에서 따로 설치할 것이 없다.

## 검토한 대안

- Notion 목록 유지(이전 프로젝트 방식): 코드 리뷰와 분리되고 번호 관리가 안 된다.
- adr-tools(셸 스크립트): 번호 매기기와 대체 표시는 되지만, 한국어 제목 · 앞머리 필드 검사 · AI 문맥 파일 생성이 없다.
- PR마다 작성자가 색인을 직접 갱신: 잊으면 색인이 어긋난다.

## 결과와 영향

- 기존 결정 18건을 이 형식으로 정리했다. 의사결정 요약보고서, `docs/개발기록_의료전환.md`, 스크럼 기록, 실행 결과 기록을 근거로 각 ADR의 `sources`에 남겼다.
- `tests/test_adr_tool.py`가 저장소의 ADR이 lint를 통과하는지와 번호 매기기 · 대체 · 생성 동작을 확인한다.
- 작성자는 ADR 파일만 쓰면 된다. 색인과 AI용 파일은 병합 뒤 CI가 갱신한다.
