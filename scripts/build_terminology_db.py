# 의료 용어 RAG DB 생성 스크립트
#
# 노드_v0.9.csv에서 DX·MED·PROC 노드를 읽어 SQLite DB를 만든다.
# LLM에는 용어 이름과 코드만 보낸다 (환자 ID·날짜·대화 내용 없음).
# 설명마다 사용 모델을 기록한다. 검토 상태는 초기값 '검토대기'.
# 민감 분류(is_sensitive)는 팀이 DB를 열어 직접 채운다.
#
# 사용법:
#   python scripts/build_terminology_db.py
#   python scripts/build_terminology_db.py --dry-run         # LLM 호출 없이 노드 목록만 확인
#   python scripts/build_terminology_db.py --resume          # 이미 설명 있는 노드는 건너뜀
#   python scripts/build_terminology_db.py --batch-size 20   # 한 번에 처리할 노드 수
#   python scripts/build_terminology_db.py --attributes DX MED  # 특정 attribute만

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from medical.config import MedicalPaths

# 설명을 생성할 attribute (AGE·SEX·REGION·PERIOD·PLAN은 제외)
EXPLAIN_ATTRS = {"DX", "MED", "PROC"}

ATTR_LABEL_KO = {"DX": "진단", "MED": "약", "PROC": "시술·처치"}

SEMTAG = re.compile(r" \((disorder|procedure|regime/therapy|record artifact|finding|situation)\)$")

# node_id 접두사 → 코드 체계 이름 (출처 표시용)
def source_of(node_id: str) -> str:
    if "_RXN_" in node_id:
        return "RxNorm"
    if "_SCT_" in node_id:
        return "SNOMED CT"
    if "_ICD_" in node_id:
        return "ICD-10"
    if "_ATC_" in node_id:
        return "ATC"
    return "기타"


SCHEMA = """
CREATE TABLE IF NOT EXISTS terminology (
    node_id          TEXT PRIMARY KEY,
    attribute        TEXT NOT NULL,
    canonical_label  TEXT NOT NULL,
    plain_explanation TEXT,
    standard_code    TEXT,
    k_patients       INTEGER,
    total_patients   INTEGER,
    parent_id        TEXT,
    level            TEXT,
    source           TEXT,
    is_sensitive     INTEGER DEFAULT 0,
    review_status    TEXT DEFAULT '검토대기',
    reviewer         TEXT,
    reviewed_at      TEXT,
    llm_model        TEXT,
    created_at       TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS terminology_fts USING fts5(
    node_id,
    canonical_label,
    plain_explanation,
    content=terminology,
    content_rowid=rowid
);

-- FTS 트리거: INSERT·UPDATE·DELETE 시 자동 동기화
CREATE TRIGGER IF NOT EXISTS terminology_ai AFTER INSERT ON terminology BEGIN
    INSERT INTO terminology_fts(rowid, node_id, canonical_label, plain_explanation)
    VALUES (new.rowid, new.node_id, new.canonical_label, new.plain_explanation);
END;
CREATE TRIGGER IF NOT EXISTS terminology_au AFTER UPDATE ON terminology BEGIN
    INSERT INTO terminology_fts(terminology_fts, rowid, node_id, canonical_label, plain_explanation)
    VALUES ('delete', old.rowid, old.node_id, old.canonical_label, old.plain_explanation);
    INSERT INTO terminology_fts(rowid, node_id, canonical_label, plain_explanation)
    VALUES (new.rowid, new.node_id, new.canonical_label, new.plain_explanation);
END;
CREATE TRIGGER IF NOT EXISTS terminology_ad AFTER DELETE ON terminology BEGIN
    INSERT INTO terminology_fts(terminology_fts, rowid, node_id, canonical_label, plain_explanation)
    VALUES ('delete', old.rowid, old.node_id, old.canonical_label, old.plain_explanation);
END;
"""

LLM_PROMPT = """\
아래 의료 용어를 환자나 보호자가 이해할 수 있도록 한국어 1~2문장으로 설명하라.
규칙:
- 전문 용어 없이 쉬운 말로만 쓴다.
- 진단 원인·예후 추측은 쓰지 않는다.
- 설명만 출력한다 (앞뒤 부연·따옴표·번호 없이).

용어: {label}
코드: {code}
분류: {attr_label}"""


def _clean_label(node_id: str, label: str) -> str:
    """SNOMED 의미 태그 제거."""
    return SEMTAG.sub("", label) if "_SCT_" in node_id else label


