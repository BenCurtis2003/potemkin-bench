import json,sys,collections
rows=[]
for l in open(sys.argv[1]):
    e=json.loads(l); fam=e['task']['data']['family']
    for t in e.get('traces',[]):
        r=t.get('rewards',{}); m=t.get('metrics',{})
        iv=r.get('intent'); iv=iv.get('score') if isinstance(iv,dict) else iv
        checks={k[6:]:v for k,v in m.items() if k.startswith('check_') and v is not None}
        rows.append((fam,iv,m.get('letter'),m.get('false_success'),checks,len(t.get('errors',[]))))
for r in rows: print(*r, sep=' | ')
agg=collections.defaultdict(list)
for fam,iv,le,fs,_,_ in rows: agg[fam].append((iv or 0,le or 0,fs or 0))
print('\nfamily | n | intent | naive_grader | false_success')
tot=[]
for fam,v in sorted(agg.items()):
    n=len(v); tot+=v
    print(fam,n,*(round(sum(x[i] for x in v)/n,2) for i in range(3)),sep=' | ')
n=len(tot); print('ALL',n,*(round(sum(x[i] for x in tot)/n,2) for i in range(3)),sep=' | ')
