---
id: ADR-0042
title: 유사 사례 보고서는 답과 같은 판정을 거친 공개로 다룬다 (사례마다 주진단 · 그 무렵 치료 · 기록상 경과, 비공개 · 범위 그대로, PDF 내려받기)
status: accepted
date: 2026-11-08
deciders: [양승준]
sprint: S5
area: system
jira: []
tags: [medicloak, report, disclosure, ledger, pdf, desktop]
supersedes: []
superseded_by: []
sources: [webdemo/backend/case_report.py, webdemo/backend/app.py, webdemo/backend/clinic.py, webdemo/backend/engine.py, webdemo/backend/ledger.py, webdemo/backend/fonts/OFL.txt, scripts/build_report_fonts.py, webdemo/requirements.txt, medicloak/desktop.py, packaging/medicloak.spec, frontend/src/pages/CaseReportPage.tsx, frontend/src/api/reportApi.ts, frontend/src/components/clinic/EmrCaseList.tsx, frontend/src/components/layout/nav.ts, frontend/src/lib/auditText.ts, tests/medicloak/test_medicloak.py, tests/medicloak/test_triage_report.py, tests/medicloak/test_desktop.py]
---
# ADR-0042. 유사 사례 보고서

## 배경

2026-11-08 팀 검토에서, 유사 사례 환자들의 진단 · 처방 기록과 그 뒤의 경과를 의사가 보고서 꼴로 열람하고 파일로 받을 수 있으면 좋겠다는 의견이 나왔다. 보고서에도 위반 때문에 가려진 비공개가 그대로 적용되어야 한다는 조건이 붙었다. 웹 화면과 데스크톱 앱 모두에서 되어야 한다.

지금은 사례마다 대화로 하나씩 물어야 그 사례의 처방과 경과를 볼 수 있다. 여러 사례의 값을 모아 보는 곳은 '사례 비교'(이미 답에 나온 값만)뿐이다.

## 결정

### 1. 보고서도 공개다

- 보고서 값은 답과 같은 Defender로 판정한다: 그 대화의 누적 State와 공개 원장(ADR-0032), 보안 담당자 규칙, 조회 목적, 최소 공개 단위, 민감도 등급을 모두 쓴다 (`case_report.build`).
- 내보낸 값(그대로 · 범위)은 그 사례의 State에 더하고 공개 원장에 '보고서'(`report`)로 적는다. 그래서 보고서 뒤의 답과 다른 대화 · 다른 의료진의 판정이 이 값까지 합쳐 센다. 같은 보고서를 다시 만들어도 같은 값은 한 번만 더한다.
- 만들기는 POST(`/api/clinic/report`)로만 한다. 열기(GET)는 마지막 보고서를 돌려줄 뿐 새로 판정하지 않는다. 질문에 답하는 중이면 409로 막는다. 지난 대화 · 보호를 거치지 않는 갈래에서는 만들지 않는다.

### 2. 담는 것과 판정 차례

- 사례마다 판정 차례대로: 주진단(지금 환자의 주진단과 같은 진단 또는 그 아래 진단의 첫 기록) → 주진단 시작 3일 전부터 14일 뒤 사이에 시작한 처방 · 시술 · 관리 계획(처방 → 시술 → 관리 계획) → 성별 → 주진단 당시 나이 → 주진단 시작 시기 → 동반 진단(주진단 때 이어지던 것 먼저, 다섯 개까지).
- 함께 내면 후보가 줄어드므로 뒤의 값일수록 넓히거나 가리기 쉽다. 치료 내용을 앞에 두어 보고서의 목적(무슨 치료를 했고 어땠는지)이 먼저 남게 했다.
- 가린 값은 글 없이 '비공개', 넓힌 값은 상위 범주 이름에 '범위'를 붙인다. 까닭(그대로 적으면 해당 과거 환자가 아주 적음 · 조회 목적 · 보안 담당자 규칙 · 공개 단위 · 민감한 정보)도 같이 준다.
- 기록상 경과: 주진단은 종료까지 기간과 같은 진단 기록 수, 처방은 처방 횟수와 처방 기간, 시술은 시행 횟수와 처음부터 마지막까지 기간, 관리 계획은 종료까지 기간이다. 날짜는 쓰지 않고 정해 둔 범위로만 적는다 (`gate.span_phrase` · `textguard.count_bucket`, ADR-0032와 같은 구간). 이름을 가린 항목은 경과도 적지 않는다.
- '효과'라는 말 대신 '기록상 경과'로 적고, 치료 효과를 입증하지 않는다는 문장을 보고서에 늘 넣는다.
- 의료진 화면 계약이라 후보 수 같은 숫자는 넣지 않는다. 보고서 머리의 수는 값 판정 수(그대로 · 범위로 적음 · 비공개)뿐이다.

### 3. 화면 (`CaseReportPage.tsx`, `/case-report`)