def load_nodes(paths: MedicalPaths, attrs: set[str]) -> list[dict[str, str]]:
    """노드 CSV에서 대상 attribute 노드만 읽는다."""
    nodes = []
    with open(paths.nodes, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row["attribute"] not in attrs:
                continue
            nodes.append(row)
    return nodes


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    con.commit()
    return con


def already_done(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("SELECT node_id FROM terminology WHERE plain_explanation IS NOT NULL").fetchall()
    return {r[0] for r in rows}


def upsert(con: sqlite3.Connection, node: dict[str, str], explanation: str | None, model: str | None, total_patients: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    node_id = node["node_id"]
    label = _clean_label(node_id, node["canonical_label"])
    con.execute(
        """
        INSERT INTO terminology
            (node_id, attribute, canonical_label, plain_explanation, standard_code,
             k_patients, total_patients, parent_id, level, source, llm_model, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(node_id) DO UPDATE SET
            plain_explanation = excluded.plain_explanation,
            llm_model = excluded.llm_model
        """,
        (
            node_id,
            node["attribute"],
            label,
            explanation,
            node.get("standard_code") or None,
            int(node["k_patients"]) if node.get("k_patients") else None,
            total_patients,
            node.get("parent_id") or None,
            node.get("level") or None,
            source_of(node_id),
            model,
            now,
        ),
    )
    con.commit()


def call_llm(label: str, code: str, attr: str) -> tuple[str, str]:
    """LLM에는 용어명과 코드만 전달한다."""
    from core.config import get_settings
    from core.llm_client import LLMClient

    settings = get_settings()
    client = LLMClient(settings)
    prompt = LLM_PROMPT.format(
        label=label,
        code=code if code else "없음",
        attr_label=ATTR_LABEL_KO.get(attr, attr),
    )
    resp = client.chat(
        [{"role": "user", "content": prompt}],
        max_tokens=200,
        temperature=0.0,
    )
    return resp.text.strip(), resp.model


def main() -> None:
    parser = argparse.ArgumentParser(description="의료 용어 RAG DB 생성")
    parser.add_argument("--output", default=str(ROOT / "data" / "medical" / "terminology.db"))
    parser.add_argument("--dry-run", action="store_true", help="LLM 호출 없이 노드 목록만 출력")
    parser.add_argument("--resume", action="store_true", help="이미 설명 있는 노드 건너뜀")
    parser.add_argument("--batch-size", type=int, default=10, help="LLM 호출 간격 조절용 배치 크기")
    parser.add_argument("--sleep", type=float, default=0.5, help="배치 사이 대기 시간(초)")
    parser.add_argument("--attributes", nargs="+", default=sorted(EXPLAIN_ATTRS),
                        help="처리할 attribute 목록 (기본: DX MED PROC)")
    parser.add_argument("--no-llm", action="store_true",
                        help="LLM 호출 없이 노드 메타데이터만 저장 (plain_explanation은 빈칸)")
    args = parser.parse_args()

    attrs = set(args.attributes)
    paths = MedicalPaths()
    nodes = load_nodes(paths, attrs)

    # 전체 환자 수 (k_patients 분모용)
    all_pats: set[str] = set()
    with open(paths.events, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            all_pats.add(row["patient_id"])
    total_patients = len(all_pats)

    print(f"노드 수: {len(nodes)} ({', '.join(sorted(attrs))})")
    print(f"전체 환자 수: {total_patients}")
    print(f"출력 DB: {args.output}")

    if args.dry_run:
        for n in nodes[:10]:
            print(f"  [{n['attribute']}] {n['node_id']} | {n['canonical_label'][:50]} | {n.get('standard_code','')}")
        if len(nodes) > 10:
            print(f"  ... 외 {len(nodes) - 10}개")
        return

    db_path = Path(args.output)
    con = init_db(db_path)
    done = already_done(con) if args.resume else set()

    skipped = 0
    success = 0
    failed: list[str] = []

    for i, node in enumerate(nodes):
        node_id = node["node_id"]
        label = _clean_label(node_id, node["canonical_label"])

        if node_id in done:
            skipped += 1
            continue

        if args.no_llm:
            upsert(con, node, None, None, total_patients)
            success += 1
            if (i + 1) % 100 == 0 or (i + 1) == len(nodes):
                print(f"[{i+1}/{len(nodes)}] 메타데이터 저장 중...")
            continue

        try:
            explanation, model = call_llm(label, node.get("standard_code", ""), node["attribute"])
            upsert(con, node, explanation, model, total_patients)
            success += 1
            print(f"[{success+skipped}/{len(nodes)}] {node_id[:40]:40s} → {explanation[:50]}")
        except Exception as exc:
            print(f"[오류] {node_id}: {exc}", file=sys.stderr)
            upsert(con, node, None, None, total_patients)
            failed.append(node_id)

        if (i + 1) % args.batch_size == 0:
            time.sleep(args.sleep)

    con.close()
    if args.no_llm:
        print(f"\n완료: {success}개 저장 (설명 없음 — 나중에 --resume으로 LLM 설명 채우기)")
    else:
        print(f"\n완료: {success}개 생성 / {skipped}개 건너뜀 / {len(failed)}개 실패")
        if failed:
            print("실패 목록:", failed)


if __name__ == "__main__":
    main()
