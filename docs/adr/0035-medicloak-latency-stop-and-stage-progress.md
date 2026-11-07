---
id: ADR-0035
title: 답을 기다리는 시간을 줄이고, 기다리는 동안 멈출 수 있게 하며, 진행은 걸린 초 대신 단계로 보인다
status: accepted
date: 2026-11-07
deciders: [양승준]
sprint: S5
area: system
jira: []
tags: [medicloak, latency, llm, extraction, ui, stop]
supersedes: []
superseded_by: []
sources: [webdemo/backend/split_extract.py, webdemo/backend/live.py, webdemo/backend/gate.py, webdemo/backend/engine.py, webdemo/backend/app.py, webdemo/backend/autocheck.py, webdemo/backend/clinic.py, medicloak/cli.py, scripts/measure_latency.py, frontend/src/components/common/StageTrack.tsx, frontend/src/components/clinic/ClinicalChat.tsx, frontend/src/components/emr/SimilarCaseBox.tsx, frontend/src/components/chat/ChatInput.tsx, tests/medicloak/test_split_extract.py, tests/medicloak/test_medicloak.py]
---
# ADR-0035. 응답 시간 줄이기 · 질문 멈추기 · 단계로 보이는 진행 표시

## 배경

2026-11-05 실제 LLM 측정(Haiku 4.5, `runs/latency/20261105_213049_real/시간요약.md`)에서 화면 갈래(C1) 질문 한 턴은 평균 19.4초였다. 단계별 평균은 다음과 같다.

| 단계 | 평균 | 비고 |
| --- | ---: | --- |
| 단서 추출(추출기) | 8.29초 (p95 19.27초) | 출력 평균 1,184토큰 |
| 대상 AI 답 | 3.03초 | 출력 평균 226토큰 |
| 재작성기 | 2.49초 | |
| 고친 답 다시 추출 | 7.22초 | |
| 첫 답(사례 5건) 추출 | 15.21초 | |
| CPU 판정(k 계산 등) | 1.1초 (p95 4.0초) | |

- 시간 대부분은 추출기다. 추출기는 답에 나온 단서를 JSON으로 하나씩 길게 쓰므로, 걸리는 시간이 출력 길이를 따라간다. 사례가 많은 첫 답이 가장 느리다.
- 프로파일링에서 진료 지원 AI 열기의 CPU 시간 3.57초 가운데 약 2초가 입력 게이팅(ADR-0032)이었다. 환자마다 사건을 다시 훑어 노드가 있는지 보았다.
- `GroupRepairKC.k`는 이미 같은 계산을 기억해 두고 있었다 (`_kcache`). 추출기 `max_tokens`는 8,192라 출력이 잘려 다시 부르는 일은 없었다.
- 의료진 체험(2026-11-07): 답이 오기 전에 질문을 멈출 방법이 없었다. 기다리는 동안 '38초 지남'처럼 걸린 초가 보여, 기다림이 더 길게 느껴진다는 의견이 있었다.

## 결정

### 1. 입력 게이팅 색인 (`webdemo/backend/gate.py`)

- 엔진을 켤 때 노드 → 그 노드를 가진 환자 집합(frozenset)을 한 번 만든다 (`event_index`). 사건마다 상위 노드까지 넣는다.
- 환자 단위가 아닌 노드를 볼 때 이 색인을 쓴다. 판정 결과는 그대로다.
- 프로파일링: 열기 CPU 3.57초 → 1.44초, 질문 CPU 0.24초 → 0.03초.

### 2. 단서 추출을 사례마다 나눠 동시에 부르기 (`webdemo/backend/split_extract.py`)

- 답에 '사례N'이 둘 이상 나오면, 같은 추출 지시문 끝에 '이번에는 사례N만'을 붙여 사례마다 따로 부른다. 사례 번호가 없는 문단(지금 환자 소개, 사례 전체를 묶은 문장)이 있으면 그 값만 뽑는 호출을 하나 더 한다.
- 호출마다 답 전체를 그대로 보여 준다. '사례1과 같은 약'처럼 앞 사례를 가리키는 말도 풀 수 있게 하려는 것이다.
- 결과는 `case_ref`로 걸러 사례 순서대로 이어 붙인 JSON 배열 하나로 돌려준다. 연구 모듈(`medical/`)의 추출 · 정규화 · 판정 코드는 바꾸지 않는다.
- 나누지 않는 경우: 사례 번호가 하나 이하, 지시문 끝이 답과 다름, 나눈 호출 하나라도 JSON 배열이 아님(→ 한 번에 다시 부름). `.env`의 `LLM_MIN_INTERVAL_SEC`가 0보다 크면(요청 간격 제한) 나누지 않는다.
- 나눈 호출들은 LLM 자리(`_Slots`) 하나를 같이 쓴다. 의료진 질문이 뒤 작업(비교 갈래 · 미리 준비)을 기다리지 않는 규칙은 그대로다.
- 서버 옵션 `--extract-parallel N`(기본 4, 1이면 끔). 측정 스크립트에도 같은 옵션을 두었다 (`scripts/measure_latency.py --extract-parallel`, 기본 1).
- 자동 레드팀 설정 지문(`autocheck.settings_of`)에 추출 방식을 넣었다. 나누기를 켜고 끄면 설정이 바뀐 것으로 보고 다시 점검한다 (ADR-0028).

