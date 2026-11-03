"""
의료 용어 조회 서비스 — 이유진 medical/terminology.py(TerminologyDB) 위에 화면에 필요한 기능을 더한다 [2026-11-03].

화면(frontend/)에서 보안 담당자와 의료진이 답변 속 의료 용어를 모를 때 쓴다. LLM은 부르지 않는다 (DB 검색만).
  - search   : 이유진 FTS 검색(구절 일치)에 앞부분 일치 · 부분 일치 · 등록 별칭 · 코드 검색을 더해 한국어 · 영어 일부만 쳐도 찾는다
  - card     : 용어 카드 = 설명 + 코드 체계 + 일반화 체인(뿌리 'ANY' 노드 제외) + 등록 별칭
  - detect   : 답변 문장에서 용어를 찾아 위치(start · end)와 노드를 돌려준다 → 화면이 밑줄 · 용어 칩을 자동으로 띄운다
               찾는 표현 = 노드 이름 + 정규화기가 쓰는 표현_노드_매핑표 별칭 (시스템이 단서를 알아보는 기준과 같다)
  - status   : DB 상태 (설명이 채워진 용어 수, 검토 상태 수)

용어 DB가 없으면 노드 표만으로 설명 없는 DB를 임시 폴더에 만든다 (scripts/build_terminology_db.py --no-llm과 같은 내용).
설명은 그 스크립트로 채운다 (LLM에는 용어 이름과 코드만 보냄).

보기(view): 'security'(기본, 이유진 API와 같음)는 모든 필드, 'clinician'은 기준 집단 환자 수(k_patients · total_patients)를 뺀다.
의료진 화면에서 '이 진단은 기준 집단에 1명뿐'처럼 드문 값이 보이지 않게 하려는 표시 규칙이며, 접근 통제는 아니다.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import re
import sqlite3
import tempfile
import threading
from pathlib import Path
from typing import Any

from medical.config import ROOT, MedicalPaths
from medical.terminology import DEFAULT_DB, TerminologyDB

ATTRS = ("DX", "MED", "PROC")
BUILD_COMMAND = "python scripts/build_terminology_db.py"
_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")

# 노드 id 앞부분 → 화면에 보일 단계 이름
_LEVEL = (
    ("DX_ICD_CHAPTER_", "ICD-10-CM 장"), ("DX_ICD_SECTION_", "ICD-10-CM 블록"), ("DX_ICD_CODE_", "ICD-10-CM 코드"),
    ("DX_SCT_", "SNOMED CT 개념"), ("MED_ATC_", "ATC 약효 분류"), ("MED_IN_", "성분"), ("MED_DF_", "성분 · 제형"),
    ("MED_RX_", "제품 (성분 · 용량 · 제형)"), ("PROC_SECTION_", "ICD-10-PCS 구분"), ("PROC_GROUP_", "ICD-10-PCS 부위"),
    ("PROC_SCT_", "SNOMED CT 시술"),
)
_HIDE_FOR_CLINICIAN = ("k_patients", "total_patients")


def _is_root(node_id: str) -> bool:
    return node_id.endswith("_ANY") or node_id.startswith("ANY_")


def level_label(node_id: str) -> str:
    return next((name for prefix, name in _LEVEL if node_id.startswith(prefix)), "상위 분류")


def _metadata_db(paths: MedicalPaths) -> Path:
    """노드 표로 설명 없는 용어 DB를 임시 폴더에 만든다 (노드 표가 바뀌면 새로 만든다)."""
    digest = hashlib.sha256(paths.nodes.read_bytes()).hexdigest()[:12]
    out = Path(tempfile.gettempdir()) / f"zeropii_terminology_meta_{digest}.db"
    if out.exists():
        return out
    spec = importlib.util.spec_from_file_location("build_terminology_db", ROOT / "scripts" / "build_terminology_db.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    nodes = build.load_nodes(paths, set(ATTRS))
    with open(paths.events, encoding="utf-8-sig", newline="") as f:
        total = len({row["patient_id"] for row in csv.DictReader(f)})
    tmp = out.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    con = build.init_db(tmp)
    for node in nodes:
        build.upsert(con, node, None, None, total)
    con.close()
    tmp.replace(out)
    return out


class TermService:
    def __init__(self, db_path: Path | None = None, *, paths: MedicalPaths | None = None, build_if_missing: bool = True) -> None:
        self.paths = paths or MedicalPaths()
        path = Path(db_path) if db_path else DEFAULT_DB
        self.generated = False
        if not path.exists() and build_if_missing:
            path, self.generated = _metadata_db(self.paths), True
        self.path = path
        self.db = TerminologyDB(path)
        self._lock = threading.Lock()
        self._surfaces: list[tuple[str, str]] | None = None
        self._aliases: dict[str, list[str]] | None = None
        self._alias_idx: dict[str, list[str]] = {}

    # ── 상태 ──────────────────────────────────────────────
    @property
    def available(self) -> bool:
        try:
            with sqlite3.connect(self.path) as con:
                con.execute("SELECT 1 FROM terminology LIMIT 1")
            return True
        except sqlite3.Error:
            return False

    def status(self) -> dict[str, Any]:
        if not self.available:
            return dict(available=False, generated=self.generated, build_command=BUILD_COMMAND)
        with sqlite3.connect(self.path) as con:
            by_attr = dict(con.execute("SELECT attribute, COUNT(*) FROM terminology GROUP BY attribute").fetchall())
            explained = con.execute("SELECT COUNT(*) FROM terminology WHERE plain_explanation IS NOT NULL AND plain_explanation != ''").fetchone()[0]
            reviewed = con.execute("SELECT COUNT(*) FROM terminology WHERE review_status = '검토완료'").fetchone()[0]
            sensitive = con.execute("SELECT COUNT(*) FROM terminology WHERE is_sensitive = 1").fetchone()[0]
            models = [m for (m,) in con.execute("SELECT DISTINCT llm_model FROM terminology WHERE llm_model IS NOT NULL")]
        total = sum(by_attr.values())
        return dict(available=True, generated=self.generated, total=total, by_attribute=by_attr, explained=explained,
                    reviewed=reviewed, sensitive=sensitive, llm_models=models, build_command=BUILD_COMMAND,
                    db=("임시 폴더 (노드 표로 만든 설명 없는 DB)" if self.generated else _rel(self.path)))

    # ── 화면용 모양 ────────────────────────────────────────
    def _shape(self, item: dict[str, Any], view: str) -> dict[str, Any]:
        out = dict(item, level_label=level_label(item["node_id"]),
                   has_explanation=bool(item.get("plain_explanation")))
        if view == "clinician":
            for k in _HIDE_FOR_CLINICIAN:
                out.pop(k, None)
        return out

    # ── 검색 ──────────────────────────────────────────────
    def search(self, q: str, *, attribute: str | None = None, limit: int = 20, view: str = "security") -> list[dict[str, Any]]:
        q = q.strip()
        if not q:
            return []
        attribute = attribute if attribute in ATTRS else None
        ranked: dict[str, int] = {}

        def add(ids: list[str], rank: int) -> None:
            for nid in ids:
                if nid not in ranked or ranked[nid] > rank:
                    ranked[nid] = rank

        ql = q.lower()
        with sqlite3.connect(self.path) as con:
            attr_sql, attr_p = ("AND attribute = ?", [attribute]) if attribute else ("", [])
            add([r[0] for r in con.execute(f"SELECT node_id FROM terminology WHERE (lower(canonical_label) = ? OR standard_code = ?) {attr_sql}",
                                           [ql, q, *attr_p])], 0)
            add([r[0] for r in con.execute(f"SELECT node_id FROM terminology WHERE lower(canonical_label) LIKE ? {attr_sql} LIMIT 200",
                                           [f"{ql}%", *attr_p])], 1)
            tokens = _TOKEN.findall(q)
            if tokens:
                fts = " ".join(f'"{t}"*' for t in tokens)
                try:
                    add([r[0] for r in con.execute(
                        f"SELECT t.node_id FROM terminology t JOIN terminology_fts f ON t.rowid = f.rowid "
                        f"WHERE terminology_fts MATCH ? {attr_sql.replace('attribute', 't.attribute')} ORDER BY rank LIMIT 200", [fts, *attr_p])], 2)
                except sqlite3.Error:
                    pass
            add([r[0] for r in con.execute(
                f"SELECT node_id FROM terminology WHERE (lower(canonical_label) LIKE ? OR plain_explanation LIKE ?) {attr_sql} LIMIT 200",
                [f"%{ql}%", f"%{q}%", *attr_p])], 3)
        alias_hits = [nid for surf, nids in self._alias_index().items() if ql in surf for nid in nids]
        add([nid for nid in alias_hits if not attribute or nid.startswith(attribute + "_")], 2)
        order = sorted((nid for nid in ranked if not _is_root(nid)), key=lambda n: (ranked[n], n))
        out = []
        for nid in order:
            item = self.db.get(nid)
            if item and (not attribute or item["attribute"] == attribute):
                out.append(self._shape(item, view))
            if len(out) >= limit:
                break
        return out

    # ── 카드 ──────────────────────────────────────────────
    def card(self, node_id: str, *, view: str = "security") -> dict[str, Any] | None:
        item = self.db.get(node_id)
        if item is None:
            return None
        chain = [dict(c, level_label=level_label(c["node_id"])) for c in self.db.generalization_chain(node_id) if not _is_root(c["node_id"])]
        aliases = [s for s in dict.fromkeys(self._aliases_of().get(node_id, [])) if _useful_alias(s, item)][:8]
        return dict(self._shape(item, view), generalization_chain=chain, aliases=aliases)

    def list_terms(self, *, view: str = "security", **kw: Any) -> dict[str, Any]:
        res = self.db.list_terms(**kw)
        return dict(res, items=[self._shape(x, view) for x in res["items"]])

    # ── 답변 속 용어 찾기 ──────────────────────────────────
    def _load_surfaces(self) -> None:
        with self._lock:
            if self._surfaces is not None:
                return
            with sqlite3.connect(self.path) as con:
                labels = {nid: lab for nid, lab in con.execute("SELECT node_id, canonical_label FROM terminology")}
            by_node: dict[str, list[str]] = {}
            pairs: dict[str, str] = {}
            for nid, lab in labels.items():
                if not _is_root(nid):
                    pairs.setdefault(lab.lower(), nid)
            with open(self.paths.alias, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    nid, surf = row["node_id"], row["surface_form"].strip()
                    if row["attribute"] in ATTRS and nid in labels and not _is_root(nid) and surf:
                        by_node.setdefault(nid, []).append(surf)
                        pairs.setdefault(surf.lower(), nid)
            # 너무 짧거나 숫자 · 기호뿐인 표현은 다른 낱말 안에서 잘못 잡히므로 뺀다
            ok = [(s, n) for s, n in pairs.items() if len(s) >= 4 and re.search(r"[a-z가-힣]", s)]
            self._surfaces = sorted(ok, key=lambda x: -len(x[0]))
            self._aliases = by_node
            idx: dict[str, list[str]] = {}
            for nid, surfs in by_node.items():
                for s in surfs:
                    idx.setdefault(s.lower(), []).append(nid)
            self._alias_idx = idx

    def _aliases_of(self) -> dict[str, list[str]]:
        self._load_surfaces()
        return self._aliases or {}

    def _alias_index(self) -> dict[str, list[str]]:
        self._load_surfaces()
        return self._alias_idx

    def detect(self, texts: list[str], *, view: str = "security", max_terms: int = 60) -> dict[str, Any]:
        """texts 각각에서 찾은 용어 위치와, 찾은 용어의 요약 카드."""
        self._load_surfaces()
        mentions: list[list[dict[str, Any]]] = []
        found: dict[str, int] = {}
        for text in texts:
            low = _lower_same_length(text)
            taken = bytearray(len(text))
            hits: list[dict[str, Any]] = []
            for surf, nid in self._surfaces or []:
                start = low.find(surf)
                while start != -1:
                    end = start + len(surf)
                    if _boundary(low, start, end) and not any(taken[start:end]):
                        taken[start:end] = b"\x01" * (end - start)
                        hits.append(dict(start=start, end=end, node_id=nid))
                        found[nid] = found.get(nid, 0) + 1
                    start = low.find(surf, end)
            mentions.append(sorted(hits, key=lambda h: h["start"]))
        terms = {}
        for nid in sorted(found, key=lambda n: -found[n])[:max_terms]:
            item = self.db.get(nid)
            if item:
                terms[nid] = dict(self._shape(item, view), mentions=found[nid])
        for hs in mentions:
            hs[:] = [h for h in hs if h["node_id"] in terms]
        return dict(mentions=mentions, terms=terms)


_SEMTAG = re.compile(r"\s*\([a-z /]+\)$")


def _useful_alias(alias: str, item: dict[str, Any]) -> bool:
    """카드에 보일 별칭: 이름과 같거나, 이름 + '(procedure)' 같은 꼬리표뿐이거나, 코드 그대로인 것은 뺀다."""
    a, label, code = alias.strip().lower(), item["canonical_label"].lower(), (item.get("standard_code") or "").lower()
    return bool(a) and a != label and _SEMTAG.sub("", a) != label and a != code and not re.fullmatch(r"[0-9a-z]?[0-9.\-]+", a)


def _lower_same_length(text: str) -> str:
    """소문자로 바꾸되 글자 수를 그대로 둔다 (위치 start · end가 원문과 맞아야 함)."""
    low = text.lower()
    return low if len(low) == len(text) else "".join(c.lower() if len(c.lower()) == 1 else c for c in text)


def _boundary(text: str, start: int, end: int) -> bool:
    """영문 · 숫자 낱말 중간이 아니면 참. 한글 조사('Gingivitis는')는 붙어 있어도 된다."""
    before = text[start - 1] if start > 0 else " "
    after = text[end] if end < len(text) else " "
    return not (before.isascii() and before.isalnum()) and not (after.isascii() and after.isalnum())


def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(ROOT))
    except ValueError:
        return p.name


_service: TermService | None = None
_service_lock = threading.Lock()


def get_service() -> TermService:
    global _service
    with _service_lock:
        if _service is None:
            _service = TermService()
        return _service
