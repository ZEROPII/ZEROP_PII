import json,collections,sys
C=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
T=[json.loads(l) for l in open(sys.argv[2],encoding='utf-8')]
ex=[c for c in C if c['role']=='extractor']
print('extractor calls',len(ex), sorted(collections.Counter((c['purpose'],c.get('parse_ok','?'),c['truncated']) for c in ex).items(), key=str))
fails=[t for t in T if t.get('release_mode')=='REFUSAL_EXTRACTION_FAILED']
print('34 fails turn0?', collections.Counter(t['turn']==0 for t in fails))
def raw_calls(t):
  arm='SHARED' if t['turn']==0 else t['arm']
  return [c for c in ex if c['trial_id']==t['trial_id'] and c['arm']==arm and c['turn']==t['turn'] and c['purpose']=='raw']
cls=collections.Counter()
for t in fails:
  calls=raw_calls(t); cls[(len(calls), sum(c['truncated'] for c in calls))]+=1
print('34 failures -> (n attempts, n truncated):',cls)
fr=collections.Counter()
for t in T:
  if t.get('turn') is None or t.get('extraction_ok'): continue
  calls=raw_calls(t); fr[(t['arm'],'t0' if t['turn']==0 else 't>=1',len(calls),sum(c['truncated'] for c in calls))]+=1
print('all failed raw extraction turns (arm,turn,n,trunc):',fr)
print('parse fail & not truncated:', sum(1 for c in ex if c.get('parse_ok') is False and not c['truncated']))
print('parse ok & truncated:', sum(1 for c in ex if c.get('parse_ok') is True and c['truncated']))
tg=[c for c in C if c['role']=='target']
ft=collections.Counter()
for t in fails:
  arm='SHARED' if t['turn']==0 else t['arm']
  c=[c for c in tg if c['trial_id']==t['trial_id'] and c['arm']==arm and c['turn']==t['turn']]
  ft[c[0]['truncated']]+=1
print('target truncated in 34 failing turns', ft)