### 3. 질문 · 열기 멈추기

- `POST /api/clinic/stop`(질문), `POST /api/emr/launch/stop`(진료 지원 AI 열기). 응답은 `{status: idle | stopping}`이다.
- 멈추기를 누르면 보내 둔 LLM 호출 하나는 끝까지 받고 그 결과는 쓰지 않는다. 다음 호출 전에 턴을 끝낸다 (`QuestionStopped`). 턴을 기록하지 않으므로 대화 · 공개 원장 · 후보 수는 묻기 전 그대로다 (LLM 오류와 같은 처리).
- 질문 요청은 409와 머리글 `X-MediCloak-State: stopped`로 끝난다. 그 사이 답을 다 만들었으면 그 답이 그대로 간다.
- 감사 기록: `clinic_stop` · `emr_launch_stop` (그때까지 보낸 호출 수). 대상 AI에 이미 보낸 질문은 보낸 것이므로 기록에 남긴다.
- 화면: 답을 기다리는 동안 보내기 단추가 '멈추기'로 바뀌고, 기다림 카드와 유사 사례 찾기에도 '멈추기'가 있다. 멈추면 질문은 입력칸으로 돌아간다.

### 4. 진행 표시는 걸린 초 대신 단계로

- 진행 API(`/api/clinic/progress`, `/api/emr/launch/progress`)는 지금 단계 `step`(target · extractor · rewriter · recheck)과 `stopping`을 돌려준다. `elapsed`는 기록용으로 남기고 화면에는 보이지 않는다.
- `StageTrack`: 막대 셋 — ① 답 쓰기(열기는 '사례 찾기') ② 보호 기준 확인 ③ 필요하면 고쳐 쓰기. 끝난 단계는 채우고, 지금 단계는 빛이 지나가는 막대로 보인다. 움직임을 줄인 설정이면 반쯤 채운 막대로 멈춘다.
- 여는 중 단추는 돌아가는 표시 대신 오른쪽으로 흐르는 꺾쇠 셋을 보인다. 열기를 마친 알림에서도 걸린 초를 뺐다.

## 근거

- 추출기 시간은 출력 길이를 따라가므로, 가장 긴 한 번의 출력을 사례 수만큼 나누면 가장 긴 조각의 시간으로 줄어든다. 답의 내용과 판정 규칙은 바꾸지 않는다.
- 멈춘 턴을 기록하지 않으면 '반쯤 판정한 답'이 대화 상태에 섞이지 않는다. 보낸 호출을 취소하지 않는 것은 HTTP를 끊어도 대상 쪽에서 호출이 이미 처리되고, 끊는 시점에 따라 상태가 어긋날 수 있기 때문이다.
- 걸린 초는 기다림을 줄여 주지 않고 재촉하는 느낌만 준다. 지금 무엇을 하는지(쓰기 · 확인 · 고쳐 쓰기)가 의료진이 기다릴지 멈출지 정하는 데 더 쓸모 있다.

## 검토한 대안

- 답을 흘려 보이기(스트리밍): 보호 확인을 마치기 전의 글이 화면에 나간다. 이 프로젝트의 기본 원칙(확인한 글만 내보냄)과 맞지 않는다.
- 추출기 출력을 짧은 JSON으로 바꾸기: 지시문을 바꿔야 하고, 고정한 연구 하네스와 측정 기준이 달라진다. 실제 LLM으로 다시 재야 하므로 이번에는 하지 않았다.
- 더 작은 추출 모델: 추출 정확도(ADR-0018)를 다시 재야 한다.
- 프롬프트 캐시: 추출 지시문 끝에 매번 다른 답이 붙어 얻는 몫이 작다.
- 보낸 HTTP 호출을 끊기: 토큰은 그대로 쓰이고, 호출이 끝났는지 알 수 없어 상태가 어긋날 수 있다.

## 결과와 영향

- 사례가 여럿인 답의 추출은 호출 수가 (사례 수 + 1)까지 늘고, 호출마다 같은 지시문을 보내므로 입력 토큰도 그만큼 는다. 출력 토큰은 거의 같다.
- 사례가 하나인 질문(고른 사례에 묻기)은 나누지 않으므로 빨라지지 않는다. 열기(첫 답)와 '찾은 사례 전체' 질문이 대상이다.
- 테스트: `tests/medicloak/test_split_extract.py` 4건(나누는 조건 · 합친 순서 · 실패하면 한 번에 · 동시 호출과 자리 하나), `test_medicloak.py`에 멈추기 1건(질문 · 열기, 대화 그대로, 감사 기록). 앞단 vitest에 멈춘 질문 지우기 1건.
- 연구 하네스(`medical/`) · 고정본(`medical/bundle/`)은 바꾸지 않았다.

## 남은 일

- 나눠 부르기를 켠 상태로 실제 LLM 시간을 다시 잰다 (`scripts/measure_latency.py --extract-parallel 4`). 이 ADR에는 아직 실제 LLM으로 잰 단축 시간을 적지 않았다.
