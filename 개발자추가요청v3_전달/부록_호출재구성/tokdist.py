import json,math,statistics,sys,collections
U=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
def nr(xs,p):  # nearest-rank
  s=sorted(xs); return s[max(1,math.ceil(p/100*len(s)))-1]
def lin(xs,p):  # linear interpolation (numpy default, type 7)
  s=sorted(xs); h=(len(s)-1)*p/100; f=math.floor(h); return s[f]+(s[min(f+1,len(s)-1)]-s[f])*(h-f)
for role in ('extractor','target','checker','mutator','rewriter'):
  xs=[u['output_tokens'] for u in U if u['role']==role]; tr=[u for u in U if u['role']==role and u['truncated']]
  ntr=[u['output_tokens'] for u in U if u['role']==role and not u['truncated']]
  print(role, 'n',len(xs),'sum',sum(xs),'mean',round(statistics.mean(xs),1),'min',min(xs),'max',max(xs),
        'NR P50/90/95/99',[nr(xs,p) for p in (50,90,95,99)], 'LIN',[round(lin(xs,p),1) for p in (50,90,95,99)],
        'trunc',len(tr),f'{len(tr)/len(xs):.1%}', 'trunc tokens', sorted(collections.Counter(u['output_tokens'] for u in tr).items())[:5],
        'non-trunc P99 NR', nr(ntr,99) if ntr else None, 'non-trunc max', max(ntr) if ntr else None)
