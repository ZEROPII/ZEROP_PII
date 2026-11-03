#!/usr/bin/env python3
"""ADR(Architecture Decision Record) 도구.

docs/adr/NNNN-<slug>.md 파일 하나가 결정 하나다. 이 스크립트는 그 파일들을 읽어서
번호를 매기고, 형식을 검사하고, 사람용 색인과 AI용 문맥 파일을 만든다.

    python scripts/adr.py new "제목" --slug short-name --deciders 이유진,양승준 \\
        --area risk --sprint S5 --jira ZP-28 --tags medical,kcalc
    python scripts/adr.py supersede 0002 --by 0007   # 대체 관계를 양쪽 파일에 적는다
    python scripts/adr.py lint                        # 형식 검사 (PR에서 실행)
    python scripts/adr.py index                       # README.md · index.json · ADR_CONTEXT.md 생성
    python scripts/adr.py index --check               # 생성 파일이 최신인지만 확인

표준 라이브러리만 쓴다. 생성 파일에는 실행 시각을 넣지 않아서 같은 ADR이면 항상 같은 결과가 나온다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADR_DIR = ROOT / "docs" / "adr"

FILE_RE = re.compile(r"^(\d{4})-([a-z0-9][a-z0-9-]*)\.md$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
JIRA_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
SPRINT_RE = re.compile(r"^S\d+$")
ID_RE = re.compile(r"^ADR-(\d{4})$")

STATUS = {
    "proposed": "제안",
    "accepted": "승인",
    "superseded": "대체됨",
    "deprecated": "폐기",
    "rejected": "기각",
}
AREAS = {
    "process": "운영·협업",
    "risk": "위험 측정·방어",
    "extraction": "단서 추출·정규화",
    "fuzzer": "공격 질문 생성",
    "data": "데이터·적용처",
    "experiment": "실험·검증",
    "system": "시스템·화면",
}
SECTIONS = ["배경", "결정", "근거", "검토한 대안", "결과와 영향"]
OPTIONAL_SECTIONS = ["남은 일"]
FIELD_ORDER = ["id", "title", "status", "date", "deciders", "sprint", "area",
               "jira", "tags", "supersedes", "superseded_by", "sources"]
LIST_FIELDS = {"deciders", "jira", "tags", "supersedes", "superseded_by", "sources"}
REQUIRED = ["id", "title", "status", "date", "deciders", "area"]
GENERATED = ("README.md", "index.json", "ADR_CONTEXT.md")


class AdrError(Exception):
    pass


@dataclass
class Adr:
    path: Path
    number: int
    slug: str
    meta: dict
    title_line: str
    sections: dict[str, str] = field(default_factory=dict)
    section_order: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"ADR-{self.number:04d}"

    def get(self, key: str):
        return self.meta.get(key, [] if key in LIST_FIELDS else "")


# ── 읽기 ──────────────────────────────────────────────────────────────

def split_front_matter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        raise AdrError("첫 줄이 '---'가 아닙니다 (앞머리 없음)")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise AdrError("앞머리를 닫는 '---'가 없습니다")
    return text[4:end], text[end + 5:]


def parse_value(key: str, raw: str):
    raw = raw.strip()
    if key in LIST_FIELDS:
        if not (raw.startswith("[") and raw.endswith("]")):
            raise AdrError(f"'{key}'는 [a, b] 형식의 목록이어야 합니다")
        inner = raw[1:-1].strip()
        return [v.strip().strip('"').strip("'") for v in inner.split(",") if v.strip()] if inner else []
    return raw.strip('"').strip("'")


def parse_front_matter(block: str) -> dict:
    meta: dict = {}
    for n, line in enumerate(block.splitlines(), start=2):
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise AdrError(f"{n}행: 'key: value' 형식이 아닙니다")
        key = key.strip()
        if key not in FIELD_ORDER:
            raise AdrError(f"{n}행: 모르는 필드 '{key}'")
        meta[key] = parse_value(key, value)
    return meta


def parse_body(body: str) -> tuple[str, dict[str, str], list[str]]:
    title_line = ""
    sections: dict[str, str] = {}
    order: list[str] = []
    current = None
    buf: list[str] = []
    for line in body.splitlines():
        if line.startswith("# ") and not title_line and current is None:
            title_line = line[2:].strip()
            continue
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = re.sub(r"\s*\(.*\)\s*$", "", line[3:].strip())
            order.append(current)
            buf = []
            continue
        if current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return title_line, sections, order


def read_adr(path: Path) -> Adr:
    m = FILE_RE.match(path.name)
    if not m:
        raise AdrError("파일 이름이 'NNNN-slug.md' 형식이 아닙니다")
    block, body = split_front_matter(path.read_text(encoding="utf-8"))
    meta = parse_front_matter(block)
    title_line, sections, order = parse_body(body)
    return Adr(path=path, number=int(m.group(1)), slug=m.group(2), meta=meta,
               title_line=title_line, sections=sections, section_order=order)


def adr_files(adr_dir: Path) -> list[Path]:
    return sorted(p for p in adr_dir.glob("*.md") if FILE_RE.match(p.name))


def load_all(adr_dir: Path) -> tuple[list[Adr], list[str]]:
    adrs, errors = [], []
    for p in adr_files(adr_dir):
        try:
            adrs.append(read_adr(p))
        except AdrError as e:
            errors.append(f"{p.name}: {e}")
    return adrs, errors


# ── 검사 ──────────────────────────────────────────────────────────────

def lint(adr_dir: Path = ADR_DIR, root: Path = ROOT) -> list[str]:
    adrs, errors = load_all(adr_dir)
    by_id: dict[str, Adr] = {}
    for a in adrs:
        where = a.path.name
        if a.id in by_id:
            errors.append(f"{where}: 번호 {a.number:04d}가 {by_id[a.id].path.name}와 겹칩니다")
            continue
        by_id[a.id] = a
        for key in REQUIRED:
            if not a.get(key):
                errors.append(f"{where}: 필수 필드 '{key}'가 비어 있습니다")
        if a.get("id") and a.get("id") != a.id:
            errors.append(f"{where}: id '{a.get('id')}'가 파일 번호({a.id})와 다릅니다")
        if a.get("status") and a.get("status") not in STATUS:
            errors.append(f"{where}: status는 {', '.join(STATUS)} 중 하나여야 합니다")
        if a.get("area") and a.get("area") not in AREAS:
            errors.append(f"{where}: area는 {', '.join(AREAS)} 중 하나여야 합니다")
        if a.get("sprint") and not SPRINT_RE.match(a.get("sprint")):
            errors.append(f"{where}: sprint는 S0, S1 … 형식이어야 합니다")
        try:
            date.fromisoformat(a.get("date"))
        except ValueError:
            errors.append(f"{where}: date '{a.get('date')}'는 YYYY-MM-DD 형식이어야 합니다")
        for key in a.get("jira"):
            if not JIRA_RE.match(key):
                errors.append(f"{where}: Jira 키 '{key}' 형식이 맞지 않습니다 (예: ZP-28)")
        if not a.title_line.startswith(f"{a.id}."):
            errors.append(f"{where}: 제목 줄은 '# {a.id}. 제목'으로 시작해야 합니다")
        for s in SECTIONS:
            if s not in a.sections:
                errors.append(f"{where}: '## {s}' 절이 없습니다")
            elif not a.sections[s]:
                errors.append(f"{where}: '## {s}' 절이 비어 있습니다")
        for s in a.section_order:
            if s not in SECTIONS and s not in OPTIONAL_SECTIONS:
                errors.append(f"{where}: 알 수 없는 절 '## {s}' ({', '.join(SECTIONS + OPTIONAL_SECTIONS)})")
        for src in a.get("sources"):
            if src.startswith("ext:"):
                continue
            target = root / src.split("#", 1)[0]
            if not target.exists():
                errors.append(f"{where}: 근거 경로 '{src}'가 저장소에 없습니다 (외부 문서는 'ext:'로 시작)")
    # 대체 관계: 양쪽에 모두 적혀 있어야 하고, 대체된 결정은 상태가 superseded
    for a in by_id.values():
        where = a.path.name
        for ref_key, back_key in (("supersedes", "superseded_by"), ("superseded_by", "supersedes")):
            for ref in a.get(ref_key):
                other = by_id.get(ref)
                if other is None:
                    errors.append(f"{where}: {ref_key}의 '{ref}'가 없습니다")
                elif a.id not in other.get(back_key):
                    errors.append(f"{where}: {ref}의 {back_key}에 {a.id}가 없습니다 (supersede 명령으로 맞추세요)")
        if a.get("status") == "superseded" and not a.get("superseded_by"):
            errors.append(f"{where}: status가 superseded이면 superseded_by가 있어야 합니다")
        if a.get("superseded_by") and a.get("status") != "superseded":
            errors.append(f"{where}: superseded_by가 있으면 status는 superseded여야 합니다")
        for ref in a.get("supersedes"):
            other = by_id.get(ref)
            if other and other.get("date") > a.get("date"):
                errors.append(f"{where}: 대체하는 결정({a.get('date')})이 대체되는 {ref}({other.get('date')})보다 이릅니다")
    return errors


# ── 생성 ──────────────────────────────────────────────────────────────

def first_paragraphs(text: str, limit: int = 400) -> str:
    out = " ".join(line.strip() for line in text.splitlines() if line.strip() and not line.startswith("|"))
    out = re.sub(r"\s+", " ", out)
    return out if len(out) <= limit else out[: limit - 1].rstrip() + "…"


def to_record(a: Adr) -> dict:
    rec = {
        "id": a.id,
        "number": a.number,
        "title": a.get("title"),
        "status": a.get("status"),
        "status_ko": STATUS.get(a.get("status"), ""),
        "date": a.get("date"),
        "deciders": a.get("deciders"),
        "sprint": a.get("sprint"),
        "area": a.get("area"),
        "area_ko": AREAS.get(a.get("area"), ""),
        "jira": a.get("jira"),
        "tags": a.get("tags"),
        "supersedes": a.get("supersedes"),
        "superseded_by": a.get("superseded_by"),
        "sources": a.get("sources"),
        "file": f"docs/adr/{a.path.name}",
        "summary": first_paragraphs(a.sections.get("결정", "")),
        "sections": {k: a.sections[k] for k in SECTIONS + OPTIONAL_SECTIONS if k in a.sections},
    }
    return rec


def count_by(adrs: list[Adr], key: str, labels: dict | None = None) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for a in adrs:
        k = a.get(key) or "-"
        counts[k] = counts.get(k, 0) + 1
    keys = list(labels) if labels else sorted(counts)
    return [(k, counts[k]) for k in keys if k in counts]


def md_escape(s: str) -> str:
    return s.replace("|", "\\|")


def mermaid_label(s: str, limit: int | None = None) -> str:
    s = s.replace('"', "'").replace(":", "·").replace("<", "＜").replace(">", "＞")
    if limit and len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    return s


def build_readme(adrs: list[Adr]) -> str:
    total = len(adrs)
    lines = [
        "# 의사결정 기록 (ADR)",
        "",
        "> 이 파일은 `python scripts/adr.py index`가 만든다. 표를 직접 고치지 말고 ADR 파일을 고친다.",
        "> 병합되면 GitHub Actions가 다시 만들어 커밋한다.",
        "",
        "아키텍처 · 기술 선택 · 실험 기준 · 트러블슈팅 중에서 나중에 \"왜 이렇게 했지?\"를 다시 찾게 될 결정을 한 건씩 남긴다.",
        "형식과 운영 규칙은 [ADR-0003](0003-record-decisions-as-adr.md), 자동화는 [ADR-0019](0019-automate-adr-index-and-ai-context.md)에 있다.",
        "",
        "## 쓰는 법",
        "",
        "```bash",
        "python scripts/adr.py new \"제목\" --slug short-name --deciders 이름 --area risk --sprint S5 --jira ZP-00",
        "python scripts/adr.py supersede 0002 --by 0007   # 결정을 뒤집을 때: 새 ADR을 쓰고 옛 ADR은 '대체됨'",
        "python scripts/adr.py lint                        # PR 전에 형식 검사",
        "python scripts/adr.py index                       # 이 색인과 AI용 파일을 다시 만듦 (선택)",
        "```",
        "",
        "- 결정 하나에 파일 하나. 이미 승인된 ADR의 결정 내용은 고치지 않고 새 ADR로 대체한다.",
        "- PR 설명에 ADR 번호를, Jira 스토리에는 ADR 번호와 링크를 남긴다.",
        "- 외부 문서 근거는 `sources`에 `ext:`로 적는다. 저장소 경로는 lint가 존재 여부를 확인한다.",
        "",
        "## 현황",
        "",
        f"전체 {total}건.",
        "",
        "| 상태 | 건수 |",
        "| --- | ---: |",
    ]
    lines += [f"| {STATUS[k]} | {n} |" for k, n in count_by(adrs, "status", STATUS)]
    lines += ["", "| 영역 | 건수 |", "| --- | ---: |"]
    lines += [f"| {AREAS[k]} | {n} |" for k, n in count_by(adrs, "area", AREAS)]
    lines += ["", "| 스프린트 | 건수 |", "| --- | ---: |"]
    lines += [f"| {k} | {n} |" for k, n in count_by(adrs, "sprint")]
    lines += [
        "",
        "## 목록",
        "",
        "| 번호 | 제목 | 상태 | 날짜 | 결정 | 스프린트 | 영역 | Jira |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for a in adrs:
        status = STATUS.get(a.get("status"), a.get("status"))
        if a.get("superseded_by"):
            status += " → " + ", ".join(a.get("superseded_by"))
        lines.append(
            f"| [{a.id}]({a.path.name}) | {md_escape(a.get('title'))} | {status} | {a.get('date')} | "
            f"{', '.join(a.get('deciders'))} | {a.get('sprint') or '-'} | {AREAS.get(a.get('area'), '-')} | "
            f"{', '.join(a.get('jira')) or '-'} |"
        )
    edges = [(a, ref) for a in adrs for ref in a.get("supersedes")]
    by_id = {a.id: a for a in adrs}
    if edges:
        lines += ["", "## 대체 관계", "", "```mermaid", "flowchart LR"]
        for a, ref in edges:
            old = by_id[ref]
            lines.append(
                f'  A{old.number:04d}["{old.id} {mermaid_label(old.get("title"))}"] -->|대체| '
                f'A{a.number:04d}["{a.id} {mermaid_label(a.get("title"))}"]'
            )
        lines.append("```")
    sprints = sorted({a.get("sprint") for a in adrs if a.get("sprint")})
    if sprints:
        lines += ["", "## 스프린트별 결정", "", "```mermaid", "timeline"]
        for s in sprints:
            items = [f"{a.id} {mermaid_label(a.get('title'), 18)}" for a in adrs if a.get("sprint") == s]
            lines.append(f"  {s} : " + " : ".join(items))
        lines.append("```")
    lines += [
        "",
        "## AI 도구에서 쓰기",
        "",
        "- [`ADR_CONTEXT.md`](ADR_CONTEXT.md): 유효한 결정은 본문을, 대체된 결정은 한 줄만 담은 요약. AI 대화나 프로젝트 지식에 이 파일 하나를 붙이면 된다.",
        "- [`index.json`](index.json): ADR마다 필드와 절을 나눈 구조화 데이터. 검색(RAG)용으로 ADR 단위로 잘라 넣을 수 있다.",
        "- 두 파일 모두 이 폴더의 ADR에서 만들어지므로 사람이 읽는 내용과 AI가 읽는 내용이 같다.",
        "",
    ]
    return "\n".join(lines)


def build_context(adrs: list[Adr]) -> str:
    active = [a for a in adrs if a.get("status") in ("accepted", "proposed")]
    inactive = [a for a in adrs if a.get("status") not in ("accepted", "proposed")]
    last = max((a.get("date") for a in adrs), default="-")
    lines = [
        "# Zero PII 의사결정 요약 (AI · 새 팀원용)",
        "",
        "> 이 파일은 `python scripts/adr.py index`가 `docs/adr/*.md`에서 만든다. 직접 고치지 않는다.",
        f"> ADR {len(adrs)}건 (유효 {len(active)} · 대체·폐기 {len(inactive)}), 마지막 결정일 {last}.",
        "",
        "## 읽는 법",
        "",
        "- '유효한 결정'이 지금 코드와 실험이 따르는 기준이다. 코드를 바꾸거나 제안할 때 이 결정과 어긋나면, 바꾸기 전에 새 ADR이 필요하다고 먼저 알린다.",
        "- '제안' 상태는 아직 확정되지 않은 결정이다.",
        "- '대체·폐기된 결정'은 이력이다. 따르지 않는다.",
        "- 근거 경로는 저장소 기준이다. `ext:`는 저장소 밖 문서다.",
        "",
        "## 유효한 결정",
    ]
    for a in active:
        meta = [STATUS[a.get("status")], a.get("date"), "결정 " + ", ".join(a.get("deciders"))]
        if a.get("sprint"):
            meta.append(a.get("sprint"))
        if a.get("jira"):
            meta.append("Jira " + ", ".join(a.get("jira")))
        meta.append(AREAS.get(a.get("area"), ""))
        lines += ["", f"### {a.id}. {a.get('title')}", "", "- " + " · ".join(meta)]
        if a.get("supersedes"):
            lines.append("- 대체한 결정: " + ", ".join(a.get("supersedes")))
        if a.get("sources"):
            lines.append("- 근거: " + ", ".join(f"`{s}`" for s in a.get("sources")))
        lines += ["", "**결정**", "", a.sections.get("결정", "")]
        lines += ["", "**결과와 영향**", "", a.sections.get("결과와 영향", "")]
    if inactive:
        lines += ["", "## 대체 · 폐기된 결정", ""]
        for a in inactive:
            to = (" → " + ", ".join(a.get("superseded_by"))) if a.get("superseded_by") else ""
            lines.append(f"- {a.id}. {a.get('title')} ({a.get('date')}, {STATUS[a.get('status')]}{to})")
    todo = [(a, a.sections["남은 일"]) for a in active if a.sections.get("남은 일")]
    if todo:
        lines += ["", "## 남은 일", ""]
        for a, text in todo:
            lines += [f"**{a.id}**", "", text, ""]
    return "\n".join(lines).rstrip() + "\n"


def build_index_json(adrs: list[Adr]) -> str:
    data = {
        "generated_by": "scripts/adr.py",
        "count": len(adrs),
        "status_labels": STATUS,
        "area_labels": AREAS,
        "adrs": [to_record(a) for a in adrs],
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def build_outputs(adrs: list[Adr]) -> dict[str, str]:
    adrs = sorted(adrs, key=lambda a: a.number)
    return {
        "README.md": build_readme(adrs),
        "index.json": build_index_json(adrs),
        "ADR_CONTEXT.md": build_context(adrs),
    }


# ── 쓰기 ──────────────────────────────────────────────────────────────

def format_value(key: str, value) -> str:
    if key in LIST_FIELDS:
        return "[" + ", ".join(value) + "]"
    return str(value)


def set_field(text: str, key: str, value) -> str:
    block, body = split_front_matter(text)
    new_line = f"{key}: {format_value(key, value)}"
    pattern = re.compile(rf"^{re.escape(key)}:.*$", re.M)
    if pattern.search(block):
        block = pattern.sub(lambda _m: new_line, block, count=1)
    else:
        block = block.rstrip("\n") + "\n" + new_line
    return f"---\n{block}\n---\n{body}"


def next_number(adr_dir: Path) -> int:
    nums = [int(FILE_RE.match(p.name).group(1)) for p in adr_files(adr_dir)]
    return max(nums, default=0) + 1


def split_csv(s: str | None) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def cmd_new(adr_dir: Path, title: str, slug: str, deciders: list[str], area: str,
            sprint: str = "", jira: list[str] | None = None, tags: list[str] | None = None,
            status: str = "proposed", on: str | None = None) -> Path:
    if not SLUG_RE.match(slug):
        raise AdrError("slug는 영문 소문자 · 숫자 · '-'만 씁니다 (예: event-level-kcalc)")
    if area not in AREAS:
        raise AdrError(f"area는 {', '.join(AREAS)} 중 하나")
    if status not in STATUS:
        raise AdrError(f"status는 {', '.join(STATUS)} 중 하나")
    template = (adr_dir / "template.md").read_text(encoding="utf-8")
    n = next_number(adr_dir)
    values = {
        "id": f"ADR-{n:04d}", "title": title, "status": status, "date": on or date.today().isoformat(),
        "deciders": deciders, "sprint": sprint, "area": area, "jira": jira or [], "tags": tags or [],
        "supersedes": [], "superseded_by": [], "sources": [],
    }
    text = template
    for key, value in values.items():
        text = set_field(text, key, value)
    text = text.replace("{{ID}}", values["id"]).replace("{{TITLE}}", title)
    path = adr_dir / f"{n:04d}-{slug}.md"
    path.write_text(text, encoding="utf-8")
    return path


def find_by_number(adr_dir: Path, num: str) -> Path:
    num = num.replace("ADR-", "").zfill(4)
    hits = [p for p in adr_files(adr_dir) if p.name.startswith(num + "-")]
    if len(hits) != 1:
        raise AdrError(f"{num}번 ADR을 하나로 찾지 못했습니다 ({len(hits)}건)")
    return hits[0]


def cmd_supersede(adr_dir: Path, old: str, new: str) -> None:
    old_p, new_p = find_by_number(adr_dir, old), find_by_number(adr_dir, new)
    old_a, new_a = read_adr(old_p), read_adr(new_p)
    old_text = old_p.read_text(encoding="utf-8")
    old_text = set_field(old_text, "status", "superseded")
    old_text = set_field(old_text, "superseded_by", sorted(set(old_a.get("superseded_by")) | {new_a.id}))
    new_text = new_p.read_text(encoding="utf-8")
    new_text = set_field(new_text, "supersedes", sorted(set(new_a.get("supersedes")) | {old_a.id}))
    old_p.write_text(old_text, encoding="utf-8")
    new_p.write_text(new_text, encoding="utf-8")


def cmd_index(adr_dir: Path, check: bool) -> list[str]:
    adrs, errors = load_all(adr_dir)
    if errors:
        raise AdrError("읽지 못한 ADR이 있습니다. 먼저 lint를 확인하세요:\n" + "\n".join(errors))
    stale = []
    for name, content in build_outputs(adrs).items():
        path = adr_dir / name
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != content:
            stale.append(name)
            if not check:
                path.write_text(content, encoding="utf-8")
    return stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ADR 도구 (docs/adr)")
    parser.add_argument("--dir", type=Path, default=ADR_DIR, help="ADR 폴더 (기본 docs/adr)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new", help="다음 번호로 ADR 초안을 만든다")
    p_new.add_argument("title")
    p_new.add_argument("--slug", required=True, help="파일 이름에 쓸 영문 이름 (예: event-level-kcalc)")
    p_new.add_argument("--deciders", required=True, help="쉼표로 구분")
    p_new.add_argument("--area", required=True, choices=list(AREAS))
    p_new.add_argument("--sprint", default="")
    p_new.add_argument("--jira", default="", help="쉼표로 구분 (예: ZP-28,ZP-29)")
    p_new.add_argument("--tags", default="")
    p_new.add_argument("--status", default="proposed", choices=list(STATUS))
    p_new.add_argument("--date", default=None, help="결정 날짜 (기본 오늘)")

    p_sup = sub.add_parser("supersede", help="OLD를 NEW가 대체했다고 양쪽 파일에 적는다")
    p_sup.add_argument("old")
    p_sup.add_argument("--by", required=True)

    sub.add_parser("lint", help="형식 · 번호 · 상태 · 대체 관계 · 근거 경로 검사")

    p_idx = sub.add_parser("index", help="README.md · index.json · ADR_CONTEXT.md 생성")
    p_idx.add_argument("--check", action="store_true", help="쓰지 않고 최신인지만 확인")

    args = parser.parse_args(argv)
    adr_dir: Path = args.dir
    try:
        if args.cmd == "new":
            path = cmd_new(adr_dir, args.title, args.slug, split_csv(args.deciders), args.area,
                           args.sprint, split_csv(args.jira), split_csv(args.tags), args.status, args.date)
            print(f"만들었습니다: {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}")
            print("배경 · 결정 · 근거 · 검토한 대안 · 결과와 영향을 채운 뒤 PR을 올리세요.")
            return 0
        if args.cmd == "supersede":
            cmd_supersede(adr_dir, args.old, args.by)
            print(f"{args.old} → {args.by} 대체 관계를 적었습니다.")
            return 0
        if args.cmd == "lint":
            root = ROOT if adr_dir.resolve() == ADR_DIR.resolve() else adr_dir.parent.parent
            errors = lint(adr_dir, root)
            n = len(adr_files(adr_dir))
            if errors:
                print(f"ADR {n}건 중 문제 {len(errors)}개:")
                for e in errors:
                    print("  - " + e)
                return 1
            print(f"ADR {n}건 형식 검사 통과")
            return 0
        if args.cmd == "index":
            stale = cmd_index(adr_dir, args.check)
            if args.check:
                if stale:
                    print("최신이 아닌 생성 파일: " + ", ".join(stale))
                    print("python scripts/adr.py index 를 실행하세요.")
                    return 1
                print("생성 파일이 최신입니다")
                return 0
            print(("다시 만든 파일: " + ", ".join(stale)) if stale else "바뀐 것이 없습니다")
            return 0
    except AdrError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
