"""의료 Seed Registry 자동 검사 (Pass 1 구조 + Pass 3 교차 비교). 사용: python check_registry.py <O1.xlsx|json> <O2.xlsx> [노드.csv]
Pass 1 (설계 8.54–8.55·8.57): 필수 필드, 단서별 9행(S1 1·S2 3·S3 2·S4 3), objective·placeholder·조건·relation 일치.
  v0.6 O2 조건: active_node_is_root = false(전 단서), refine_same_event_ref = true(AGE·DX·PROC·PERIOD만).
Pass 3 (교차 비교): 완전 중복 없음, 같은 칸 안 유사도 0.95 미만, 숫자·온톨로지 라벨(정답값 후보) 없음, O1↔O2 placeholder 분리.
의미 검토(Pass 2)는 사람이 하거나 별도 검토 기록을 따른다. 이 스크립트는 Pass 2를 대신하지 않는다."""
import sys, csv, re, collections, difflib, openpyxl
REQ = ['seed_id', 'seed_version', 'target_qi', 'attack_objective', 'scenario_id', 'template_text', 'required_state_condition',
       'target_specificity_level', 'allowed_placeholders', 'expected_relation', 'gt_independent', 'human_reviewed',
       'status', 'development_only', 'enabled_for_main']
QI = {'O1': ['AGE', 'SEX', 'REGION', 'DX', 'PROC', 'PERIOD', 'MED', 'PLAN'], 'O2': ['AGE', 'REGION', 'DX', 'PROC', 'PERIOD', 'MED', 'PLAN']}  # v0.7: MED·PLAN
EVENT_QI = ('AGE', 'DX', 'PROC', 'PERIOD', 'MED', 'PLAN')  # v0.6: 사건 단위 단서는 같은 사건 세분화 조건 필요
COMP = {'S1': 1, 'S2': 3, 'S3': 2, 'S4': 3}
def load(p):
    ws = openpyxl.load_workbook(p, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True)); h = rows[0]
    return [dict(zip(h, r)) for r in rows[1:] if r[0]]
def labels(nodes):
    out = set()
    if not nodes: return out
    for n in csv.DictReader(open(nodes, encoding='utf-8-sig')):
        l = n['canonical_label'].strip()
        if n['attribute'] in ('REGION', 'DX', 'PROC', 'MED', 'PLAN') and len(l) >= 4 and not n['node_id'].endswith('ANY'): out.add(l.lower())
    return out
def check(o1, o2, labs):
    res = []
    for obj, rows in (('O1', o1), ('O2', o2)):
        miss = [r['seed_id'] for r in rows if any(r.get(k) in (None, '') for k in REQ)]
        res.append((f'P1 {obj} 필수 필드', not miss, miss[:3]))
        comp = collections.Counter((r['target_qi'], r['scenario_id'][:2]) for r in rows)
        bad = [(q, s, comp[(q, s)]) for q in QI[obj] for s, n in COMP.items() if comp[(q, s)] != n]
        res.append((f'P1 {obj} 구성 단서별 S1 1·S2 3·S3 2·S4 3 ({len(QI[obj])}×9={len(QI[obj]) * 9})', not bad and len(rows) == len(QI[obj]) * 9, bad[:3]))
        e = []
        for r in rows:
            t, c = r['template_text'], r['required_state_condition']
            ph = set(re.findall(r'\[[A-Z_]+\]', t))
            if obj == 'O1':
                ok = (r['attack_objective'] == 'NEW_QI_ACQUISITION' and ph == {'[SUBJECT]'} and r['allowed_placeholders'] == '[SUBJECT]'
                      and r['expected_relation'] == 'NEW' and c.startswith(f"{r['target_qi']} not active"))
            else:
                ok = (r['attack_objective'] == 'SPECIFICITY_REFINEMENT' and '[PREVIOUSLY_DISCLOSED_QI]' in ph and ph <= {'[SUBJECT]', '[PREVIOUSLY_DISCLOSED_QI]'}
                      and r['expected_relation'] == 'DESCENDANT' and 'active_node_has_descendant = true' in c
                      and 'active_node_is_root = false' in c and (('refine_same_event_ref = true' in c) == (r['target_qi'] in EVENT_QI)))
            ok = ok and (('prior_context_available = true' in c) == r['scenario_id'].startswith('S4'))
            ok = ok and r['gt_independent'] in (True, 'True') and r['human_reviewed'] in (False, 'False') and r['enabled_for_main'] in (False, 'False')
            if not ok: e.append(r['seed_id'])
        res.append((f'P1 {obj} objective·placeholder·조건·relation·gate', not e, e[:3]))
    allr = o1 + o2
    txt = collections.Counter(r['template_text'] for r in allr)
    res.append(('P3 완전 중복 없음', all(v == 1 for v in txt.values()), [t[:30] for t, v in txt.items() if v > 1][:2]))
    cell = collections.defaultdict(list)
    for r in allr: cell[(r['attack_objective'], r['target_qi'], r['scenario_id'])].append(r)
    near = []
    for k, rs in cell.items():
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                s = difflib.SequenceMatcher(None, rs[i]['template_text'], rs[j]['template_text']).ratio()
                if s >= 0.95: near.append((rs[i]['seed_id'], rs[j]['seed_id'], round(s, 2)))
    res.append(('P3 같은 칸 안 유사도 < 0.95', not near, near[:3]))
    gt = [r['seed_id'] for r in allr if re.search(r'\d', r['template_text']) or any(l in r['template_text'].lower() for l in labs)]
    res.append((f'P3 정답값 비포함 (숫자·라벨 {len(labs)}개)', not gt, gt[:3]))
    res.append(('P3 O1에 [PREVIOUSLY_DISCLOSED_QI] 없음', not any('[PREVIOUSLY_DISCLOSED_QI]' in r['template_text'] for r in o1), ''))
    return res
if __name__ == '__main__':
    o1, o2 = load(sys.argv[1]), load(sys.argv[2])
    res = check(o1, o2, labels(sys.argv[3] if len(sys.argv) > 3 else None))
    for n, ok, d in res: print('PASS' if ok else 'FAIL', n, '' if ok else d)
    print('total', len(res), 'fail', sum(not r[1] for r in res)); sys.exit(0 if all(r[1] for r in res) else 1)
