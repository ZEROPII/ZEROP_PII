"""고정본 채점(frozen/extract_eval_v4.py)과 같은 정답 · 평가 대상으로, 틀린 곳을 나눠 본다 (LLM 0).

  1. trial별 재현율과 확정 재현율 (몇 trial에 몰렸는지)
  2. 놓친 단서의 종류 (아예 안 뽑음 · 다른 사례에 붙임 · 다른 종류로 뽑음 · 같은 종류 다른 값만 · 그 사례에서 뽑은 것 없음)
     '서로 다른 표현' 수도 함께 낸다. 같은 날짜가 여러 사실에 걸리면 채점에서는 여러 개로 세기 때문이다.
  3. 놓친 날짜가 나온 줄 (표 줄인지, 날짜 앞에 사건 낱말이 있는지)
  4. 확정 값 정밀도를 출처별로 (LLM · 규칙 추출 · 나열 귀속, 정규화 방식별)
  5. 확정하지 못한 관찰의 이유

frozen/extract_eval_v4.py를 고치지 않고, 그 파일의 앞부분(데이터 적재 · 정답 · 평가 trial 정하기)을 그대로 불러 쓴다.
보류 검증 기록에서 이 결과를 보고 규칙을 고치면 그 기록은 개발 기록이 된다. 고친 규칙은 새 기록으로 다시 재야 한다.

사용: 저장소 루트에서
  PYTHONHASHSEED=0 python medical/scoring/miss_breakdown.py runs/medical/holdout_2 --exclude medical/scoring/patients/before_holdout_2.json
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FROZEN = HERE / 'frozen'
ROLEW = re.compile(r'관리\s*계획|care\s*plan|계획|처방|약물|복용|투약|시술|수술|생검|시행|진단|진료|내원|방문|입원', re.I)


def load_frozen(run: str, exclude: str | None) -> dict:
    sys.argv = ['extract_eval_v4.py', run, str(FROZEN / 'extractor_recall.py')] + (['--exclude', exclude] if exclude else [])
    src = (FROZEN / 'extract_eval_v4.py').read_text(encoding='utf-8')
    ns: dict = {'__name__': 'frozen_scorer'}
    exec(compile(src[:src.index("names = ['0 기존'")], str(FROZEN / 'extract_eval_v4.py'), 'exec'), ns)
    return ns


def _obs(r: dict, QI) -> list[tuple[int, dict, dict]]:
    out = []
    for o in r.get('raw_observations') or []:
        m = re.search(r'\d+', str(o.get('case_ref') or ''))
        if not m or o.get('attribute') not in QI:
            continue
        rec = next((x for x in (r.get('cases') or {}).get(o.get('case_ref'), {}).get('normalized', [])
                    if x.get('attribute') == o['attribute'] and x.get('raw_value') == o.get('raw_value')), None)
        if rec is not None:
            out.append((int(m.group()), o, rec))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('run')
    ap.add_argument('--exclude', default=None)
    ap.add_argument('--examples', type=int, default=2)
    a = ap.parse_args()
    ns = load_frozen(a.run, a.exclude)
    er, facts, docs_of, data, QI, doc_has = ns['er'], ns['facts'], ns['docs_of'], ns['data'], ns['QI'], ns['doc_has']

    def hit(o, a_, v):
        return o['attribute'] == a_ and any(s and (s in v or v in s) for s in er._sp(o))

    gold = collections.Counter(); got = collections.Counter(); com = collections.Counter()
    miss = collections.Counter(); uniq = collections.defaultdict(set); ex = collections.defaultdict(list)
    ctx = collections.Counter()
    prec = collections.Counter(); bad = collections.Counter(); pex = collections.defaultdict(list)
    fail = collections.Counter(); fex = collections.defaultdict(list)

    for line in open(Path(a.run) / '턴기록.jsonl', encoding='utf-8'):
        r = json.loads(line)
        if r.get('arm') != 'C0' or not r.get('raw_response_text') or r['trial_id'] not in docs_of:
            continue
        t, docs, resp = r['trial_id'], docs_of[r['trial_id']], r['raw_response_text']
        obs = _obs(r, QI)
        by, cby = collections.defaultdict(list), collections.defaultdict(list)
        for n, o, rec in obs:
            by[n].append(o)
            if rec.get('commit'):
                cby[n].append(o)
        for n, seg in er.split_cases(resp).items():
            if n < 1 or n > len(docs):
                continue
            for f in facts[docs[n - 1]]:
                mt = er.match_fact(data, f, seg)
                if not mt:
                    continue
                at, val = f['attribute'], mt[1]
                gold[t] += 1
                if any(hit(o, at, val) for o in by.get(n, [])):
                    got[t] += 1
                    com[t] += any(hit(o, at, val) for o in cby.get(n, []))
                    continue
                if any(hit(o, at, val) for k, os_ in by.items() if k != n for o in os_):
                    kind = '다른 사례에 붙임'
                elif any(any(s and (s in val or val in s) for s in er._sp(o)) for o in by.get(n, [])):
                    kind = '다른 종류로 뽑음'
                elif not by.get(n):
                    kind = '그 사례에서 뽑은 것 없음'
                elif any(o['attribute'] == at for o in by.get(n, [])):
                    kind = '같은 종류 다른 값만'
                else:
                    kind = '아예 안 뽑음'
                miss[(at, kind)] += 1
                uniq[(at, kind)].add((t, r['turn'], n, val))
                if len(ex[(at, kind)]) < a.examples:
                    ex[(at, kind)].append(f'{t} 턴{r["turn"]} 사례{n} {val[:40]}')
                if at == 'PERIOD':
                    ln = next((x for x in seg.split('\n') if val in x), '')
                    head = ln[:ln.find(val)] if val in ln else ln
                    ctx[('표 줄' if ln.strip().startswith('|') else '일반 줄', '날짜 앞 사건 낱말 있음' if ROLEW.search(head) else '날짜 앞 사건 낱말 없음')] += 1
        for n, o, rec in obs:
            if n < 1 or n > len(docs):
                continue
            if not rec.get('commit'):
                k = (o['attribute'], '; '.join(map(str, rec.get('reasons') or [])) or str(rec.get('mapping_status')))
                fail[k] += 1
                if len(fex[k]) < a.examples:
                    fex[k].append(str(o.get('raw_value'))[:40])
                continue
            reasons = [str(x) for x in rec.get('reasons') or []]
            how = next((x for x in ('TOKEN_SUBSET_LCA', 'SLASH_SPLIT', 'SEX_SHORT', 'PAREN_SPLIT') if x in reasons), '')
            src = o.get('rule') or o.get('source') or 'LLM'
            k = (o['attribute'], src + (f'/{o["fixed_from"]}에서 바꿈' if o.get('fixed_from') else ''), how)
            prec[k] += 1
            if not doc_has(rec.get('node_id'), docs[n - 1]):
                bad[k] += 1
                if len(pex[k]) < a.examples:
                    pex[k].append(f'{t} 턴{r["turn"]} 사례{n} {str(o.get("raw_value"))[:30]}')

    G, H, C = sum(gold.values()), sum(got.values()), sum(com.values())
    print(f'평가 trial {len(gold)}개  단서 {G}개  재현율 {H / G:.1%}  확정 재현율 {C / G:.1%}')
    print('\n[1] trial별 (재현율 / 확정 재현율 / 놓친 단서)')
    for t in sorted(gold):
        print(f'  {t}  단서 {gold[t]:4d}  재현율 {got[t] / gold[t]:6.1%}  확정 {com[t] / gold[t]:6.1%}  놓침 {gold[t] - got[t]:4d}')
    print('\n[2] 놓친 단서 (전체 / 서로 다른 표현)')
    for k, v in sorted(miss.items(), key=lambda x: -x[1]):
        print(f'  {v:4d} / {len(uniq[k]):3d}  {k[0]:7s} {k[1]:14s} 예: {" | ".join(ex[k])}')
    if ctx:
        print('\n[3] 놓친 날짜가 나온 줄')
        for k, v in sorted(ctx.items(), key=lambda x: -x[1]):
            print(f'  {v:4d}  {k[0]} · {k[1]}')
    print('\n[4] 확정 값 정밀도 (단서 · 출처 · 정규화 방식)')
    for k, v in sorted(prec.items(), key=lambda x: -x[1]):
        note = f'  틀린 예: {" | ".join(pex[k])}' if bad[k] else ''
        print(f'  {k[0]:7s} {k[1]:24s} {k[2]:17s} {v - bad[k]:4d}/{v:4d}{note}')
    print('\n[5] 확정하지 못한 관찰 (이유)')
    for k, v in sorted(fail.items(), key=lambda x: -x[1]):
        print(f'  {v:4d}  {k[0]:7s} {k[1][:60]}  예: {" | ".join(fex[k])}')


if __name__ == '__main__':
    main()
