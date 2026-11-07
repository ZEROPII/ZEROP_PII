"""scripts/adr.py (ADR 도구) 테스트."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("adr_tool", ROOT / "scripts" / "adr.py")
adr = importlib.util.module_from_spec(_spec)
sys.modules["adr_tool"] = adr   # dataclass가 모듈을 찾을 수 있게
_spec.loader.exec_module(adr)

BODY = """
## 배경

배경 내용

## 결정

결정 내용

## 근거

근거 내용

## 검토한 대안

- 대안

## 결과와 영향

결과 내용
"""


def write_adr(d: Path, num: int, slug: str, **meta) -> Path:
    fields = {
        "id": f"ADR-{num:04d}", "title": f"결정 {num}", "status": "accepted", "date": "2026-10-01",
        "deciders": "[양승준]", "sprint": "S4", "area": "risk", "jira": "[ZP-1]", "tags": "[]",
        "supersedes": "[]", "superseded_by": "[]", "sources": "[]",
    }
    fields.update(meta)
    head = "\n".join(f"{k}: {v}" for k, v in fields.items())
    path = d / f"{num:04d}-{slug}.md"
    path.write_text(f"---\n{head}\n---\n# ADR-{num:04d}. {fields['title']}\n{BODY}", encoding="utf-8")
    return path


@pytest.fixture
def adr_dir(tmp_path: Path) -> Path:
    d = tmp_path / "docs" / "adr"
    d.mkdir(parents=True)
    shutil.copy(ROOT / "docs" / "adr" / "template.md", d / "template.md")
    return d


def test_repository_adrs_pass_lint():
    assert adr.lint() == []


def test_repository_outputs_build():
    adrs, errors = adr.load_all(adr.ADR_DIR)
    assert not errors
    out = adr.build_outputs(adrs)
    data = json.loads(out["index.json"])
    assert data["count"] == len(adrs) >= 19
    assert [a["number"] for a in data["adrs"]] == sorted(a["number"] for a in data["adrs"])
    # 대체된 결정은 AI 문맥 파일에서 본문 없이 한 줄로만 나온다
    assert "### ADR-0002." not in out["ADR_CONTEXT.md"]
    assert "- ADR-0002." in out["ADR_CONTEXT.md"]
    assert adr.build_outputs(adrs) == out   # 같은 입력이면 같은 출력


def test_new_uses_next_number(adr_dir: Path):
    write_adr(adr_dir, 1, "first")
    write_adr(adr_dir, 7, "seventh")
    path = adr.cmd_new(adr_dir, "새 결정", "new-decision", ["이유진"], "data",
                       sprint="S5", jira=["ZP-40"], on="2026-11-03")
    assert path.name == "0008-new-decision.md"
    a = adr.read_adr(path)
    assert a.get("id") == "ADR-0008"
    assert a.get("status") == "proposed"
    assert a.get("deciders") == ["이유진"]
    assert a.get("jira") == ["ZP-40"]
    assert a.title_line == "ADR-0008. 새 결정"
    assert adr.lint(adr_dir, adr_dir.parent.parent) == []


def test_new_rejects_non_ascii_slug(adr_dir: Path):
    with pytest.raises(adr.AdrError):
        adr.cmd_new(adr_dir, "제목", "한글-이름", ["양승준"], "risk")


def test_lint_finds_duplicate_number_and_missing_section(adr_dir: Path):
    write_adr(adr_dir, 3, "a")
    write_adr(adr_dir, 3, "b")
    p = write_adr(adr_dir, 4, "c")
    p.write_text(p.read_text(encoding="utf-8").replace("## 근거", "## 메모"), encoding="utf-8")
    errors = adr.lint(adr_dir, adr_dir.parent.parent)
    assert any("겹칩니다" in e for e in errors)
    assert any("'## 근거' 절이 없습니다" in e for e in errors)
    assert any("알 수 없는 절" in e for e in errors)


def test_lint_checks_status_area_jira_and_sources(adr_dir: Path):
    write_adr(adr_dir, 1, "a", status="done", area="misc", jira="[zp1]", sources="[docs/none.md, ext:외부문서]")
    errors = adr.lint(adr_dir, adr_dir.parent.parent)
    assert any("status는" in e for e in errors)
    assert any("area는" in e for e in errors)
    assert any("Jira 키" in e for e in errors)
    assert any("docs/none.md" in e for e in errors)
    assert not any("외부문서" in e for e in errors)


def test_supersede_updates_both_sides(adr_dir: Path):
    write_adr(adr_dir, 1, "old", date="2026-09-01")
    write_adr(adr_dir, 2, "new", date="2026-10-01")
    errors = adr.lint(adr_dir, adr_dir.parent.parent)
    assert errors == []
    adr.cmd_supersede(adr_dir, "1", "ADR-0002")
    old = adr.read_adr(adr_dir / "0001-old.md")
    new = adr.read_adr(adr_dir / "0002-new.md")
    assert old.get("status") == "superseded"
    assert old.get("superseded_by") == ["ADR-0002"]
    assert new.get("supersedes") == ["ADR-0001"]
    assert adr.lint(adr_dir, adr_dir.parent.parent) == []


def test_lint_requires_both_sides_of_supersede(adr_dir: Path):
    write_adr(adr_dir, 1, "old", date="2026-09-01")
    write_adr(adr_dir, 2, "new", supersedes="[ADR-0001]")
    errors = adr.lint(adr_dir, adr_dir.parent.parent)
    assert any("superseded_by에 ADR-0002가 없습니다" in e for e in errors)


def test_index_writes_files_and_check_reports_stale(adr_dir: Path):
    write_adr(adr_dir, 1, "a")
    assert adr.cmd_index(adr_dir, check=True) == ["README.md", "index.json", "ADR_CONTEXT.md"]
    adr.cmd_index(adr_dir, check=False)
    assert adr.cmd_index(adr_dir, check=True) == []
    write_adr(adr_dir, 2, "b")
    assert "index.json" in adr.cmd_index(adr_dir, check=True)
