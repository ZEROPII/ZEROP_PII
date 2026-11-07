---
id: ADR-0039
title: MediCloak을 창 하나짜리 데스크톱 앱으로도 켠다 (pywebview + 같은 프로세스 서버, 병원 서버 연결, PyInstaller 묶음, 글꼴 · 아이콘 앱 안에)
status: accepted
date: 2026-11-07
deciders: [양승준]
sprint: S5
area: system
jira: []
tags: [medicloak, desktop, packaging, pywebview, pyinstaller, pwa, offline]
supersedes: []
superseded_by: []
sources: [medicloak/desktop.py, medicloak/desktop_start.html, medicloak/paths.py, medicloak/cli.py, medicloak/requirements-desktop.txt, packaging/medicloak.spec, packaging/medicloak_app.py, packaging/icons/medicloak.svg, scripts/build_desktop.py, frontend/public/manifest.webmanifest, frontend/index.html, frontend/src/main.tsx, tests/medicloak/test_desktop.py]
---
# ADR-0039. 데스크톱 앱

## 배경

- 시연 · 심사 때 터미널에서 `init` · `serve --build`를 치고, 브라우저에 주소를 따로 열어야 했다. 처음 쓸 계정 비밀번호는 터미널에만 한 번 보였다.
- 실제 병원에서는 의료진 PC가 병원의 MediCloak 서버에 붙고, 환자 데이터는 PC에 두지 않는다. 지금은 '이 컴퓨터에서 서버 켜기' 말고는 길이 없었다.
- 병원 내부망은 인터넷이 막힌 곳이 많은데, 화면 글꼴을 글꼴 CDN(jsdelivr)에서 받았다. 막히면 글꼴이 바뀌고, 열 때마다 외부로 요청이 나갔다.

## 결정

### 1. `python -m medicloak app` (`medicloak/desktop.py`)

- pywebview 창 하나에 화면을 띄운다. 서버(uvicorn)는 같은 프로세스의 다른 스레드에서 돈다. 포트는 8000이 비어 있으면 8000, 아니면 빈 포트를 고른다.
- 창을 닫으면 서버도 멈춘다. 뒤에서 돌던 일이 5초 안에 끝나지 않으면 기다리지 않고 끝낸다.
- pywebview가 없거나 창을 띄우지 못하면(Linux에 GTK · Qt가 없을 때 등) 기본 브라우저로 연다. `--browser`도 같다. `--no-window`는 서버만 켠다 (점검용).
- `serve`는 그대로다. 서버를 만드는 부분을 `prepare()`로 나눠 둘이 같이 쓴다.

### 2. 시작 화면 (`desktop_start.html`)

- 인터넷 없이 열리게 글꼴 · 그림을 밖에서 받지 않는 한 장짜리 화면이다. 처음 설정 · 준비 중 · 처음 쓸 계정 · 켜지 못함 네 가지를 보인다.
- 처음 설정에서 연결 방식을 고른다. 고른 것은 데이터 폴더의 `desktop.json`에 남고, 메뉴의 '처음 설정 다시 하기'로 지운다.
  - 이 컴퓨터에서 켜기: API 주소 · 모델 · 키를 받아 `.env`에 쓰고(권한 600, 다른 줄은 그대로), `check-llm`과 같은 짧은 요청을 한 번 보내 확인한다. 실패하면 까닭을 보이고 '확인 없이 시작'도 둔다. 저장한 키는 화면에 다시 보이지 않는다.
  - 키 없이 둘러보기: 결정적 응답기(`--llm oracle`)로 켠다.
  - 병원 서버에 연결: 주소의 `/api/health`가 MediCloak이면 그 주소를 창으로 연다. 이 컴퓨터에서는 서버를 켜지 않는다 (`--server`).
- 이 컴퓨터의 `.env`에 연결 정보가 다 있으면 처음 설정 없이 바로 켠다. 명령줄의 `--server` · `--llm`은 저장한 방식보다 앞서고, `--setup`이면 처음 설정부터 다시 연다.
- 준비 중에는 단계만 보인다: 데이터 폴더 확인 · 가상 EMR 넣기(처음 한 번) · 진료 지원 AI 연결 준비 · 위험 계산 엔진 준비 · 화면 열기. 걸린 시간 숫자는 보이지 않는다 (ADR-0035의 단계 표시와 같은 원칙).
- 켜지 못하면 까닭(설정 오류 메시지, 키 값 없음)과 '처음 설정 다시 하기' · '기록 폴더 열기'를 보인다.
- 시작 화면의 단추는 pywebview의 `js_api`로 부른다. pywebview는 창에 열린 모든 페이지에 이 API를 넣으므로, 앱 화면(또는 병원 서버)을 연 뒤에는 받지 않는다. 그 페이지의 스크립트가 `.env`(LLM 주소 · 키)를 고쳐 써서 사례 문서가 다른 곳으로 가게 하지 못한다.

### 3. 처음 쓸 계정 · 기록

- DB를 처음 만들면 처음 쓸 계정 셋을 창에 한 번 보이고, '로그인 화면으로'를 누르면 로그인 화면이 열린다. 같은 내용은 `initial_accounts.txt`(권한 600)에 있다.
- 창 앱은 비밀번호를 기록에 적지 않는다 (`init(show_passwords=False)`). 묶은 앱을 터미널 없이 켜면 화면 출력은 `logs/medicloak-app.log`(권한 600, 5MB를 넘으면 한 번 돌림)에 적는다.

### 4. 데이터 폴더와 잠금 (`medicloak/paths.py`)

