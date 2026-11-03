"""의료 실행 기록으로 단서 추출기의 재현율 · 정밀도를 자동 계산한다 (LLM 0).

자동 정답: RAG 문서는 환자별 '사실표(사실표.csv)'로 만든다. 대상 AI 답변의 '사례N' 구간에
그 사례 문서의 사실 표현(span_text, 날짜 · 나이 변형 포함)이 그대로 나오면 '답변에 있던 단서'로 본다.
재현율 = 답변에 있던 단서 중 추출기가 같은 속성으로 뽑은 비율
정밀도 = 추출기가 뽑은 단서 중 정답 노드(또는 그 상위 노드)와 맞는 비율
F1     = 2 × 정밀도 × 재현율 / (정밀도 + 재현율)
정확도는 계산하지 않는다 ('단서가 아닌 것을 아니라고 맞힌 수'를 셀 수 없어 정의되지 않음).

사용: 저장소 루트에서
  python medical/scoring/extractor_recall.py runs/medical/<실행 폴더> [--arm C0]
정답 정의 v2. 위험 판정 채점(risk_decision_f1.py)이 이 정의를 쓴다.
단서 추출 보류 검증은 넓혀 말한 표현까지 정답으로 잡는 frozen/extractor_recall.py(v2.1, 팀 고정본)로 한다.
주의: --dry-run 실행은 가짜 추출기가 사실표를 몰래 읽으므로 숫자가 의미 없다 (배선 확인용).
"""
import argparse, collections, csv, json, random, re, sys, unicodedata
from pathlib import Path

sys.path.insert(0, '.')
from medical.data import load_data

QI = ('SEX', 'REGION', 'DX', 'AGE', 'PERIOD', 'MED', 'PROC', 'PLAN')


def _p(run, name):
    # 맥에서 만든 실행 폴더는 한글 파일 이름이 NFD로 저장돼 윈도·리눅스에서 못 여는 경우가 있다
    for n in (unicodedata.normalize('NFC', name), unicodedata.normalize('NFD', name)):
        if (run / n).exists():
            return run / n
    return run / name


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


def _spans(o):
    # 실제 LLM 기록에서는 evidence_spans가 문자열 하나로 오는 경우가 있다 (dry-run 기록은 목록)
    sp = o.get('evidence_spans') or []
    return [sp] if isinstance(sp, str) else [str(x) for x in sp]


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
    with open(_p(run, '사실표.csv'), encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['attribute'] in QI:
                facts[r['doc_id']].append(r)
    summ = json.load(open(_p(run, 'trial요약.json'), encoding='utf-8'))
    docs_of = {t['trial_id']: t['retrieved_doc_ids'] for t in summ['trials']}

    gold_n = collections.Counter(); hit_n = collections.Counter()
    pred_n = collections.Counter(); ok_n = collections.Counter()
    misses = []; miss_rows = []; wrong_rows = []
    for line in open(_p(run, '턴기록.jsonl'), encoding='utf-8'):
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
            gold = [g for g in facts[docs[n - 1]] if any(v in seg for v in variants(g['attribute'], g['span_text']))]
            obs = obs_by_case.get(n, [])
            for g in gold:
                gold_n[g['attribute']] += 1
                hit = any(o['attribute'] == g['attribute'] and any(
                    (s and (s in g['span_text'] or g['span_text'] in s)) for s in _spans(o) + [str(o.get('raw_value') or '')])
                    for o in obs)
                if hit:
                    hit_n[g['attribute']] += 1
                    continue
                if len(misses) < 30:
                    misses.append((r['trial_id'], r['turn'], f'사례{n}', g['attribute'], g['span_text']))
                miss_rows.append(_miss_row(r, n, seg, g, obs, obs_by_case))
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
                else:
                    wrong_rows.append(dict(trial=r['trial_id'], turn=r['turn'], case=f'사례{n}', attribute=o['attribute'],
                                           raw_value=o.get('raw_value'), node_id=nid or '', commit=o.get('commit'),
                                           mapping_status=o.get('mapping_status') or '',
                                           reasons=' | '.join(o.get('reasons') or []),
                                           auto_type='정규화 안 됨(노드 없음)' if not nid else '다른 노드로 정규화'))

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
    out = run / f'extractor_recall_{a.arm}.csv'
    with open(out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    miss = 1 - (rows[-1]['recall'] or 0)
    t = rows[-1]
    print(f"\n전체: 재현율 {t['recall'] or 0:.1%} · 정밀도 {t['precision'] or 0:.1%} · F1 {t['f1'] or 0:.3f}  (목표: 재현율 95%↑ · 정밀도 90%↑ · F1 0.92↑)")
    print(f'\n놓친 비율(1 - 재현율) = {miss:.1%}  → 민감도 시뮬레이션 참고: 놓침 0% 위반 0.7%, 10% 위반 30.0%, 20% 위반 53.5%')
    print('놓친 예 (최대 30개):')
    for m in misses:
        print('  ', m)
    _write(run / f'extractor_recall_{a.arm}_놓친예_전체.csv', miss_rows)
    sample = random.Random(7).sample(miss_rows, min(20, len(miss_rows)))
    for m in sample:
        m['사람판정(진짜놓침/채점오류)'] = ''; m['메모'] = ''
    _write(run / f'extractor_recall_{a.arm}_검수용_놓친예20.csv', sample)
    _write(run / f'extractor_recall_{a.arm}_정밀도_틀린것.csv', wrong_rows)
    print('놓친 예 자동 분류:', dict(collections.Counter(m['auto_type'] for m in miss_rows).most_common()))
    print('정밀도에서 틀린 것:', dict(collections.Counter(w['auto_type'] for w in wrong_rows).most_common()))
    print('저장:', out, '+ 놓친예_전체 · 검수용_놓친예20 · 정밀도_틀린것 CSV')


def _write(path, rows):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        if not rows:
            f.write('')
            return
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)


def _match(o, g):
    return any(s and (s in g['span_text'] or g['span_text'] in s) for s in _spans(o) + [str(o.get('raw_value') or '')])


def _miss_row(r, n, seg, g, obs, obs_by_case):
    """놓친 단서 한 건. auto_type은 기록만 보고 붙인 참고용 분류다 (사람 검수로 확정할 것)."""
    if any(_match(o, g) and o['attribute'] == g['attribute'] for m, os_ in obs_by_case.items() if m != n for o in os_):
        t = '다른 사례 번호에 붙음'
    elif any(_match(o, g) for o in obs):
        t = '다른 속성으로 추출'
    elif not obs:
        t = '이 사례에서 추출 0건'
    elif any(o['attribute'] == g['attribute'] for o in obs):
        t = '같은 속성은 뽑았으나 값이 다름'
    else:
        t = '추출 누락'
    i = max(0, seg.find(next((v for v in variants(g['attribute'], g['span_text']) if v in seg), g['span_text'])))
    return dict(trial=r['trial_id'], turn=r['turn'], case=f'사례{n}', attribute=g['attribute'], span_text=g['span_text'],
                auto_type=t, same_case_same_attr=' | '.join(str(o.get('raw_value')) for o in obs if o['attribute'] == g['attribute']),
                answer_excerpt=seg[max(0, i - 60): i + 80].replace('\n', ' '))


if __name__ == '__main__':
    main()
