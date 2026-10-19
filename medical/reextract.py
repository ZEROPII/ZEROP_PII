# 기록된 원 응답에 지금의 추출기 프롬프트만 다시 적용해 본다 (대상 AI·변형기 호출 0, 추출기만 응답 수만큼)
#
# 용도: 추출기 프롬프트·출력 길이를 고친 뒤, 실행 전체를 다시 돌리지 않고 같은 답변에서 사례·단서를 제대로 뽑는지 확인한다.
# 갈래 간에 같은 원 응답(턴 0 공유)은 한 번만 다시 추출한다. 결과는 <실행 폴더>/reextract.jsonl.
# 원래 실행 기록(턴기록·trial요약)은 고치지 않는다.

from __future__ import annotations

import collections
import glob
import json
import unicodedata
from pathlib import Path

from medical.bundle.normalize_bridge import Normalizer
from medical.config import MedicalPaths
from medical.prompts import PROMPTS
from medical.tracking import parse_json, view_of


def _find(run_dir: Path, stem: str) -> Path:
    for f in run_dir.iterdir():
        if unicodedata.normalize("NFC", f.name) == stem:
            return f
    raise FileNotFoundError(stem)


def reextract(run_dir: Path, limit: int = 4, model: str | None = None) -> list[dict]:
    from core.config import get_settings
    from core.llm_client import LLMClient
    from medical.llm import ClientRoleLLM
    import dataclasses
    st = get_settings()
    st = dataclasses.replace(st, llm_timeout_sec=max(st.llm_timeout_sec, 180.0))
    llm = ClientRoleLLM(LLMClient(st), models={"extractor": model} if model else {})
    paths = MedicalPaths()
    nz = Normalizer(paths.nodes, paths.alias)
    seen, out = set(), []
    for line in open(_find(run_dir, "턴기록.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        raw = r.get("raw_response_text")
        if not raw or raw in seen:
            continue
        seen.add(raw)
        prompt = PROMPTS["extractor"].format(cases="[]",
                                             query=r["query_text"], response=raw)
        text = llm.complete("extractor", prompt, [])
        obs = parse_json(text, "array")
        v = view_of([o for o in (obs or []) if isinstance(o, dict)], raw, r["query_text"], nz)
        status = collections.Counter(o["mapping_status"] for os_ in v.normalized.values() for o in os_)
        rec = dict(trial_id=r["trial_id"], turn=r.get("turn"), parsed=obs is not None, n_obs=len(obs or []),
                   cases=v.case_refs, status=dict(status),
                   unmapped=[o["raw_value"] for os_ in v.normalized.values() for o in os_ if o["mapping_status"] == "UNMAPPED"][:15],
                   old_n_obs=len(r.get("raw_observations") or []), old_ok=r.get("extraction_ok"))
        out.append(rec)
        print(f"{rec['trial_id']} 턴{rec['turn']}: 예전 관측 {rec['old_n_obs']}개(ok={rec['old_ok']}) → 지금 {rec['n_obs']}개 "
              f"(JSON {'정상' if rec['parsed'] else '실패'}), 사례 {rec['cases']}, 상태 {rec['status']}")
        if rec["unmapped"]:
            print(f"   UNMAPPED 예: {rec['unmapped']}")
        if len(out) >= limit:
            break
    with open(run_dir / "reextract.jsonl", "w", encoding="utf-8") as f:
        for rec in out:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    toks = sum((u.get("input_tokens") or 0) + (u.get("output_tokens") or 0) for u in llm.usage)
    print(f"추출기 호출 {len(llm.usage)}회, 토큰 합계 약 {toks}")
    return out