- 저장소에서 켜면 지금처럼 `runs/medicloak/`을 쓴다. 묶은 앱은 사용자 앱 데이터 폴더를 쓴다: macOS `~/Library/Application Support/MediCloak`, Windows `%APPDATA%\MediCloak`, Linux `~/.local/share/medicloak`. `MEDICLOAK_HOME`이 있으면 그 폴더다. 앱 안(읽기 전용)에는 쓰지 않는다.
- 같은 데이터 폴더로는 서버를 하나만 켠다 (`medicloak-app.lock`). 두 번째 창은 서버를 새로 켜지 않고, 켜 둔 서버의 주소(`medicloak-app.json`)를 연다.

### 5. 묶은 앱 (`packaging/medicloak.spec` · `scripts/build_desktop.py`)

- PyInstaller로 묶는다: macOS `dist/desktop/MediCloak.app`, Windows `dist/desktop/MediCloak/MediCloak.exe`. 그 운영체제용 앱은 그 운영체제에서 만든다.
- 앱 안에는 코드 · 화면(`frontend/dist`) · 가상 EMR 원본 표 · Seed 표 · 시작 화면만 넣는다. `.env` · `runs/` · 키는 넣지 않는다. 쓰지 않는 큰 꾸러미(matplotlib · 다른 GUI 백엔드 등)는 뺀다.
- 묶은 앱을 명령 없이 켜면 데스크톱 앱이고, 명령을 주면 `python -m medicloak`과 같다 (예: `MediCloak users list`).
- macOS 앱은 창(WKWebView)이 이 컴퓨터의 서버(`http://127.0.0.1`)와 병원 서버를 열 수 있게 ATS 설정(`NSAllowsLocalNetworking` · `NSAllowsArbitraryLoadsInWebContent`)을 넣었다. 코드 서명 · 공증은 하지 않았다. 만든 Mac에서는 바로 열리고, 다른 Mac에 보내면 처음 한 번 Finder에서 오른쪽 클릭 → 열기가 필요하다.
- 아이콘은 화면의 표시(여섯 점)와 같은 그림으로 만들었다 (`packaging/icons/`).

### 6. 웹 화면도 인터넷 없이 (`frontend`)

- 글꼴(Wanted Sans · Geist Mono)을 npm 꾸러미로 앱 안에 넣고, CDN 링크를 지웠다. 화면을 열 때 외부로 나가는 요청이 없다.
- `manifest.webmanifest`와 아이콘을 더했다. https 주소나 이 컴퓨터(`127.0.0.1`)에서 열면 Chrome · Edge의 '앱 설치'로 창 하나짜리 앱처럼 쓸 수 있다 (Chromium 설치 가능 검사에서 오류 없음). 오프라인 캐시(서비스 워커)는 두지 않았다. 답은 서버가 있어야 나온다.

## 근거

- pywebview는 운영체제의 웹뷰(macOS WKWebView · Windows WebView2)를 써서 묶음이 작고, 서버가 Python이라 같은 프로세스에 넣을 수 있다. 창과 서버의 수명이 같아 '창을 닫았는데 서버가 남는' 일이 없다.
- 병원 서버 연결을 같은 앱에 둔 것은 실제 배치(의료진 PC에는 데이터 없음)와 시연(이 컴퓨터에서 켜기)을 앱 하나로 하려는 것이다.
- 처음 쓸 계정을 창에 보이는 것은 터미널 없는 사용자도 로그인할 수 있게 하려는 것이고, 기록에 남기지 않는 것은 기록 파일이 비밀번호 사본이 되지 않게 하려는 것이다.

## 검토한 대안

- Electron · Tauri: Electron은 Chromium과 Node 런타임을 같이 넣어 묶음이 커지고, Tauri는 Rust 빌드 도구가 필요하다. 둘 다 Python 서버를 따로 띄워야 한다.
- 서버를 다른 프로세스로 띄우기: 창과 서버의 수명을 맞추기 어렵고, 묶은 앱에서 Python을 두 번 띄워야 한다.
- 브라우저 앱(PWA)만: 서버를 켜는 일(명령)이 그대로 남는다. 병원 서버에 붙는 경우의 보조 수단으로 같이 두었다.
- 처음 쓸 계정을 파일로만 알리기: 사용자가 숨은 폴더의 파일을 찾아야 한다.

## 결과와 영향

- 시험: `tests/medicloak/test_desktop.py` 17건 (폴더 · 주소 · `.env` 쓰기 · 잠금 · 서버 스레드 · 가짜 창으로 시작 화면 흐름 · 처음 쓸 계정 · 병원 서버 · 두 번째 창 · 켜지 못함 · 기록 · 명령줄 · 묶은 앱 시작점 · 웹 manifest).
- 개발 환경에서 확인한 것:
  - 실제 pywebview(Qt, 화면 없이): 시작 화면 → 처음 쓸 계정 → 로그인 → 내 담당 환자.
  - Linux 묶음(창 없이, 결정적 응답기): 로그인 → 유사 사례 찾기 → 질문 → 답 → 의료 용어 찾기. 외부 요청은 없었다. 묶음 크기는 130MB.
  - macOS · Windows 묶음은 이 환경에서 만들지 못했다. 그 운영체제에서 `python scripts/build_desktop.py`로 만든다.
- 연구 하네스(`medical/`) · 고정본(`medical/bundle/`)은 바꾸지 않았다.

## 남은 일

- 코드 서명 · 공증, 자동 업데이트, Windows 설치 프로그램.
- 병원 서버 연결의 인증서 고정 · 사내 인증서 안내.
