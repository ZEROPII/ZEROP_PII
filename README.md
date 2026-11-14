<p align="center">
  <img src="docs/images/banner.png" alt="MediCloak: 과거 사례는 진료에 쓰고, 그 환자는 드러나지 않게" width="100%">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/KISIA_2026-AI_보안_기술개발_개인정보반-10262e?style=flat-square" alt="KISIA 2026 AI 보안 기술개발 개인정보반">
  <img src="https://img.shields.io/badge/한국융합보안학회_2026_추계-우수논문상-b8860b?style=flat-square" alt="한국융합보안학회 2026 추계학술대회 우수논문상">
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.11">
  <img src="https://img.shields.io/badge/FastAPI-서버-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/React-18-0b7a75?style=flat-square&logo=react&logoColor=white" alt="React 18">
  <img src="https://img.shields.io/badge/macOS-데스크톱_앱-555555?style=flat-square&logo=apple&logoColor=white" alt="macOS 데스크톱 앱">
  <img src="https://img.shields.io/badge/HL7_FHIR-R4-0b7a75?style=flat-square" alt="FHIR R4">
  <img src="https://img.shields.io/badge/tests-pytest_955_passed_·_vitest_104-16a374?style=flat-square" alt="pytest 955 passed, vitest 104 passed">
  <a href="docs/adr/README.md"><img src="https://img.shields.io/badge/ADR-44건-5b5bf0?style=flat-square" alt="ADR 44건"></a>
</p>

<p align="center">
  <b>사례 검색 → AI 답 초안 → 단서 추출 → 누적 후보 수 계산 → 넓히거나 가림 → 다시 확인 → 화면</b><br>
  병원 진료 지원 AI가 과거 환자를 드러내지 않도록, 답이 화면에 나가기 직전에 검사하는 개인정보 보호 계층
</p>

<p align="center">
  <a href="#바로-써-보기"><b>바로 써 보기</b></a> ·
  <a href="https://github.com/ZEROPII/ZEROP_PII/releases/latest">데스크톱 앱 내려받기</a> ·
  <a href="https://drive.google.com/file/d/1HUJPo0GUUjoJog1v-2vt1aLyHxIpSjFw/view?usp=sharing">시연 영상</a> ·
  <a href="https://github.com/ZEROPII/ZEROP_PII/tree/dataset">데이터셋</a>
</p>

> 2026 AI 보안 기술개발 교육과정 최종 프로젝트 (KISIA 개인정보반, 2026.8.17 ~ 11.6) · **Team Zero PII**

---

## 만들게 된 계기

병원의 진료 지원 AI를 쓰면 의료진은 "지금 환자와 비슷한 과거 사례"를 대화로 찾아볼 수 있습니다. 답에서 이름과 등록번호를 지워도 질문이 이어지면 진단, 처방 약, 처방 시작일, 나이, 거주 지역 같은 단서가 한 사람에 대해 쌓입니다. 이 프로젝트의 기준 집단(합성 환자 461명)으로 계산해 보면 정확한 날짜 하나만 공개해도 환자의 98.5%가 후보 5명 미만으로 좁혀집니다.

답을 하나씩 따로 검사해서는 이렇게 쌓이는 위험을 막을 수 없습니다. **MediCloak**은 답이 화면에 나가기 전에 대화 전체에 나온 단서를 사례별로 모아, 조건을 모두 만족하는 과거 환자가 몇 명 남는지(k)를 셉니다. 그리고 후보를 5명 아래로 좁히는 값만 의료 온톨로지의 상위 범주로 넓히거나 가리고, 나머지는 그대로 답합니다. 모델 재학습이나 원본 기록 수정 없이, RAG가 답을 내보내는 단계에 추가해 쓰는 방식입니다.

MediCloak은 두 부분으로 되어 있습니다. **Privacy Guardrail**은 위처럼 답을 내보내기 직전에 대화 전체의 후보 수를 세어 필요한 값만 고칩니다. **Privacy Fuzzer**는 출시 전에 의료 기본 질문 140개와 그 변형으로 공격 대화를 만들고, 후보 수가 더 많이 줄어드는 질문을 먼저 골라(k 피드백) 같은 방어를 시험합니다. 위험했던 대화는 저장해 두었다가 모델이나 규칙이 바뀔 때마다 그대로 다시 실행합니다.

<p align="center">
  <img src="docs/images/clinic-flow.gif" alt="의료진이 사례 1의 약과 시작 시기를 묻자 시작 시기만 비공개로 표시되는 장면" width="760">
  <br><sub>▲ 의료진이 사례 1의 약과 시작 시기를 묻자 시작 시기만 '비공개'로 표시되고, '왜 그런가요?'를 누르면 이유가 나옵니다</sub>
</p>

---

## 한눈에 보기

<table>
<tr>
<td width="50%"><a href="docs/images/screen-clinic.png"><img src="docs/images/screen-clinic.png" alt="의료진 유사 사례 조회 화면"></a></td>
<td width="50%"><a href="docs/images/screen-monitor.png"><img src="docs/images/screen-monitor.png" alt="보안 담당자 실시간 관제 화면"></a></td>
</tr>
<tr>
<td><b>의료진 · 유사 사례 조회</b><br>비슷한 과거 사례 5건에 대해 질문합니다. 환자를 알아볼 수 있는 값은 '비공개'나 범위로 표시하고, 표시를 누르면 어느 사례의 무엇을 왜 바꿨는지 보입니다. 후보 수 같은 위험 수치는 보여 주지 않습니다.</td>
<td><b>보안 담당자 · 실시간 관제</b><br>같은 대화를 후보 수와 함께 봅니다. 그대로 공개했다면 후보가 1명으로 좁혀졌을 답을 가려 157명을 유지한 기록과 의료진의 요청이 올라옵니다.</td>
</tr>
<tr>
<td><a href="docs/images/screen-watch.png"><img src="docs/images/screen-watch.png" alt="의료진 대화 위험 분석 화면"></a></td>
<td><a href="docs/images/screen-report.png"><img src="docs/images/screen-report.png" alt="레드팀 점검 리포트 화면"></a></td>
</tr>
<tr>
<td><b>의료진 대화 위험 분석</b><br>단서가 더해질 때마다 후보가 줄어든 과정(461 → 189 → 157명)과 각 답의 판정 근거를 봅니다.</td>
<td><b>레드팀 점검 리포트</b><br>같은 공격 대화를 세 가지 방어 방식(방어 없음, 턴별 방어, 누적 방어)으로 실행해, 후보가 기준 아래로 내려간 대화 수와 답변 유용도를 비교합니다.</td>
</tr>
</table>

