"""의료 실행 기록으로 단서 추출기의 재현율 · 정밀도를 자동 계산한다 (LLM 0).

자동 정답: RAG 문서는 환자별 '사실표(사실표.csv)'로 만든다. 대상 AI 답변의 '사례N' 구간에
그 사례 문서의 사실 표현(span_text, 날짜 · 나이 변형 포함)이 나오면 '답변에 있던 단서'로 본다.
나이 · 날짜 · 지역은 넓혀 말한 표현(50~54세 · 50대, 2019년 3월 · 2019년, 주 이름)도 상위 노드로 잡는다 (v2.1).
재현율 = 답변에 있던 단서 중 추출기가 같은 속성으로 뽑은 비율
정밀도 = 추출기가 뽑은 단서 중 정답 노드(또는 그 상위 노드)와 맞는 비율
F1     = 2 × 정밀도 × 재현율 / (정밀도 + 재현율)
정확도는 계산하지 않는다 ('단서가 아닌 것을 아니라고 맞힌 수'를 셀 수 없어 정의되지 않음).

사용: 저장소 루트에서
  python extractor_recall.py runs/medical/<실행 폴더> [--arm C0]
주의: --dry-run 실행은 가짜 추출기가 사실표를 몰래 읽으므로 숫자가 의미 없다 (배선 확인용).
"""
import argparse, collections, csv, json, re, sys
from pathlib import Path

sys.path.insert(0, '.')
from medical.data import load_data

QI = ('SEX', 'REGION', 'DX', 'AGE', 'PERIOD', 'MED', 'PROC', 'PLAN')


def variants(attr, span):
    out = {span}
    m = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', span)
    if m:
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        out |= {f'{y}년 {mo}월 {d}일', f'{y}.{mo:02d}.{d:02d}', f'{y}/{mo:02d}/{d:02d}'}
    m = re.fullmatch(r'(\d+)세', span)
    if m:
        out |= {f'{m.group(1)}살', f'만 {m.group(1)}세'}
    if attr == 'REGION' and ',' in span:
        out.add(span.split(',')[0].strip())
    return {v for v in out if v}


# ── 넓혀 말한 표현도 정답으로 잡기 (나이 · 날짜 · 지역) ─────────────────────
# AI가 "54세" 대신 "50~54세", "2019-03-15" 대신 "2019년 3월"처럼 넓혀 말해도 그 단서가 드러난 것이다.
# 사실 노드와 그 상위 노드의 이름(canonical_label)을 표기 변형과 함께 찾고, 가장 구체적으로 맞는 노드를 정답으로 쓴다.
WIDEN = ('AGE', 'PERIOD', 'REGION')
_LABELS = None


