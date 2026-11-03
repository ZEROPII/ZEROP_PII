"""기록된 실행 폴더를 정한 코드로 다시 처리해 새 폴더에 쓴다 (LLM 0).

대상 AI 답과 LLM 추출 결과는 기록 그대로 쓰고, 그 뒤 단계만 다시 한다. 새 폴더는 frozen/extract_eval_v4.py로 그대로 채점한다.
  --code v2 (기본) : 추출 바로잡기(obs_fix) → 규칙 추출(rule_extract, 나열 귀속 포함) → 정규화 v2 (지금 코드)
  --code v1        : 나열 귀속 관찰을 빼고 묶음 정규화(normalize_bridge v0.11.1) 그대로 (정규화 v2 · 추출 바로잡기 이전 코드)
                     v2로 돌린 기록이면 실행 때 이미 적용된 추출 바로잡기(fixed_from이 붙은 관찰)는 되돌리지 않는다
같은 기록을 두 코드로 처리해 채점하면, 답변이 같은 상태에서 코드 차이만 비교할 수 있다.

사용: 저장소 루트에서
  python medical/scoring/reprocess.py runs/medical/holdout_2 runs/medical/h2_v1 --code v1
  python medical/scoring/frozen/extract_eval_v4.py runs/medical/h2_v1 medical/scoring/frozen/extractor_recall.py --exclude medical/scoring/patients/before_holdout_2.json
"""
import argparse
import json
import shutil
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, '.')
from medical.config import MedicalPaths
from medical.normalize_ext import make_normalizer
from medical.obs_fix import fix_observations
from medical.rule_extract import rule_observations
from medical.tracking import view_of


def _p(run: Path, name: str) -> Path:
    for n in (unicodedata.normalize('NFC', name), unicodedata.normalize('NFD', name)):
        if (run / n).exists():
            return run / n
    return run / name


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--code', choices=['v1', 'v2'], default='v2')
    a = ap.parse_args()
    src, dst = Path(a.src), Path(a.dst)
    dst.mkdir(parents=True, exist_ok=True)
    for name in ('사실표.csv', 'trial요약.json', 'run_meta.json', 'llm_usage.jsonl', '코호트분리.csv'):
        if _p(src, name).exists():
            shutil.copy2(_p(src, name), dst / name)
    nz = make_normalizer(MedicalPaths(), a.code)
    n_fixed = n_rule = n_drop = 0
    with open(_p(src, '턴기록.jsonl'), encoding='utf-8') as fi, open(dst / '턴기록.jsonl', 'w', encoding='utf-8') as fo:
        for line in fi:
            r = json.loads(line)
            if r.get('raw_response_text') and r.get('arm') == 'C0':
                resp, query = r['raw_response_text'], r.get('query_text') or ''
                obs = [o for o in (r.get('raw_observations') or []) if isinstance(o, dict)]
                if a.code == 'v2':
                    obs = fix_observations(obs)
                    n_fixed += sum(1 for o in obs if o.get('fixed_from'))
                    extra = rule_observations(resp, query, obs, nz=nz)
                    n_rule += len(extra)
                    obs += extra
                else:
                    kept = [o for o in obs if o.get('rule') != 'LIST_ATTRIBUTION']
                    n_drop += len(obs) - len(kept)
                    obs = kept
                v = view_of(obs, resp, query, nz)
                r['raw_observations'] = obs
                r['cases'] = {ref: dict((r.get('cases') or {}).get(ref, {}), normalized=norm) for ref, norm in v.normalized.items()}
            fo.write(json.dumps(r, ensure_ascii=False) + '\n')
    if a.code == 'v2':
        print(f'다시 처리 (v2): {dst}  (종류 바로잡기 {n_fixed}개, 새 규칙 관찰 {n_rule}개)')
    else:
        print(f'다시 처리 (v1): {dst}  (나열 귀속 관찰 {n_drop}개 뺌)')


if __name__ == '__main__':
    main()