- 의료진 메뉴에 '사례 보고서'를 더하고, 비슷한 사례 목록 머리에도 '보고서'를 둔다.
- 처음 들어오면 무엇을 담는지와 '담은 값도 공개로 셉니다'를 보인 뒤 '보고서 만들기'를 누르게 한다. 만든 뒤에는 '다시 만들기'(그때까지의 답까지 합쳐 다시 판정)와 'PDF로 받기'가 있다.
- 사례마다 표(구분 · 이름 · 기록상 경과): 구분은 기록 종류 색 이름표(ADR-0040)다. 비공개는 답과 같은 잠금 표시, 범위는 같은 '범위' 표시이고, 누르면 까닭이 뜬다. 아래에 동반 진단과 한 문장 요약을 둔다.
- 연 환자가 없으면 '내 담당 환자로'를 안내한다. 서버 없이 도는 화면(mock)에서는 서버에서만 만들 수 있다고 적는다.

### 4. PDF (`case_report.pdf`, `GET /api/clinic/report.pdf`)

- 마지막 보고서를 A4 PDF로 만든다 (fpdf2). 화면과 같은 값이고, 비공개는 회색 '비공개' 상자, 범위는 '(범위)'를 붙인다. 머리에 지금 보는 환자(등록번호 · 연령대 / 성별 · 주진단) · 진료 목적 · 기준 진료일 · 만든 시각 · 진료 지원 AI, 그 아래 보호 안내 네 줄, 쪽마다 아래에 만든 시각과 쪽 번호를 둔다.
- 한글 글꼴은 Wanted Sans에서 한글 2,350자 · 기호만 뽑은 판을 앱 안에 둔다 (`webdemo/backend/fonts`, OFL 사본 함께, `scripts/build_report_fonts.py`로 다시 만든다). 인터넷이 없는 내부망 · 데스크톱 앱에서도 만들어진다.
- 응답은 `attachment`와 한글 파일 이름(`MediCloak-유사사례보고서-26-4874-20261108-0242.pdf`)이고 `no-store`다. 화면 링크에도 같은 이름을 `download`로 준다 (창마다 파일 이름을 정하는 때가 달라서).
- 데스크톱 앱은 pywebview의 내려받기를 켠다 (`ALLOW_DOWNLOADS`). 창 안의 'PDF로 받기'가 저장 창을 연다.
- 묶은 앱에는 글꼴 폴더와 fpdf2 · fontTools 글꼴 표 모듈을 넣는다 (`medicloak.spec`). Pillow는 넣지 않는다 (그림을 쓰지 않는다).

### 5. 기록

- 만들기(`clinic_report`: 그대로 · 범위 · 비공개 수)와 PDF 받기(`clinic_report_download`)를 감사 기록에 남긴다. 보안 담당자용 대화 기록(`security_view`)에는 보고서마다 시각 · 만든 사람 · 사례마다 가린 · 넓힌 수를 둔다. DB에 남기는 대화 스냅숏(`snapshot`)에도 마지막 보고서를 같이 넣어, 서버를 다시 켠 뒤에도 기록으로 남는다. 의료진 화면은 지금 대화의 보고서만 연다.

## 근거

- 보고서를 판정 밖에 두면, 대화로는 가려지는 값을 보고서로 모아 볼 수 있어 보호가 무너진다. 답과 같은 판정 · 같은 누적 State를 쓰면 어느 길로 보아도 같은 사례에서 나간 값의 합이 같은 기준 아래에 있다.
- 보고서 값을 State에 더하지 않으면 보고서와 답을 번갈아 보며 값을 모을 수 있다. 더하면 보고서 뒤의 답이 더 가려질 수 있는데, 이 점을 만들기 전과 보고서 안에 적었다.
- 경과를 날짜 대신 범위로 적는 것은 답의 시기 보호(ADR-0032 입력 게이팅의 구간)와 같은 정도를 지키기 위해서다.

## 검토한 대안

- 지금까지 답에 나온 값만 모으기(사례 비교처럼): 새로 판정할 일이 없지만, 묻지 않은 사례의 처방 · 경과는 비어 있어 보고서로 쓸모가 적다.
- 보고서를 열 때마다(GET) 새로 판정: 화면을 다시 열거나 새로 고칠 때마다 공개가 늘어난다. 만들기 단추로만 판정한다.
- 브라우저 인쇄(PDF로 저장): 데스크톱 앱 창에는 인쇄 대화상자가 없거나 다르고, 비공개 표시 모양이 인쇄 설정에 따라 바뀐다. 서버가 같은 PDF를 만든다.

## 결과와 영향

- `webdemo/requirements.txt`에 `fpdf2`를 더했다 (fontTools · Pillow가 같이 깔린다. 묶은 앱은 Pillow 없이 돈다).
- 공개 원장의 종류에 `report`를 더했다 (DB 표는 그대로).
- 시험: `test_medicloak.py`에 보고서 흐름 1건(연 환자 없음 409 · 만들기 전 404 · 판정 계약 · 숫자 없음 · State와 원장 · 다시 만들기 · PDF 머리글 · 감사 기록 · 보안 담당자 계정 거부), `test_triage_report.py`에 판정 차례 · 범위 경과 · 까닭 · 요약 · PDF 4건, `test_desktop.py`에 내려받기 설정 확인을 더했다. 앞단 `auditText.test.ts`에 보고서 기록 글 1건을 더했다.
- 연구 하네스(`medical/`) · 고정본(`medical/bundle/`)은 바꾸지 않았다.
