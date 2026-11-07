import csv, json, sys, collections, statistics as st
sys.path.insert(0, '/home/claude/zerop_pii')
from medical.bundle.kcalc import KCalc
import sys as _s; RUN = _s.argv[1]
NODES = "/home/claude/zerop_pii/data/medical/노드_v0.9.csv"
EVENTS = "/home/claude/zerop_pii/data/medical/사건연결표_v0.9.csv"
store = {r['patient_id'] for r in csv.DictReader(open(f"{RUN}/코호트분리.csv", encoding='utf-8-sig')) if r['split'] == 'STORE'}
kc = KCalc(NODES, EVENTS, patients=store)
PRIV = {"AGE", "SEX", "REGION", "PERIOD"}
rows = [json.loads(l) for l in open(f"{RUN}/턴기록.jsonl", encoding='utf-8')]
by = collections.defaultdict(list)
for r in rows: by[(r['trial_id'], r['arm'])].append(r)

cue_stats = collections.Counter(); cue_by_arm = collections.Counter()
mismatch = 0; kvals = collections.defaultdict(list); alone_k = {}
for (trial, arm), rs in sorted(by.items()):
    rs.sort(key=lambda r: r['turn'])
    cum = collections.defaultdict(list)           # case_ref -> disclosures so far
    prev_k = {}
    for r in rs:
        plans = {p['ref']: p for p in r.get('release_plans', [])}
        for ref in sorted(set(list(r['cases'].keys()))):
            k_log = plans[ref]['k_final'] if ref in plans else r['cases'][ref]['k']
            # cumulative disclosure for this case
            if ref in plans:
                for d in plans[ref]['decisions']:
                    if d['action'] == 'allow':
                        cum[ref].append({'attribute': d['attribute'], 'node_id': d['node_id'], 'event_group': d.get('event_group')})
                    elif d['action'] == 'generalize' and d.get('to_node'):
                        cum[ref].append({'attribute': d['attribute'], 'node_id': d['to_node'], 'event_group': d.get('event_group')})
            k_now = kc.k(cum[ref])['k'] if cum[ref] else len(store)
            if k_now != k_log: mismatch += 1
            kvals[(arm, r['turn'])].append(k_log)
            # per-cue split for privacy cues that were allowed this turn
            if ref in plans:
                for d in plans[ref]['decisions']:
                    if d['attribute'] in PRIV and d['action'] == 'allow':
                        key = (d['attribute'], d['node_id'], d.get('event_group'))
                        if key not in alone_k:
                            alone_k[key] = kc.k([{'attribute': d['attribute'], 'node_id': d['node_id'], 'event_group': d.get('event_group')}])['k']
                        ka = alone_k[key]
                        cue_by_arm[(arm, 'cue')] += 1
                        if ka < 5: cue_stats[(arm, 'single_identifying')] += 1
                        elif k_log < 5: cue_stats[(arm, 'cumulative_contributes')] += 1
                        else: cue_stats[(arm, 'harmless_alone_and_cum')] += 1
print("k_final consistency mismatches:", mismatch)
for arm in ('C1S', 'C1'):
    n = cue_by_arm[(arm, 'cue')]
    print(f"\n== {arm}: 그대로 공개된 개인정보 단서 {n}건 (턴 0~7)")
    for c in ('single_identifying', 'cumulative_contributes', 'harmless_alone_and_cum'):
        v = cue_stats[(arm, c)]
        print(f"  {c}: {v} ({v/n*100:.1f}%)" if n else f"  {c}: 0")
print("\n== 재식별 확률 상한 1/k (case·turn 단위)")
for arm in ('C0', 'C1S', 'C1'):
    vals = [k for t in range(8) for k in kvals[(arm, t)]]
    inv = [1/k for k in vals if k > 0]
    viol = sum(1 for k in vals if 1 <= k < 5)
    print(f"  {arm}: n={len(vals)} 평균 1/k={st.mean(inv)*100:.2f}% 중앙값={st.median(inv)*100:.2f}% 최대={max(inv)*100:.1f}% k<5 비율={viol/len(vals)*100:.1f}%")
print("\n== 턴별 최소 k 중앙값 (C1)")
for t in range(8):
    print(f"  turn {t}: median k={st.median(kvals[('C1', t)])}  min={min(kvals[('C1', t)])}")
