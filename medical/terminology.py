# 의료 용어 RAG 검색 모듈
#
# 사전에 build_terminology_db.py로 생성한 SQLite DB를 읽는다.
# LLM 호출 없음 — 검색만.
# 관리자 화면(admin frontend)이 이 모듈을 통해 용어 카드·일반인 설명·일반화 체인을 조회한다.

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from medical.config import ROOT

DEFAULT_DB = ROOT / "data" / "medical" / "terminology.db"

# attribute → 화면 표시 이름
ATTR_LABEL = {
    "DX": "진단",
    "MED": "약",
    "PROC": "시술·처치",
}

# node_id 접두사 → 코드 체계 이름
def _source_of(node_id: str) -> str:
    if "_RXN_" in node_id:
        return "RxNorm"
    if "_SCT_" in node_id:
        return "SNOMED CT"
    if "_ICD_" in node_id:
        return "ICD-10"
    if "_ATC_" in node_id:
        return "ATC"
    return "기타"


@dataclass
class TerminologyDB:
    path: Path

    def _conn(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    # ── 단건 조회 ────────────────────────────────────────

    def get(self, node_id: str) -> dict[str, Any] | None:
        with self._conn() as con:
            row = con.execute(
                "SELECT * FROM terminology WHERE node_id = ?", (node_id,)
            ).fetchone()
        if row is None:
            return None
        return self._format(dict(row))

    # ── 키워드 검색 (FTS5) ───────────────────────────────

    def search(self, q: str, *, limit: int = 20, attribute: str | None = None) -> list[dict[str, Any]]:
        """
        canonical_label과 plain_explanation 전문 검색.
        attribute 지정 시 DX·MED·PROC 중 하나로 필터링.
        """
        q_escaped = q.replace('"', '""')
        attr_clause = "AND t.attribute = ?" if attribute else ""
        params: list[Any] = [f'"{q_escaped}"', limit]
        if attribute:
            params.insert(1, attribute)

        sql = f"""
            SELECT t.*
            FROM terminology t
            JOIN terminology_fts f ON t.rowid = f.rowid
            WHERE terminology_fts MATCH ?
            {attr_clause}
            ORDER BY rank
            LIMIT ?
        """
        with self._conn() as con:
            rows = con.execute(sql, params).fetchall()
        return [self._format(dict(r)) for r in rows]

    # ── 목록 (페이지네이션) ──────────────────────────────

    def list_terms(
        self,
        *,
        attribute: str | None = None,
        review_status: str | None = None,
        is_sensitive: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses, params = [], []
        if attribute:
            clauses.append("attribute = ?")
            params.append(attribute)
        if review_status:
            clauses.append("review_status = ?")
            params.append(review_status)
        if is_sensitive is not None:
            clauses.append("is_sensitive = ?")
            params.append(1 if is_sensitive else 0)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        with self._conn() as con:
            total = con.execute(f"SELECT COUNT(*) FROM terminology {where}", params).fetchone()[0]
            rows = con.execute(
                f"SELECT * FROM terminology {where} ORDER BY attribute, canonical_label LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [self._format(dict(r)) for r in rows],
        }

    # ── 일반화 체인 ──────────────────────────────────────

    def generalization_chain(self, node_id: str) -> list[dict[str, Any]]:
        """
        현재 노드에서 루트까지 일반화 단계 반환.
        예: fexofenadine 60mg → fexofenadine → 항히스타민제
        """
        chain = []
        current = node_id
        with self._conn() as con:
            while current:
                row = con.execute(
                    "SELECT node_id, canonical_label, plain_explanation, parent_id, level FROM terminology WHERE node_id = ?",
                    (current,),
                ).fetchone()
                if row is None:
                    # 부모가 terminology DB에 없으면(루트·AGE 등) 중단
                    break
                chain.append({
                    "node_id": row["node_id"],
                    "label": row["canonical_label"],
                    "plain_explanation": row["plain_explanation"],
                    "level": row["level"],
                })
                current = row["parent_id"] or ""
        return chain

    # ── 내부 포맷 ────────────────────────────────────────

    def _format(self, row: dict[str, Any]) -> dict[str, Any]:
        node_id = row["node_id"]
        return {
            "node_id": node_id,
            "attribute": row["attribute"],
            "attribute_label": ATTR_LABEL.get(row["attribute"], row["attribute"]),
            "canonical_label": row["canonical_label"],
            "plain_explanation": row["plain_explanation"],
            "standard_code": row["standard_code"],
            "source": _source_of(node_id),
            "k_patients": row["k_patients"],
            "total_patients": row["total_patients"],
            "parent_id": row["parent_id"],
            "level": row["level"],
            "is_sensitive": bool(row["is_sensitive"]),
            "review_status": row["review_status"],
            "reviewer": row["reviewer"],
            "reviewed_at": row["reviewed_at"],
            "llm_model": row["llm_model"],
            "created_at": row["created_at"],
        }


# 싱글턴 — api_server에서 한 번만 로드
_db: TerminologyDB | None = None


def get_db(path: Path | None = None) -> TerminologyDB:
    global _db
    if _db is None:
        _db = TerminologyDB(path or DEFAULT_DB)
    return _db