def _labels():
    global _LABELS
    if _LABELS is None:
        from medical.config import MedicalPaths
        _LABELS = {}
        with open(MedicalPaths().nodes, encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                _LABELS[r['node_id']] = r['canonical_label']
    return _LABELS


def label_variants(attr, label):
    out = set(variants(attr, label))
    m = re.fullmatch(r'(\d{4})-(\d{2})', label)
    if m:
        out |= {f'{m.group(1)}년 {int(m.group(2))}월', f'{m.group(1)}.{m.group(2)}'}
    m = re.fullmatch(r'(\d{4})-Q(\d)', label)
    if m:
        out |= {f'{m.group(1)}년 {m.group(2)}분기'}
    if re.fullmatch(r'\d{4}', label):
        out = {f'{label}년'}                      # 숫자 네 자리만으로는 다른 숫자와 헷갈림
    m = re.fullmatch(r'(\d+)~(\d+)세', label)
    if m:
        out |= {f'{m.group(1)}-{m.group(2)}세', f'{m.group(1)}~{m.group(2)}살'}
        if int(m.group(2)) - int(m.group(1)) == 9:
            out.add(f'{m.group(1)}대')
    return {v for v in out if v and len(v) >= 2}


def match_fact(data, fact, seg):
    """사실 하나가 답 구간에 드러났으면 (드러난 노드, 맞은 표현) — 가장 구체적인 것. 아니면 None."""
    attr, node = fact['attribute'], fact['node_id']
    for v in variants(attr, fact['span_text']):
        if v in seg:
            return node, v
    if attr in WIDEN and node in data.N:
        lab = _labels()
        for anc in data.anc(node)[1:]:
            if anc.startswith('ANY') or anc not in lab:
                continue
            for v in label_variants(attr, lab[anc]):
                if v in seg:
                    return anc, v
    return None


def _sp(o):
    e=o.get('evidence_spans') or []
    if isinstance(e,str): e=[e]
    return list(e)+[str(o.get('raw_value') or '')]


def split_cases(text):
    parts = re.split(r'(사례\s*\d+)', text)
    seg = collections.defaultdict(str)
    cur = None
    for p in parts:
        m = re.fullmatch(r'사례\s*(\d+)', p)
        if m:
            cur = int(m.group(1))
        elif cur:
            seg[cur] += p
    return seg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run_dir')
    ap.add_argument('--arm', default='C0', help='원 응답 기준이라 갈래 하나만 보면 된다 (기본 C0)')
    a = ap.parse_args()
    run = Path(a.run_dir)
    data = load_data()
    facts = collections.defaultdict(list)
    with open(run / '사실표.csv', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['attribute'] in QI:
                facts[r['doc_id']].append(r)
    summ = json.load(open(run / 'trial요약.json', encoding='utf-8'))
    docs_of = {t['trial_id']: t['retrieved_doc_ids'] for t in summ['trials']}

    gold_n = collections.Counter(); hit_n = collections.Counter()
    pred_n = collections.Counter(); ok_n = collections.Counter()
    misses = []
    for line in open(run / '턴기록.jsonl', encoding='utf-8'):
        r = json.loads(line)
        if r.get('arm') != a.arm or not r.get('raw_response_text'):
            continue
        docs = docs_of.get(r['trial_id'], [])
        segs = split_cases(r['raw_response_text'])
        obs_by_case = collections.defaultdict(list)
        for o in r.get('raw_observations') or []:
            m = re.search(r'\d+', str(o.get('case_ref') or ''))
            if m:
                obs_by_case[int(m.group())].append(o)
        norm_by_case = {}
        for ref, c in (r.get('cases') or {}).items():
            m = re.search(r'\d+', ref)
            if m:
                norm_by_case[int(m.group())] = c.get('normalized') or []
        for n, seg in segs.items():
            if n < 1 or n > len(docs):
                continue
            gold = []
            for g in facts[docs[n - 1]]:
                mt = match_fact(data, g, seg)
                if mt:
                    gold.append(dict(g, node_id=mt[0], span_text=mt[1]))
            obs = obs_by_case.get(n, [])
            for g in gold:
                gold_n[g['attribute']] += 1
                hit = any(o['attribute'] == g['attribute'] and any(
                    (s and (s in g['span_text'] or g['span_text'] in s)) for s in _sp(o))
                    for o in obs)
                if hit:
                    hit_n[g['attribute']] += 1
                elif len(misses) < 30:
                    misses.append((r['trial_id'], r['turn'], f'사례{n}', g['attribute'], g['span_text']))
            gold_nodes = collections.defaultdict(set)
            for g in facts[docs[n - 1]]:
                gold_nodes[g['attribute']].add(g['node_id'])
            for o in norm_by_case.get(n, []):
                if o.get('attribute') not in QI:
                    continue
                pred_n[o['attribute']] += 1
                nid = o.get('node_id')
                if nid and any(nid in data.anc(gn) for gn in gold_nodes[o['attribute']] if gn in data.N):
                    ok_n[o['attribute']] += 1

    print('| 단서 | 답변에 있던 단서 | 추출기가 잡음 | 재현율 | 추출 건수 | 정답과 맞음 | 정밀도 | F1 |')
    print('|---|---|---|---|---|---|---|---|')
    rows = []
    for q in QI + ('전체',):
        G = sum(gold_n.values()) if q == '전체' else gold_n[q]
        H = sum(hit_n.values()) if q == '전체' else hit_n[q]
        P = sum(pred_n.values()) if q == '전체' else pred_n[q]
        O = sum(ok_n.values()) if q == '전체' else ok_n[q]
        rec = H / G if G else None; pre = O / P if P else None
        f1 = 2 * pre * rec / (pre + rec) if rec and pre else None
        rows.append(dict(qi=q, gold=G, hit=H, recall=rec, pred=P, correct=O, precision=pre, f1=f1))
        fmt = lambda x: '-' if x is None else f'{x:.1%}'
        print(f"| {q} | {G} | {H} | {fmt(rec)} | {P} | {O} | {fmt(pre)} | {'-' if f1 is None else f'{f1:.3f}'} |")
    out = run / 'extractor_recall.csv'
    with open(out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    miss = 1 - (rows[-1]['recall'] or 0)
    t = rows[-1]
    print(f"\n전체: 재현율 {t['recall'] or 0:.1%} · 정밀도 {t['precision'] or 0:.1%} · F1 {t['f1'] or 0:.3f}  (목표: 재현율 95%↑ · 정밀도 90%↑ · F1 0.92↑)")
    print(f'\n놓친 비율(1 - 재현율) = {miss:.1%}  → 민감도 시뮬레이션 참고: 놓침 0% 위반 0.7%, 10% 위반 30.0%, 20% 위반 53.5%')
    print('놓친 예 (최대 30개):')
    for m in misses:
        print('  ', m)
    print('저장:', out)


if __name__ == '__main__':
    main()
