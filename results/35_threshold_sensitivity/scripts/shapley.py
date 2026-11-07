import json, math, ast, csv, sys, collections, itertools, statistics as st
sys.path.insert(0, '/home/claude/zerop_pii')
from medical.bundle.kcalc import KCalc
RUN = "/home/claude/zp_poc/runs/medical/sim_base_5_3"
store = {r['patient_id'] for r in csv.DictReader(open(f"{RUN}/코호트분리.csv", encoding='utf-8-sig')) if r['split'] == 'STORE'}
N = len(store)
kc = KCalc("/home/claude/zerop_pii/data/medical/노드_v0.9.csv", "/home/claude/zerop_pii/data/medical/사건연결표_v0.9.csv", patients=store)
ATTRS = ["AGE", "SEX", "REGION", "PERIOD", "DX", "PROC", "MED", "PLAN"]
rows = [json.loads(l) for l in open(f"{RUN}/턴기록.jsonl", encoding='utf-8')]
# 최종 상태: C0, 턴 7 (없으면 마지막 턴)
last = {}
for r in rows:
    if r['arm'] != 'C0': continue
    key = (r['trial_id'], r['target_ref'] if False else None)
    for ref, c in r['cases'].items():
        k2 = (r['trial_id'], ref)
        if k2 not in last or r['turn'] > last[k2][0]:
            last[k2] = (r['turn'], c)
print("C0 사례 수:", len(last))
shap = collections.defaultdict(list); shap_id = collections.defaultdict(list)
mismatch = 0; eff_err = []
for (trial, ref), (turn, c) in last.items():
    disc = []
    for ks, node in c['state'].items():
        k = ast.literal_eval(ks)
        disc.append({'attribute': k[0], 'node_id': node, 'event_group': k[1] if len(k) >= 2 else None, '_k': k})
    present = sorted({d['attribute'] for d in disc} & set(ATTRS))
    if not present: continue
    def kS(S):
        sub = [{x: y for x, y in d.items() if x != '_k'} for d in disc if d['attribute'] in S]
        return kc.k(sub)['k'] if sub else N
    m = len(present); vals = {}
    for r_ in range(m + 1):
        for S in itertools.combinations(present, r_):
            vals[frozenset(S)] = kS(set(S))
    if vals[frozenset(present)] != c['k']: mismatch += 1
    full = frozenset(present)
    v = lambda S: math.log2(N / vals[S]) if vals[S] else 0
    vi = lambda S: 1.0 if 1 <= vals[S] < 5 else 0.0
    for i in present:
        others = [a for a in present if a != i]
        s_log = 0.0; s_id = 0.0
        for r_ in range(len(others) + 1):
            for S in itertools.combinations(others, r_):
                S = frozenset(S); w = math.factorial(len(S)) * math.factorial(m - len(S) - 1) / math.factorial(m)
                s_log += w * (v(S | {i}) - v(S)); s_id += w * (vi(S | {i}) - vi(S))
        shap[i].append(s_log); shap_id[i].append(s_id)
    eff_err.append(abs(sum(shap[i][-1] for i in present) - (v(full) - v(frozenset()))))
print("k 재계산 불일치 (C0 최종):", mismatch, "/", len(last))
print("효율성 오차 최대:", round(max(eff_err), 6) if eff_err else None)
print(f"{'속성':8} {'사례 수':>7} {'Shapley log2 평균':>18} {'식별 Shapley 평균':>18}")
for a in ATTRS:
    v_ = shap.get(a, [])
    if v_: print(f"{a:8} {len(v_):7d} {st.mean(v_):18.3f} {st.mean(shap_id[a]):18.3f}")