<sub>화면은 실제 LLM 대신 시연용 응답기를 연결한 운영 모드에서 캡처했습니다. 공개 전 검사가 잘 보이도록 의료진 · 관제 화면은 입력 게이팅(사례 기록을 AI에 넣기 전에 값을 가리는 단계)을 끈 상태입니다. 입력 게이팅을 켜면 AI에 보내지 않은 값은 답에 'AI에 보내지 않음'으로 보입니다. 리포트 화면의 기준 평가는 10턴까지 집계한 값이라 아래 검증 결과(8턴)와 수치가 조금 다릅니다.</sub>

---

## 바로 써 보기

MediCloak은 **웹**(브라우저 · 모바일)과 **데스크톱 앱** 두 가지로 쓸 수 있습니다. 화면과 보호 기준은 같고, 둘 다 API 키 없이 시연용 응답기로 먼저 둘러볼 수 있습니다.

<p align="center">
  <img src="docs/images/platforms.png" alt="같은 진료 지원 AI 화면을 모바일, 웹 브라우저, 데스크톱 앱에서 연 모습" width="100%">
</p>

| | 웹 (브라우저 · 모바일) | 데스크톱 앱 (macOS) |
| --- | --- | --- |
| 이럴 때 | 저장소를 받아 직접 켜고, 팀원이나 휴대폰에서도 열어 볼 때 | 개발 도구 없이 앱 하나로 켜 볼 때 |
| 필요한 것 | Python 3.10 이상(3.11 · 3.13에서 확인), 화면 빌드용 Node.js 18 이상 | Apple Silicon Mac |
| 받는 곳 | 이 저장소 (`git clone`) | [Releases](https://github.com/ZEROPII/ZEROP_PII/releases/latest)의 `MediCloak-macOS.zip` |
| API 키 없이 | `--llm oracle` | 시작 화면의 '키 없이 둘러보기' |
| 실제 LLM으로 | 저장소 맨 위 `.env` | 시작 화면의 '이 컴퓨터에서 켜기' |

### 웹으로 열기

**1. 준비 (처음 한 번)**

```bash
git clone https://github.com/ZEROPII/ZEROP_PII.git
cd ZEROP_PII
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r webdemo/requirements.txt
```

**2. 키 없이 켜기**

```bash
python -m medicloak serve --llm oracle --build        # 시연용 응답기 (외부로 나가는 요청 없음)
```

- `--build`는 화면을 빌드합니다(npm 필요). 한 번 빌드한 뒤에는 빼도 됩니다.
- 처음 켤 때 DB · 가상 EMR(합성 환자 576명) · 계정 3개를 만들고, 비밀번호를 터미널에 한 번 보여 줍니다. 같은 내용이 `runs/medicloak/initial_accounts.txt`(이 컴퓨터 사용자만 읽을 수 있음)에 남습니다.
- 브라우저에서 <http://127.0.0.1:8000>을 열고 아래 계정으로 로그인합니다.

| 아이디 | 역할 | 열리는 화면 |
| --- | --- | --- |
| `doctor1` · `doctor2` | 의료진 | 내 담당 환자, 진료 지원 AI(유사 사례 조회 · 보고서) |
| `privacy1` | 보안 담당자 | MediCloak 관제, 레드팀 리포트, EMR 접근 관리, 감사 기록 |

비밀번호는 계정마다 따로 만들어집니다. 로그인이 안 되면 `initial_accounts.txt`에서 그 계정의 줄을 확인하거나 `python -m medicloak users passwd doctor2`로 새로 정합니다. 같은 계정을 10분 안에 5번 틀리면 잠시 로그인이 막힙니다.

**3. 실제 LLM으로 켜기**

```bash
cp .env.example .env               # LLM_API_KEY · LLM_API_BASE · LLM_MODEL 입력
python -m medicloak check-llm      # 연결 확인 (키 값은 출력하지 않음)
python -m medicloak serve --build
```

서버 옵션은 [medicloak/README.md](medicloak/README.md#서버-옵션)에 있습니다. 로그인 없이 화면만 보려면 `python -m webdemo --build`를 실행합니다.

**4. 팀원 · 휴대폰에서 열기**

기본 주소(`127.0.0.1`)는 켠 컴퓨터에서만 열립니다. 휴대폰 브라우저로 열면 아래쪽에 탭(내 환자 · 사례 조회 · 사례 보고서 · 조회 기록 · 보호 안내)이 있는 모바일 화면으로 바뀝니다.

**같은 Wi-Fi**에 있으면 `--host 0.0.0.0`으로 켜고, 다른 기기에서 `http://<이 컴퓨터의 IP>:8000`을 엽니다. http라서 같은 네트워크 안에서는 비밀번호가 암호화되지 않고 오가므로 공용 Wi-Fi에서는 쓰지 않습니다.

```bash
python -m medicloak serve --llm oracle --host 0.0.0.0
ipconfig getifaddr en0                              # macOS에서 이 컴퓨터의 IP 확인
```

**다른 곳에 있는 팀원**에게는 서버를 그대로 `127.0.0.1`로 두고, 터널 도구로 https 주소를 만들어 보냅니다. 예를 들어 Cloudflare Quick Tunnel은 다음과 같습니다.

```bash
brew install cloudflared
cloudflared tunnel --url http://127.0.0.1:8000      # https://….trycloudflare.com 주소가 나옴
```

이 주소를 아는 사람은 누구나 로그인 화면까지 들어올 수 있습니다. 처음 비밀번호를 `users passwd`로 바꾸고, 비밀번호는 주소와 다른 곳으로 보냅니다. 실제 LLM으로 켜면 팀원의 질문도 내 API 키로 호출되므로 시연에는 `--llm oracle`을 권합니다. 시연이 끝나면 터널과 서버를 모두 끕니다(Ctrl+C). 주소는 켤 때마다 바뀝니다.

### 데스크톱 앱으로 쓰기

**1. 내려받기**

[Releases](https://github.com/ZEROPII/ZEROP_PII/releases/latest)에서 [`MediCloak-macOS.zip`](https://github.com/ZEROPII/ZEROP_PII/releases/download/v9.0/MediCloak-macOS.zip)을 받아 압축을 풀고, `MediCloak.app`을 응용 프로그램 폴더로 옮깁니다. Apple Silicon Mac용입니다. 글꼴과 아이콘이 앱 안에 있어 인터넷이 없어도 '키 없이 둘러보기'는 그대로 열립니다.

**2. 처음 열기**

서명하지 않은 앱이라 처음 한 번은 macOS가 실행을 막습니다.

- macOS 15 이후: 앱을 열어 경고가 나오면 '완료'를 누르고, 시스템 설정 → 개인정보 보호 및 보안 아래쪽의 '그래도 열기'를 누릅니다.
- macOS 14 이전: Finder에서 앱을 오른쪽 클릭 → 열기를 누릅니다.
- '손상되었기 때문에 열 수 없습니다'가 나오면 터미널에서 `xattr -dr com.apple.quarantine /Applications/MediCloak.app`을 실행한 뒤 다시 엽니다.

**3. 연결 방식 고르기**

<p align="center">
  <img src="docs/images/screen-desktop.png" alt="데스크톱 앱 시작 화면: 이 컴퓨터에서 켜기, 키 없이 둘러보기, 병원 서버에 연결" width="640">
</p>

| 고르는 것 | 하는 일 | 필요한 것 | 이 Mac에 남는 것 |
| --- | --- | --- | --- |
| 이 컴퓨터에서 켜기 | 가상 EMR과 MediCloak 서버를 이 Mac에서 같이 켭니다 | LLM API 주소 · 모델 · 키 | DB, `.env`(권한 600), 기록 |
| 키 없이 둘러보기 | 시연용 응답기로 켭니다. 화면과 보호 흐름은 같고, 답 내용은 실제 AI가 쓴 것이 아닙니다 | 없음 | DB, 기록 |
| 병원 서버에 연결 | 따로 켜 둔 MediCloak 서버를 앱 창으로 엽니다. 위 '팀원 · 휴대폰에서 열기'의 주소도 됩니다(http 주소는 `http://`까지 적음) | 서버 주소 | 고른 연결 방식만 |

고른 방식은 메뉴 MediCloak → 처음 설정 다시 하기로 바꿉니다. 창을 닫으면 서버도 멈춥니다.

**4. 처음 쓸 계정**

DB를 처음 만들 때 계정 3개(`doctor1` · `doctor2` · `privacy1`)와 비밀번호가 창에 한 번 보입니다. 같은 내용이 데이터 폴더의 `initial_accounts.txt`(이 Mac 사용자만 읽을 수 있음)에 있고, 기록 파일에는 비밀번호를 적지 않습니다. 비밀번호를 바꾸려면 터미널에서 다음을 실행합니다.

```bash
/Applications/MediCloak.app/Contents/MacOS/MediCloak users passwd doctor1
```

**5. 데이터 폴더**

DB · `.env` · `initial_accounts.txt` · `logs/medicloak-app.log` · `desktop.json`은 앱 안이 아니라 `~/Library/Application Support/MediCloak`에 생깁니다(메뉴 MediCloak → 데이터 폴더 열기). 앱을 지울 때 이 폴더도 지우면 이 Mac에 남는 것이 없습니다.

**직접 만들기**

```bash
pip install -r medicloak/requirements-desktop.txt   # pywebview · PyInstaller
python -m medicloak app --llm oracle --build        # 묶지 않고 저장소에서 창으로 켜기
python scripts/build_desktop.py --zip               # dist/desktop/MediCloak.app, MediCloak-macOS.zip
```

그 운영체제용 앱은 그 운영체제에서 만듭니다. Windows에서 같은 명령을 실행하면 `MediCloak-Windows.zip`이 만들어지고, 창은 WebView2를 씁니다. 자세한 내용은 [medicloak/README.md](medicloak/README.md#데스크톱-앱)에 있습니다.

---

## 내 데이터가 밖으로 나가지 않게

환자 데이터는 모두 Synthea로 만든 합성 데이터입니다. 그래도 API 키, 계정 비밀번호, 대화 · 감사 기록은 실행하는 사람의 것이므로 켠 컴퓨터에만 두고, 이 저장소와 앱 압축 파일에는 넣지 않습니다.

**어디에 저장되나**

| 파일 | 저장소에서 켤 때 | 데스크톱 앱 | 저장소 · 앱에 들어가나 |
| --- | --- | --- | --- |
| API 키 (`.env`) | 저장소 맨 위 `.env` | 데이터 폴더의 `.env`(권한 600) | 아니요 |
| DB (대화 · 감사 기록 · 계정의 비밀번호 해시) | `runs/medicloak/medicloak.db` | 데이터 폴더의 `medicloak.db` | 아니요 |
| 처음 계정 비밀번호 | `runs/medicloak/initial_accounts.txt`(권한 600) | 데이터 폴더의 같은 파일 | 아니요 |
| 실행 기록 · 실험 결과 | `runs/` | 데이터 폴더의 `logs/` | 아니요 |

- `.gitignore`가 `.env`와 그 변형, `runs/`, DB 파일, 계정 파일, 기록, 키 파일, 가상환경, 편집기 설정을 막습니다. 저장소에 있는 `.env.example` 같은 예시 파일에는 변수 이름만 있습니다.
- 데스크톱 앱 압축 파일에는 코드 · 화면 · 가상 EMR 원본 표 · Seed 표만 들어가고, 위 파일은 앱을 처음 켤 때 그 컴퓨터의 데이터 폴더에 새로 생깁니다(`packaging/medicloak.spec`).
- API 키는 화면, 로그, 감사 기록, 오류 문구에 남기지 않습니다. `check-llm`도 키 값을 출력하지 않습니다.

**밖으로 나가는 것**

- **키 없이 켤 때**(`--llm oracle`, '키 없이 둘러보기'): 외부로 보내는 요청이 없습니다. 화면 글꼴과 아이콘도 앱 안에 있습니다.
- **실제 LLM으로 켤 때**: `.env`에 적은 LLM 주소로만 요청을 보냅니다. 의료진 질문, 검색된 과거 사례의 진료 기록(진단 · 약 · 날짜 · 나이 · 거주 도시 등. 이름과 상세 주소는 없고, 입력 게이팅이 가린 값은 빠짐), 단서 추출과 다시 확인에 쓰는 답 초안이 들어갑니다. 실제 병원 기록에 쓴다면 병원 내부 모델이나 계약으로 보호되는 전용 환경이 필요합니다([운영 가이드](medicloak/README.md#운영-가이드)).
- 사용 통계나 원격 기록을 보내는 코드는 없습니다.
- 팀원과 화면을 나눌 때의 주의점은 [팀원 · 휴대폰에서 열기](#웹으로-열기)에 있습니다.

**저장소에 올리기 전 확인**

```bash
git status --short          # 올라갈 파일 목록. .env · runs/ · *.db · initial_accounts.txt가 보이면 멈춥니다
git diff --cached --stat    # 스테이징한 파일만 다시 확인
git grep -n -I -E 'sk-(ant|proj)-|ghp_[A-Za-z0-9]{20}|AKIA[0-9A-Z]{16}' -- .    # 키 모양 문자열 (아무것도 나오지 않아야 함)
```

VS Code의 소스 제어에서 '모든 변경 내용 스테이징'을 누르기 전에도 목록을 먼저 봅니다. 키를 실수로 커밋했다면 지우는 커밋을 더해도 기록에 남으므로, 먼저 발급한 곳에서 그 키를 폐기하고 새로 받습니다.

---

## 동작 방식

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/flow-dark.png">
  <img src="docs/images/flow-light.png" alt="질문부터 화면까지 답 하나가 나가는 7단계: 유사 사례 검색, 입력 게이팅, AI 답 초안, 단서 추출, 후보 수 k, 판정, 다시 확인" width="100%">
</picture>

- **대화 전체를 합쳐서 셉니다.** 이번 답의 단서에, 같은 대화에서 이미 공개된 값과 같은 과거 환자에 대해 다른 대화에서 공개된 값(최근 90일)까지 더해 판정합니다.
- **필요한 만큼만 바꿉니다.** 기준은 후보 5명입니다. 새 단서를 모두 더해도 후보가 5명보다 많으면 그대로 공개하고, 그렇지 않으면 [의료 온톨로지](#의료-온톨로지)의 상위 노드로 넓히거나 가립니다. 나이는 5세 구간, 날짜는 월 단위보다 자세히 공개하지 않습니다.
- **고친 답도 처음부터 다시 셉니다.** 재작성한 답에서 단서를 다시 뽑아 후보 수를 확인하고, 그래도 통과하지 못하면 값 치환, 해당 사례 빼기, 답변 거절 순으로 처리합니다.
- **꼭 필요한 값은 사람이 승인해 공개합니다.** 의료진이 세부 정보 요청을 보내면, 보안 담당자가 그 값을 함께 공개했을 때의 후보 수를 확인한 뒤 승인합니다. 원문 열람, 공개 승인, 규칙 적용은 사유와 함께 감사 기록에 남습니다.

---

## 의료 온톨로지

MediCloak은 답에 나온 표현을 글자 그대로 비교하지 않고, 팀이 구축한 의료 온톨로지(`data/medical/`, v0.10)의 노드로 바꾼 뒤 후보 수를 셉니다. Synthea 합성 환자 576명의 기록을 SNOMED CT, ICD-10-CM, RxNorm, ATC 같은 표준 코드 체계의 계층에 맞춰 단서 8종, 노드 71,692개로 정리했습니다. 진료 사건 51,759건에는 각각 진단 · 약 · 시술 코드와 날짜 · 나이 · 성별 · 지역 노드를 연결해 두었습니다(사건연결표).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/ontology-dark.png">
  <img src="docs/images/ontology-light.png" alt="diphenhydramine 25 mg 정을 RxNorm, 제형, ATC 5단계, 4단계로 올려도 후보 4명이고, ATC 3단계 R06A 전신용 항히스타민제에서 27명이 되어 멈추는 실제 판정" width="100%">
</picture>

- **같은 뜻의 표현을 같은 노드로.** 답에 나온 표현을 표현-노드 매핑표(3,825개)와 날짜 · 나이 규칙으로 노드에 연결합니다. 'Lynn, MA'와 'Lynn, Massachusetts', '2014년 4월 1일'과 '2014-04-01'은 같은 노드가 됩니다. 노드에 연결하지 못한 표현은 후보 수 계산에서 빠져 위험을 놓치게 됩니다. 원본 기록과 대조하는 검증에서 날짜가 이렇게 빠지는 경우를 찾아 판정 규칙 v8에서 고쳤습니다.
- **같은 진료 사건으로 묶어 세기.** 후보 수 계산기(kcalc)는 노드 조건을 사건연결표와 대조합니다. 진단과 그 진단 당시의 나이, 날짜는 한 사건이 함께 만족해야 후보로 남습니다. 환자 한 명에게 진단이 평균 8.8개, 처방이 6.8개 있어 값을 따로 맞추면 후보가 부풀려집니다. 576명 전체에서 '당뇨병 + 60대'를 따로 세면 25명, 사건으로 묶어 세면 4명입니다.
- **필요한 만큼만 넓히기.** 위험한 값은 부모 노드로 한 단계씩 올리며 후보 수를 다시 세고, 처음으로 5명을 넘는 단계에서 멈춥니다. 넓힌 노드는 그 아래 노드를 가진 환자를 모두 후보로 셉니다. 위 그림의 약은 네 단계를 올라간 'R06A 전신용 항히스타민제'(27명)로 공개됐고, 그보다 넓은 'R 호흡기계 약'까지는 올리지 않았습니다. 원래 값으로 후보가 3명 이하이면 넓히지 않고 가립니다.

| 단서 | 계층 (왼쪽이 가장 자세함) | 노드 |
| --- | --- | ---: |
| 진단 | SNOMED CT → ICD-10-CM 코드 → 3자리 → 블록 → 장 | 709 |
| 약 | RxNorm → 제형 · 성분 → ATC 5단계 | 752 |
| 시술 | SNOMED CT → ICD-10-PCS 신체 계통 → 구분 | 133 |
| 관리 계획 | SNOMED CT 상위 개념 | 65 |
| 시기 | 일 → 월 → 분기 → 연. 진단 · 처방 · 시술 · 관리 계획 · 진료의 시작과 끝마다 따로 | 69,277 |
| 나이 | 1세 미만의 일령 · 주령 → 세 → 5세 → 10세 구간 | 563 |
| 지역 | 도시 → 주 | 190 |
| 성별 | 남 · 여 | 3 |

모든 계층의 맨 위는 '조건 없음'입니다. SynthPAI 단계에서 쓰던 준식별정보 8종 온톨로지(`ontology/`)는 [docs/ontology.md](docs/ontology.md)에 정리되어 있습니다.

---

## 주요 기능

**의료진** · 진료 지원 AI

- **[내 담당 환자 · 차트 요약](docs/images/screen-emr.png)**: 로그인하면 자기 담당 외래 환자만 등록번호(`26-4821`)와 함께 보입니다. 줄마다 응급실 분류판처럼 색으로 나눈 환자 위험 등급(1 위급 ~ 5 안정, 기록으로 센 참고 등급)이 있고, 등급으로 거르거나 위험 높은 순으로 늘어놓을 수 있습니다. 환자를 고르면 내원 이력(해 × 달 달력: 칸 색은 그달 기록 종류, 숫자는 내원 수, 점은 새 진단 · 첫 시술. 해나 달을 누르면 그때 내원이 아래에 보임), 진단 이력, 처방, 시술, 관리 계획을 기록 종류마다 같은 색으로 정리한 차트가 나오고, 같은 화면에서 진료 목적(처방, 시술·치료, 경과·관리)을 골라 유사 사례를 찾습니다. 차트 머리에는 위험 등급과 그 까닭이 보입니다. 목록에는 생년과 거주 지역을 표시하지 않습니다.
- **[협진 의뢰 · 담당 외 환자 열기](docs/images/screen-consult.png)**: 담당 의료진이 차트에서 협진 의뢰를 보내면, 받은 의료진은 목록 맨 위에서 번호를 적지 않고 12시간 동안 엽니다. 의뢰 없이 당직 · 응급으로 꼭 봐야 하면 등록번호와 사유를 적고 엽니다. 둘 다 감사 기록에 남고 보안 담당자가 검토합니다.
- **[유사 사례 조회](docs/images/screen-clinic.png)**: 사례별 대화, 검색된 사례 전체에 대한 질문, 답에 실제로 나온 값만 모은 사례 노트, 보내기 전 확인, 세부 정보 요청. 답의 '비공개' · '범위' 표시를 누르면 어느 사례의 무엇을 왜 바꿨는지 그 자리에 설명이 뜨고, 답 아래에는 사례마다 바뀐 항목이 한 줄씩 보입니다. 답을 기다리는 동안 지금 하는 일을 적은 띠와 단계 막대(답 쓰기 → 보호 확인 → 필요하면 고쳐 쓰기 · 다시 확인)가 보이고, 멈추기로 질문을 거둘 수 있습니다.
- **[유사 사례 보고서](docs/images/screen-case-report.png)**: 찾은 사례마다 주진단, 그 무렵 시작한 처방 · 시술 · 관리 계획, 기록상 경과(기간 · 횟수를 범위로)를 한 문서로 모으고 PDF로 받습니다. 보고서 값도 답과 같은 기준으로 판정해 비공개 · 범위가 그대로 보이며, 담은 값은 그 대화에서 공개한 것으로 셉니다. 웹 화면과 데스크톱 앱 모두에서 쓸 수 있습니다.

**보안 담당자** · MediCloak 관제

- **[실시간 관제](docs/images/screen-monitor.png)**: 세 줄 요약(위험했던 것, 시스템이 한 일, 담당자가 할 일), 방어 방식별 후보 수 눈금, 사유를 남기는 원문 열람, 값 공개 승인, 대화별 규칙, 검토 보조 에이전트의 초안
- **[의료진 대화 분석](docs/images/screen-watch.png) · [단서 그래프](docs/images/screen-graph.png)**: 단서별로 후보가 줄어든 과정, 답별 판정 표(가리지 않았다면 후보가 몇 명이었는지), 사례와 단서의 연결
- **[레드팀 리포트](docs/images/screen-report.png)**: 실제 LLM으로 공격 대화를 실행해 방어 방식별 결과를 비교합니다. 모델이나 판정 규칙이 바뀐 상태로 서버를 시작하면 점검을 자동으로 실행하고 직전 결과와 비교합니다.
- **[EMR 접근 관리](docs/images/screen-emr-access.png)**: 외래 환자마다 담당 의료진, 마지막 접근, 담당 외 접근 거부, 협진 의뢰 · 예외 열람을 환자 기호로만 보여 줍니다. 차트는 사유를 적어야 열리고(그때 등록번호가 보임), 협진 의뢰로 연 열람과 예외 열람은 여기서 사후 검토합니다.
- **[감사 기록](docs/images/screen-audit.png) · [보호 정책](docs/images/screen-policy.png)**: 로그인, EMR 열기, 질문, 열람, 승인, 규칙, 예외 열람, 레드팀 기록과 현재 적용 중인 판정 기준 · 보호 설정

**어디서나 같은 화면**

- **[데스크톱 앱](docs/images/screen-desktop.png)**: 창 하나로 켜는 macOS · Windows 앱입니다. 서버는 같은 프로세스에서 돌다가 창을 닫으면 멈추고, 글꼴과 아이콘을 앱 안에 넣어 인터넷이 막힌 내부망에서도 같은 화면이 열립니다.
- **모바일**: 같은 주소를 휴대폰 브라우저로 열면 아래쪽 탭으로 화면을 오가는 모바일 화면이 됩니다. 사용법은 [바로 써 보기](#바로-써-보기)에 있습니다.

---

## 시스템 구성

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/arch-dark.png">
  <img src="docs/images/arch-light.png" alt="의료진 화면과 보안 담당자 관제가 FastAPI 서버에 연결되고, 서버는 SQLite · FHIR · 사례 문서 · LLM을 사용하며 판정은 실험 코드(medical/)를 그대로 쓰는 구성" width="100%">
</picture>

- 화면 두 개(의료진, 보안 담당자)와 서버 하나로 구성됩니다. 역할은 로그인 계정으로 나뉘며, 의료진 화면 API에는 후보 수 같은 위험 수치를 보내지 않습니다.
- 서버의 판정은 실험 코드(연구 하네스, `medical/`)의 후보 수 계산(kcalc)과 Defender를 그대로 사용합니다. 실험에서 측정한 방어와 실제 화면에서 동작하는 방어가 같은 코드입니다.
- 데이터는 Synthea 합성 환자 576명입니다. 461명은 과거 기록(AI 검색 대상이자 기준 집단)으로, 나머지 115명은 외래 환자(첫 질문용)로 사용합니다. 실제 환자 정보는 포함되어 있지 않습니다.

---

## 검증 결과

같은 공격 대화로 세 방식을 비교했습니다. **방어 없음**(C0)은 기존 AI 그대로, **단일 응답 가드레일**(C1S)은 답 하나씩만 검사, **누적 가드레일**(C1, MediCloak)은 대화 전체를 합쳐 검사합니다. 아래 그림과 앱 화면에서는 단일 응답 가드레일을 '턴별 방어', 누적 가드레일을 '누적 방어'로 적었습니다. 판정 기준은 후보 6명 이상이면 원문 공개, 4~5명이면 일반화, 3명 이하면 억제입니다.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/results-dark.png">
  <img src="docs/images/results-light.png" alt="공격 대화 296건 중 기준 아래로 좁혀진 비율은 방어 없음 95.6%, 턴별 방어 83.1%, 누적 방어 0%이고, 누적 방어는 의료정보 87.2%를 그대로 공개함" width="100%">
</picture>

| 지표 | 측정 조건 | 결과 |
| --- | --- | --- |
| 위반율 (8턴 안에 후보가 5명 미만으로 좁혀진 대화) | 의료 공격 대화 296건 × 세 방식, 모의 POC(기록대로 답하는 결정적 응답기) | 방어 없음 95.6%(283건) · 단일 응답 83.1%(246건) · **누적 0%(0건)**. 방어 없음 대 누적의 McNemar 정확 검정 불일치 쌍 283 : 0 |
| 다른 데이터의 위반 | SynthPAI 30명 × 12턴 | 방어 없음 24명 · 단일 응답 19명 · **누적 0명** |
| 개인정보 단서 그대로 공개 (낮을수록 안전) | 나이 · 성별 · 지역 · 날짜, 위 296건 | 방어 없음 100% · 단일 응답 93% · **누적 63.8%**. 날짜 70% · 나이 24% · 지역 22%를 가렸고, 그대로 나간 단서 가운데 후보를 5명 미만으로 좁힌 것은 0건 |
| 의료정보 그대로 공개 (높을수록 쓸모) | 진단 · 시술 · 약 · 관리 계획, 위 296건 | 방어 없음 100% · 단일 응답 97.1% · **누적 87.2%** |
| 보호 · 유용성 조화평균 | 보호(100 − 개인정보 공개율)와 의료정보 공개율 | 방어 없음 0 · 단일 응답 13.1 · **누적 51.2** |
| 위반 0%일 때 남는 정보 (유지율) | SynthPAI 표본 | 고정 일반화 2.3% · 단일 응답 25.6%(위반 0%에 기준 k = 100 필요) · **누적 44.5%** |
| 정상 질문 통과율 | SynthPAI 정상 질문 6턴(기준 집단 30만 명) | **98.9%** |
| 공격 질문 고르기 (Privacy Fuzzer) | 같은 대화 296건, 방어 없는 AI | 후보를 5명 미만까지 먼저 좁힌 환자: k 피드백 100명 · 무작위 40명 (2.5배) |
| 찾은 위험을 규칙으로 | 위험 대화 230건의 핵심 단서(지역 · 나이 · 진단)로 규칙 2개를 만들어 다른 231명에 다시 실행 | 누적 위반 0.4% → 0%, 유지율 50.1% → 55.5% |
| 단서 추출 | 처음 보는 질의 환자 13명, 정답 단서 2,566개, claude-haiku-4.5 | 재현율 89.2% · 정밀도 89.2% · F1 0.892. 날짜 · 표 형식의 표기 차이를 채점 규칙에 맞춘 교정값은 정밀도 97.0% · F1 0.929. 위험 계산 반영률 83.2% |
| 판정 시간 | 실제 LLM 답, LLM 호출 제외 | 평균 1.1초 · 중앙값 0.52초 · p95 4.0초. 한 턴 전체는 평균 19.4초(표본 6명, 대부분 단서 추출과 다시 확인) |

**조건을 바꿔도 같은가.** 위 296건과 같은 조건에서 방어 기준(일반화 · 억제)을 5/3 · 10/5 · 20/10으로 바꿔도 누적 가드레일의 위반율은 0%였습니다([결과](results/35_threshold_sensitivity/README.md)). 기준 k · 명단 크기 · 공개 순서를 바꾼 시뮬레이션에서도 1.1% 이하였습니다. 다만 단서를 10% 놓치면 약 32%, 20% 놓치면 약 54%까지 올라갔습니다([결과](results/sim42_sensitivity_20261108/README.md)). 결과를 좌우하는 것은 단서 추출 정확도입니다.

<details>
<summary>결과를 다시 계산하는 명령 (LLM 호출 없음)</summary>

```bash
python -m medical.simulate --out runs/medical/sim_staged --profile staged --fuzzer uniform   # 모의 POC, 약 30분
python scripts/verify_result3.py runs/medical/sim_staged                                     # 위 표의 위반율과 판정 비율
```

단서 추출 정확도의 기록과 채점 방법은 [medical/scoring/결과_기록.md](medical/scoring/결과_기록.md)에, 민감도 실행 방법은 각 결과 폴더의 README에 있습니다. 후보 수를 세는 기준 집단 데이터와 그 변화 과정은 [dataset 브랜치](https://github.com/ZEROPII/ZEROP_PII/tree/dataset)에 있습니다.
</details>

**해석할 때 유의할 점**

- k는 고정된 기준 집단(461명) 안에서 조건을 만족하는 후보 수입니다. 실제로 신원이 확인되는지나 법적 안전성을 보장하는 값은 아닙니다.
- 위반율 · 공개율은 기록대로 답하는 모의 POC에서 잰 값입니다. 실제 LLM 측정은 표본 6~13명 규모라 더 넓은 측정이 필요합니다. 데이터는 한 주(Massachusetts)의 합성 환자입니다.
- 단서 추출 재현율(89.2%)은 목표 95%에 못 미칩니다. 실제 LLM 답에서 찾은 단서의 약 4분의 1이 표기 차이로 위험 계산에서 빠지던 것을 표기 규칙으로 보완해 반영률을 71%에서 83%로 올렸지만, 놓친 단서는 후보 수 계산에 들어가지 않습니다.
- 판정 시간 p95 4.0초는 요구사항(답 1건당 0.1초 이내, LLM 제외)을 채우지 못했습니다.
- 후보 전원이 같은 값을 가지면 누구인지 몰라도 그 값은 알려질 수 있습니다(동질성 문제). k만으로는 막지 못하는 부분입니다.

---

## 보안 설계

- **역할 분리.** 의료진과 보안 담당자는 서로의 API를 쓸 수 없습니다. 미들웨어와 경로별 검사 두 곳에서 확인하며, 로그인 없이 호출하면 401, 다른 역할의 경로는 403을 돌려줍니다.
- **비밀번호와 세션.** 비밀번호는 PBKDF2-HMAC-SHA256(200,000회 반복, 계정별 salt)으로 해시해 저장합니다. 세션 토큰은 HttpOnly 쿠키로 발급하고 DB에는 SHA-256 해시만 둡니다. 세션은 12시간이 지나거나 60분 동안 쓰지 않으면 만료되고, 같은 계정 · IP에서 10분 안에 5번 틀리면 로그인을 막습니다.
- **원문 열람.** 보안 담당자도 열람 사유를 고르고 확인할 내용을 적어야 AI의 원래 답과 가린 값을 볼 수 있습니다. 감사 기록과 관제 화면에는 환자 번호 대신 HMAC으로 만든 가명 기호(`P-3f9a1c`)가 남습니다.
- **담당 환자만 열기.** 외래 환자도 담당 의료진만 목록, 차트, 진료 지원 AI, FHIR로 열 수 있습니다. 담당이 아닌 환자는 담당 의료진이 보낸 협진 의뢰로 열거나, 등록번호와 사유를 적어야 12시간 동안 열리고, 그 열람은 감사 기록에 남아 보안 담당자가 검토합니다. 등록번호는 무작위 네 자리라 번호를 차례로 넣어 열어 볼 수 없습니다. 서버 옵션 `--break-glass off`로 예외 열람을 끌 수 있습니다(협진 의뢰는 그대로).
- **과거 기록 환자.** 검색 대상 461명은 FHIR로 조회할 수 없고, 진료 지원 AI의 답과 MediCloak 판정을 거쳐서만 보입니다.
- **민감 정보.** 물질 사용, 정신 건강, 생식, HIV 관련 값은 후보가 10명 이상일 때만 공개하고, 미성년 시기에 물질 사용 장애가 있던 환자는 검색 대상에서 제외합니다.
- **답변 시간 한도.** 90초 안에 확인을 마치지 못한 답은 내보내지 않고, 시간이 걸려 보내지 않았다는 안내 문장으로 대신합니다 (ADR-0043).
- **API 키.** `.env`에서만 읽으며 화면, 로그, 감사 기록, 오류 문구에 남기지 않습니다.

자세한 동작과 실제 운영 시 정해야 할 사항(외부 LLM으로 전송되는 데이터, 승인 담당자 당직, 감사 기록 보관 기간)은 [medicloak/README.md](medicloak/README.md)에 있습니다. 실행하는 사람의 키와 기록을 지키는 방법은 [내 데이터가 밖으로 나가지 않게](#내-데이터가-밖으로-나가지-않게)에 정리했습니다.

---

## 개발과 시험

```bash
pip install -r webdemo/requirements.txt   # 서버 · 실험 코드 · pytest (루트 requirements.txt 포함)
python -m pytest -q                   # 955 passed, 7 skipped, fpdf 미설치 시 test_triage_report 1건 실패 (LLM 호출은 가짜 HTTP 세션으로 대체)
cd frontend && npm ci && npm test     # vitest 104 passed
```

기준 · 구조 · 실험 방식을 바꾸는 결정은 [ADR](docs/adr/README.md)로 남기고, PR에는 `.env` · `runs/` · 기준 집단 데이터가 커밋에 없는지 확인하는 항목이 있습니다.

---

## 저장소 구성

```text
ZEROP_PII/
├─ medicloak/              # 운영 모드 실행: init · serve · app(데스크톱 앱) · users · assign · check-llm
├─ packaging/              # 데스크톱 앱 묶음 설정(PyInstaller) · 앱 아이콘
├─ webdemo/backend/        # FastAPI 서버: 로그인 · 진료 대화 · 공개 전 검사 · 관제 · 레드팀
├─ frontend/               # React 화면: 진료 지원 AI(의료진) · MediCloak 관제(보안 담당자), 모바일 화면 포함
├─ medical/                # 의료 시나리오 실험 코드: 문서 · 검색 · 대상 AI · 추출 · kcalc · Defender · 퍼저
│  ├─ bundle/              # 팀에서 전달받은 고정본 (정규화 · 참조 구현 · 검증)
│  ├─ scoring/             # 단서 추출 채점과 보류 검증
│  └─ terminology.py       # 의료 용어 RAG (이유진)
├─ risk_defender/          # Privacy State · k 계산 · 판정 정책 (이유진)
├─ fuzzer/                 # k 피드백으로 변형 전략을 고르는 공격 질문 생성 (한재이)
├─ evaluation/             # 평가 지표 정의 · 통계 검정, eval-metrics (이정민)
├─ eval_demo/              # 평가 지표 22개 대시보드 (이정민)
├─ data/medical/           # 의료 온톨로지 노드 · 사건연결표 · 표현-노드 매핑표 · Seed Registry
├─ results/                # 발표용 추가 결과: 방어 기준 민감도 · sim42 시뮬레이션
├─ core/                   # .env 설정 · LLM 호출 (모든 모듈 공통)
├─ scripts/                # 측정 · RAG 재측정 · 결과 다시 세기 · 데스크톱 앱 묶기 · ADR 도구
├─ tests/                  # pytest (LLM 경로는 가짜 HTTP 세션으로 시험)
└─ docs/                   # ADR 44건 · 의료 시나리오 · 평가 통합 문서 · README 그림
```

SynthPAI(일반 게시글) 단계의 모듈(`target_llm/` · `qi_extractor/` · `normalizer/` · `attack/` · `ontology/` · `adapters/` · `orchestrator/` · `validation/` · `api_server/` · `analysis/` · `evaluation_v1/` · `risk_defender_synthpai/`)은 그대로 두었습니다. 의료 데이터로 전환하기 전의 실험을 재현할 때 사용하며, 설명은 [docs/research_harness.md](docs/research_harness.md)에 있습니다. 평가 프로토타입(`eval/`과 루트의 `eval_baseline.py` · `log_schema.py` · `run_demo.py`)은 [docs/evaluation.md](docs/evaluation.md)에 설명되어 있습니다.

## 관련 문서

- [시연 영상](https://drive.google.com/file/d/1HUJPo0GUUjoJog1v-2vt1aLyHxIpSjFw/view?usp=sharing): 데모 웹앱 실제 화면 녹화 (4분 58초)
- [medicloak/README.md](medicloak/README.md): 운영 모드의 옵션, 데스크톱 앱, 화면 흐름, API, 보안 동작, 운영 가이드
- [docs/medical.md](docs/medical.md): 의료 시나리오 실험 코드와 기준 집단 사전 점검
- [docs/adr/](docs/adr/README.md): 설계 결정 기록 44건
- [docs/evaluation.md](docs/evaluation.md): 평가 통합 문서(evaluation_proto · eval-metrics)
- [docs/rag_remeasure/](docs/rag_remeasure/README.md): RAG 기준 재측정 도구와 원본 대조 검증기
- [dataset 브랜치](https://github.com/ZEROPII/ZEROP_PII/tree/dataset): 기준 집단 데이터(Synthea 환자 프로필 · 노드 · 사건연결표 v0.9, SynthPAI 300명 · 30만 명 프로필)와 그 변화 과정
- [docs/README.md](docs/README.md): 나머지 문서 안내

---

## 팀

**Team Zero PII** · 멘토 박소현

| 이름 | 역할 | 맡은 일 |
| --- | --- | --- |
| 양승준 | System Integration · Development Lead | RAG 기반 대상 AI와 단서 추출, 모듈 통합, MediCloak 서버와 화면, 실험 자동화 |
| 한재이 | Privacy Fuzzing · Offensive Security Lead | 공격 시나리오, Seed와 변형, k 피드백 퍼저 |
| 이유진 | Privacy Risk · Defense Lead | Privacy State와 k 계산, 판정 정책, 의료 용어 RAG |
| 이정민 | Evaluation · Assurance Lead | 실험 설계, 평가 지표, 평가 대시보드 |
| 배성윤 | Research · Policy & Privacy Model Lead | 위협 모델, 준식별정보 정의, 온톨로지와 연구 논리 |

- 주간 스크럼과 Jira 백로그로 진행했고, 기준 · 구조 · 실험 방식을 바꾼 결정은 [ADR](docs/adr/README.md)로 남겼습니다.
- 논문: 「멀티 턴 LLM 대화의 개인정보 재식별 위험 대응을 위한 상태 기반 공개 전 방어 기법 연구」(State-Aware Pre-Release Defense against Re-Identification Risk in Multi-Turn LLM Conversations), 한국융합보안학회 2026 추계학술대회(2026.11.6, 성신여자대학교) **우수논문상**. 의료 실험은 이 논문의 향후 연구로 이어서 수행했습니다.

<sub>모든 환자 데이터는 Synthea로 만든 합성 데이터입니다. 화면의 의료진 · 보안 담당자 이름과 계정은 시연용입니다.</sub>
