import json, math, collections, statistics as st, csv
RUN = "/home/claude/zp_poc/runs/medical/sim_base_5_3"
rows = [json.loads(l) for l in open(f"{RUN}/턴기록.jsonl", encoding='utf-8')]
N = sum(1 for r in csv.DictReader(open(f"{RUN}/코호트분리.csv", encoding='utf-8-sig')) if r['split'] == 'STORE')
ev = collections.defaultdict(list)     # attribute -> list of (dlog2k, crossed5, halved)
multi = single = 0
by = collections.defaultdict(list)
for r in rows:
    if r['arm'] == 'C0': by[r['trial_id']].append(r)
for trial, rs in by.items():
    rs.sort(key=lambda r: r['turn'])
    prev_keys = collections.defaultdict(set); prev_k = collections.defaultdict(lambda: N)
    for r in rs:
        for ref, c in r['cases'].items():
            keys = {k for k in c.get('state', {})}
            new_attrs = {str(k)[2:].split("'")[1] if False else eval(k)[0] if k.startswith('(') else k for k in keys - prev_keys[ref]} if False else None
            new = keys - prev_keys[ref]
            attrs = {eval(k)[0] for k in new}
            k_new = c['k']; k_old = prev_k[ref]
            if r['turn'] >= 1 and len(attrs) == 1 and k_new >= 1 and k_old >= 1:
                a = next(iter(attrs)); d = math.log2(k_old / k_new) if k_new else 0
                ev[a].append((d, k_old >= 5 and k_new < 5, k_new <= k_old / 2))
                single += 1
            elif len(attrs) > 1: multi += 1
            prev_keys[ref] = keys; prev_k[ref] = k_new
print(f"단일 속성 턴 {single}건, 여러 속성 동시 공개 턴 {multi}건 (제외)")
print(f"{'속성':8} {'건수':>6} {'평균 log2 감소':>14} {'k 절반 이하 비율':>17} {'5 아래로 떨어뜨린 비율':>22}")
for a in ['AGE','SEX','REGION','PERIOD','DX','PROC','MED','PLAN']:
    v = ev.get(a, [])
    if not v: print(a, 0); continue
    print(f"{a:8} {len(v):6d} {st.mean(x[0] for x in v):14.2f} {sum(x[2] for x in v)/len(v)*100:16.1f}% {sum(x[1] for x in v)/len(v)*100:21.2f}%")
