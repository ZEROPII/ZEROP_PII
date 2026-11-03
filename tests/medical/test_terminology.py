# 의료 용어 RAG: 이유진 medical/terminology.py + 화면용 서비스(medical/term_service.py) + API(medical/terminology_api.py)
# 용어 DB는 노드 표로 설명 없이 만든다 (build_terminology_db.py --no-llm과 같은 내용, LLM 0)
from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from medical.term_service import TermService, level_label
from medical.terminology import TerminologyDB
from medical.terminology_api import terminology_router


@pytest.fixture(scope="module")
def svc(tmp_path_factory) -> TermService:
    return TermService(tmp_path_factory.mktemp("term") / "없는_파일.db")      # 없으면 노드 표로 만든다


def test_metadata_db_has_all_terms(svc):
    st = svc.status()
    assert st["available"] and st["generated"]
    assert st["by_attribute"] == {"DX": 709, "MED": 752, "PROC": 133}
    assert st["explained"] == 0 and st["reviewed"] == 0


def test_teammate_db_api_still_works(svc):
    db = TerminologyDB(svc.path)
    assert db.get("MED_RX_308136")["source"] == "RxNorm"                     # MED_RX_ · MED_IN_ · MED_DF_ = RxNorm
    assert db.search("Gingivitis", limit=5)                                  # 이유진 FTS 구절 검색
    chain = [c["node_id"] for c in db.generalization_chain("MED_RX_308136")]
    assert chain[:3] == ["MED_RX_308136", "MED_DF_370573", "MED_IN_17767"]
    assert db.list_terms(attribute="PROC", limit=3)["total"] == 133


def test_search_partial_code_alias(svc):
    assert "DX_SCT_66383009" in [t["node_id"] for t in svc.search("gingiv")]      # 앞부분만
    assert svc.search("K05")[0]["node_id"] == "DX_ICD_CODE_K05"                   # 코드
    assert svc.search("amlodipine", attribute="MED")[0]["node_id"] == "MED_IN_17767"
    assert all(t["attribute"] == "PROC" for t in svc.search("removal", attribute="PROC"))
    assert svc.search("   ") == []


def test_card_chain_aliases_and_views(svc):
    c = svc.card("MED_RX_308136")
    assert c["level_label"] == level_label("MED_RX_308136") == "제품 (성분 · 용량 · 제형)"
    assert not any(x["node_id"].startswith("ANY") or x["node_id"].endswith("_ANY") for x in c["generalization_chain"])
    assert c["k_patients"] > 0 and c["total_patients"] > 0
    clin = svc.card("MED_RX_308136", view="clinician")
    assert "k_patients" not in clin and "total_patients" not in clin
    assert svc.card("NOPE") is None


def test_detect_positions_longest_first_and_boundaries(svc):
    text = "사례1: Gingivitis는 2018-03-09 진단, amlodipine 2.5 MG Oral Tablet 처방. xGingivitis 아님"
    res = svc.detect([text, ""], view="clinician")
    found = [(text[m["start"]:m["end"]], m["node_id"]) for m in res["mentions"][0]]
    assert ("Gingivitis", "DX_SCT_66383009") in found
    assert ("amlodipine 2.5 MG Oral Tablet", "MED_RX_308136") in found            # 성분 'amlodipine'보다 긴 제품명
    assert len([f for f in found if f[0] == "Gingivitis"]) == 1                    # 'xGingivitis'는 낱말 중간
    assert res["mentions"][1] == []
    assert all("k_patients" not in t for t in res["terms"].values())


def test_api_routes(svc):
    app = FastAPI()
    app.include_router(terminology_router(lambda: svc))
    with TestClient(app) as c:
        assert c.get("/api/terminology/status").json()["total"] == 1594
        assert c.get("/api/terminology/search", params={"q": "gingiv", "limit": 3}).status_code == 200
        assert c.get("/api/terminology/search", params={"q": " "}).status_code == 422
        r = c.post("/api/terminology/detect", json={"texts": ["Gingivitis 진단"], "view": "clinician"}).json()
        assert r["mentions"][0][0]["node_id"] == "DX_SCT_66383009"
        assert c.get("/api/terminology/DX_SCT_66383009").json()["generalization_chain"]
        assert c.get("/api/terminology/NOPE").status_code == 404
        assert c.get("/api/terminology", params={"attribute": "DX", "limit": 2}).json()["total"] == 709


def test_unavailable_db_gives_503(tmp_path):
    bad = tmp_path / "empty.db"
    sqlite3.connect(bad).close()
    s = TermService(bad, build_if_missing=False)
    app = FastAPI()
    app.include_router(terminology_router(lambda: s))
    with TestClient(app) as c:
        assert c.get("/api/terminology/status").json()["available"] is False
        assert c.get("/api/terminology/search", params={"q": "x"}).status_code == 503


def test_both_servers_expose_terminology():
    from api_server.app import create_app as research_app
    from webdemo.backend.app import create_app as demo_app

    with TestClient(research_app(workspace_factory=lambda: None)) as c:        # 용어 경로는 연구 작업공간을 만들지 않는다
        assert c.get("/api/terminology/status").status_code == 200
    with TestClient(demo_app(simulations=False)) as c:
        assert c.get("/api/terminology/search", params={"q": "amlodipine"}).json()[0]["canonical_label"].startswith("amlodipine")
        assert c.get("/api/없는경로").status_code == 404                        # 데모 서버의 '없는 경로' 처리는 그대로
