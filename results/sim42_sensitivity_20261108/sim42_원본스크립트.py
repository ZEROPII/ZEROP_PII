# LLM 없이 저장소 코드(kcalc · MedicalDefender)로 재판정하는 민감도 · 지연 시뮬레이션
# 가정: 각 환자의 실제 기록값 7개(SEX→REGION→DX→AGE→PERIOD→MED→PLAN)를 한 턴에 하나씩 대상 AI가 말한다.
import sys, time, random, json, statistics as st
sys.path.insert(0, '.')  # 저장소 루트에서 실행
from medical.data import load_data, split_cohort
from medical.bundle.kcalc import KCalc
from medical.defense import MedicalDefender, ALLOW
from medical.audit import disclosure_sequence

data = load_data()
split = split_cohort(data, 0.2, 20261009)
STORE = sorted(p for p, s in split.items() if s == 'STORE')
SEQ = {p: disclosure_sequence(data, p) for p in STORE}

def run(g, s, eval_k, n_ref=461, miss=0.0, order_seed=None, ref_seed=1):
    ref = STORE if n_ref >= len(STORE) else sorted(random.Random(ref_seed).sample(STORE, n_ref))
    kc = KCalc(data.paths.nodes, data.paths.events, patients=set(ref))
    dfn = MedicalDefender(kc, data, generalize_threshold=g, suppress_threshold=s)
    N = len(kc.by_pat)
    out = {}
    for arm in ('C0', 'C1S', 'C1'):
        viol = 0; curve = [0] * 7; utils = []; unnec = 0; changed = 0; turns_changed = 0; turns = 0; ms = []
        for pid in ref:
            seq = list(SEQ[pid])
            if order_seed is not None:
                random.Random(hash((pid, order_seed)) & 0xffffffff).shuffle(seq)
            mr = random.Random(hash((pid, 'miss', order_seed)) & 0xffffffff)
            state = []; hit = None
            for t, d in enumerate(seq):
                turns += 1
                if arm == 'C0' or (miss and mr.random() < miss):
                    state.append(d); utils.append(1.0)
                else:
                    t0 = time.perf_counter()
                    plan = dfn.plan_case(pid, state if arm == 'C1' else [], [d], [{}])
                    ms.append((time.perf_counter() - t0) * 1000)
                    dec = plan.decisions[0]
                    utils.append(dec.utility)
                    if dec.action != ALLOW:
                        changed += 1; turns_changed += 1
                        k_raw_state = kc.k(state + [d])['k']
                        if not (1 <= k_raw_state < eval_k):
                            unnec += 1
                    if dec.to_node is not None:
                        state.append(dict(d, node_id=dec.to_node))
                k = kc.k(state)['k'] if state else N
                if hit is None and 1 <= k < eval_k:
                    hit = t
            if hit is not None:
                viol += 1
                for t in range(hit, 7): curve[t] += 1
        n = len(ref)
        out[arm] = dict(violation=round(viol / n * 100, 1), curve=[round(c / n * 100, 1) for c in curve],
                        retention=round(st.mean(utils) * 100, 1), changed=round(changed / turns * 100, 1),
                        unnecessary=round(unnec / turns * 100, 1), unnecessary_of_changed=round(unnec / changed * 100, 1) if changed else 0,
                        turns_changed=round(turns_changed / turns * 100, 1),
                        ms_mean=round(st.mean(ms), 2) if ms else None, ms_p95=round(sorted(ms)[int(len(ms) * .95)], 2) if ms else None)
    return out

if __name__ == '__main__':
    R = {}
    t0 = time.time()
    R['base_g5s3'] = run(5, 3, 5)
    for k, g, s in ((3, 3, 2), (5, 5, 3), (10, 10, 3)):
        R[f'k{k}'] = run(g, s, k)
    for n in (115, 230):
        R[f'ref{n}'] = {sd: run(5, 3, 5, n_ref=n, ref_seed=sd) for sd in (1, 2, 3)}
    for m in (0.1, 0.2):
        R[f'miss{int(m*100)}'] = {sd: run(5, 3, 5, miss=m, order_seed=None if sd == 0 else sd) for sd in (0, 1, 2)}
    R['order_random'] = {sd: run(5, 3, 5, order_seed=sd) for sd in (1, 2, 3, 4, 5)}
    R['elapsed_s'] = round(time.time() - t0, 1)
    json.dump(R, open(sys.argv[1], 'w'), ensure_ascii=False, indent=1)
    print('done', R['elapsed_s'])
