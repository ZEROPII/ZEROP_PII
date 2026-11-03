# 의료 용어 RAG

LLM 답변에 등장하는 의료 용어를 환자·보호자가 이해할 수 있는 한국어로 설명해주는 RAG 모듈.
Defender가 공개한 용어에 대해 관리자 화면이 용어 카드를 표시할 때 이 모듈을 통해 설명과 일반화 체인을 조회한다.

담당: 이유진

## 파일 구조

| 파일 | 설명 |
|------|------|
| `medical/terminology.py` | SQLite 검색 로직 (search / get / list_terms / generalization_chain) |
| `scripts/build_terminology_db.py` | DB 최초 생성 스크립트 (LLM으로 설명 생성) |
| `api_server/app.py` | 엔드포인트 3개 추가 (기존 파일 수정) |
| `data/medical/terminology.db` | 생성된 SQLite DB — .gitignore 처리, 스크립트로 재생성 |

등록 용어: DX 709개 / MED 752개 / PROC 133개 (총 1,594개, 576명 기준)

## DB 생성

```bash
# 처음 생성
python scripts/build_terminology_db.py

# LLM 없이 메타데이터만 먼저 저장
python scripts/build_terminology_db.py --no-llm

# 중단 후 이어서 (설명 없는 노드만 처리)
python scripts/build_terminology_db.py --resume

# 특정 분류만
python scripts/build_terminology_db.py --attributes DX
```

`.env`에 `LLM_API_KEY` / `LLM_API_BASE` / `LLM_MODEL` 필요.  
`terminology.db`는 스크립트로 재생성 가능하므로 git에 올리지 않는다.

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/terminology/search?q=심근&limit=20` | 키워드 FTS 검색. `attribute` 필터 가능 (DX·MED·PROC) |
| GET | `/api/terminology/{node_id}` | 단건 조회 + 일반화 체인 포함 |
| GET | `/api/terminology` | 목록 조회 (limit / offset 페이지네이션) |

## DB 주요 필드

| 필드 | 설명 |
|------|------|
| `node_id` | 온톨로지 노드 ID (기본키) |
| `canonical_label` | 의료 용어 원문 |
| `plain_explanation` | LLM 생성 일반인 설명 (한국어) |
| `standard_code` | RxNorm / ICD-10 / SNOMED / ATC 코드 |
| `k_patients` | 이 값을 가진 환자 수 (576명 기준) |
| `parent_id` | 일반화 체인용 부모 노드 |
| `source` | 코드 체계명 (RxNorm 등) |
| `is_sensitive` | 민감 분류 (0/1) — 팀이 직접 지정 |
| `review_status` | 검토대기 / 검토완료 |
| `reviewer` | 검토자 |
| `reviewed_at` | 검토 날짜 |
| `llm_model` | 설명 생성에 쓴 모델 |

## 준수 규칙

- LLM에는 용어명과 코드만 전달 — 환자 ID·날짜·대화 내용 없음
- 설명마다 `llm_model`·`source` 기록, `review_status` 초기값 `검토대기`
- `is_sensitive`는 코드로 자동 판정하지 않음 — 팀이 DB에서 직접 지정
- ⚠️ SNOMED CT 라이선스 조건 확인 필요

## 화면 연동 (통합 브랜치, 2026-11-03)

보안 담당자나 의료진이 답변에 나온 진단 · 약 · 시술 이름을 모를 때 화면 안에서 바로 찾는다. 화면에서는 LLM을 부르지 않고 이 DB만 읽는다.

| 어디서 | 무엇을 |
|------|------|
| 위쪽 막대 `용어` 버튼, ⌘K 명령 찾기 | 오른쪽 옆 패널. 대화를 가리지 않고 검색 · 용어 카드를 본다 |
| 의료진 화면 AI 답변 | 답변 속 용어에 밑줄 (마우스를 올리면 짧은 설명, 누르면 카드), 답변 아래 `이 답변의 의료 용어` 칩 |
| 보안 담당자 관제 상세 | 턴마다 `내보낸 답 보기`(밑줄 포함)와 `답에 나온 의료 용어` 칩 |
| 보안 담당자 `용어` 메뉴 (`/terms`) | 전체 목록, 분류 · 검토 상태 거르기, 카드 (기준 집단 환자 수 포함) |

자동 표시(밑줄 · 칩)는 옆 패널의 `답변에 자동 표시`로 끄고 켠다.

용어 카드: 쉬운 설명(검토 상태 · 설명 만든 모델), 코드 체계와 코드, 넓힌 이름(일반화 체인, 방어 규칙이 값을 넓힐 때 쓰는 단계), 보안 담당자 보기에만 기준 집단에서 그 값을 가진 환자 수.

### 더한 코드

| 파일 | 내용 |
|------|------|
| `medical/term_service.py` | 이 모듈(TerminologyDB) 위의 화면용 기능: 앞부분 · 부분 일치 · 코드 검색, 카드(뿌리 ANY 노드 뺀 일반화 체인), 답변 속 용어 찾기, DB 상태 |
| `medical/terminology_api.py` | API 라우터. `api_server`(실제 LLM)와 `webdemo`(데모 서버)가 같은 경로로 쓴다 |
| `frontend/src/…/terminology/` · `pages/TerminologyPage.tsx` · `state/TermContext.tsx` | 옆 패널, 밑줄, 칩, 용어 사전 화면 |

API는 위 세 경로를 그대로 두고 두 개를 더했다.

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/terminology/status` | 용어 수, 설명 채운 수, 검토 완료 수 |
| POST | `/api/terminology/detect` | `{"texts": [...], "view": "clinician"}` → 글마다 용어 위치(start · end · node_id)와 요약 |

모든 경로에 `view=security|clinician`을 줄 수 있다. 기본 `security`는 위 표의 필드 그대로이고, `clinician`은 `k_patients` · `total_patients`를 뺀다
(의료진 화면에 '이 진단은 기준 집단에 몇 명'이 보이지 않게 하는 표시 규칙이며 접근 통제는 아니다).

답변 속 용어 찾기는 노드 이름과 `표현_노드_매핑표`(정규화기가 쓰는 별칭)를 긴 것부터 찾고, 영문 · 숫자 낱말 중간은 건너뛴다(`Gingivitis는`은 잡고 `xGingivitis`는 안 잡음). 네 글자 미만이거나 숫자뿐인 표현은 찾지 않는다.

### DB가 없을 때

`data/medical/terminology.db`가 없으면 서버가 노드 표로 설명 없는 DB를 임시 폴더에 만들어 화면이 바로 동작한다 (`--no-llm`과 같은 내용).
쉬운 설명과 한국어 검색은 설명을 채운 뒤에 된다.

```bash
python scripts/build_terminology_db.py --no-llm     # 용어 1,594개 메타데이터 (LLM 0, 몇 초)
python scripts/build_terminology_db.py --resume     # 설명 없는 용어만 LLM으로 채움 (용어 하나에 호출 1번)
```

DB를 만든 뒤 서버(`python -m webdemo` 또는 `python -m api_server`)를 다시 켜면 반영된다.

### 고친 점

- `_source_of` / `source_of`: 노드 표 v0.10의 RxNorm 노드는 `MED_IN_` · `MED_DF_` · `MED_RX_`로 시작해서 `_RXN_` 조건에 걸리지 않고 '기타'로 나왔다 → RxNorm으로. `PROC_SECTION_` · `PROC_GROUP_`은 ICD-10-PCS.
