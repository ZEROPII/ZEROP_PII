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
