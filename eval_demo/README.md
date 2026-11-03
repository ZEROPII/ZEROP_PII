# 비식별화 성능 평가 대시보드

Privacy Fuzzer · 누적 가드레일의 평가 지표를 보여주는 정적 웹 페이지입니다.
빌드 도구 없이 `index.html`만 열면 동작합니다.

## 폴더 구조

```
eval_demo/
├─ index.html            # 화면 뼈대
├─ style.css             # 스타일
├─ app.js                # 표·그래프·필터 렌더링
├─ data.js               # 화면에 쓰는 데이터 (build_data.py가 생성)
├─ poc_summary.json      # 원본 실험 결과 (webdemo/data/poc_summary.json과 같은 파일)
└─ build_data.py         # poc_summary.json → data.js 변환 (python eval_demo/build_data.py)
```

데모 서버(`python -m webdemo`)를 켜면 `http://127.0.0.1:8000/eval/`에서도 열리고, 앱의 리포트 화면에서 이 페이지로 가는 링크가 있습니다.

## VS Code에서 보기

1. 폴더를 VS Code로 엽니다.
2. 확장 프로그램 **Live Server**를 설치하고 `index.html`에서 우클릭 → *Open with Live Server*.
   (`index.html`을 브라우저로 직접 열어도 됩니다. 데이터를 `fetch`가 아닌 `<script>`로 읽기 때문입니다.)

## GitHub Pages로 올리기

```bash
git init
git add .
git commit -m "feat: 평가 지표 대시보드"
git branch -M main
git remote add origin https://github.com/<아이디>/<저장소>.git
git push -u origin main
```

저장소의 **Settings → Pages → Build and deployment**에서 Source를 `Deploy from a branch`,
Branch를 `main` / `(root)`로 선택하면 `https://<아이디>.github.io/<저장소>/`에서 열립니다.

## 숫자를 바꾸는 방법

| 바꾸고 싶은 것 | 어디를 고치나 |
|---|---|
| 의료 실험 결과(위반율, 과잉 수정률, 먼저 찾은 환자 수 등) | 새 `poc_summary.json`을 `eval_demo/`에 넣고 `python eval_demo/build_data.py` |
| SynthPAI 정보 유지율, 정상 질문 통과율, 처리 시간 | `eval_demo/build_data.py` 위쪽 `STATIC` 값 수정 후 같은 명령 재실행 |
| 단서 추출 Precision / Recall / F1 | `STATIC["extraction"]`의 `None`을 측정값으로 교체 (예: `"f1": 0.91`) → 화면의 "측정 전"이 숫자로 바뀝니다 |
| `staged` / `full` 시나리오 이름 | `build_data.py`의 `scenarioLabels` (의미에 맞는 한글 이름으로) |
| 22개 지표의 측정 상태 | `app.js`의 `allMetrics()` |

## 값의 출처

- 위반율 · 과잉 수정률 · 조건별 비교 · 턴별 그래프 · 먼저 찾은 환자 수: `poc_summary.json` (의료 실험, 환자 296명)
- 정보 유지율 · 정상 질문 통과율 · 처리 시간: 발표자료 37·39·42p 값 (JSON에 없음)
- 단서 추출 정확도: holdout_2(처음 보는 질의 환자 13명) 팀 고정본 채점값. 측정 방법은 `medical/scoring/README.md`
