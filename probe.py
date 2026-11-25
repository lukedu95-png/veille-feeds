import requests, re
UA="Mozilla/5.0 (veille-feeds)"
out=[]
for u in ["https://itch.io/jams/upcoming","https://itch.io/jams/upcoming.json","https://itch.io/jams.json","https://itch.io/jams/starting-this-month"]:
    try:
        r=requests.get(u,headers={"User-Agent":UA},timeout=25)
        t=r.text
        out.append(f"== {u} {r.status_code} {r.headers.get('content-type')} len={len(t)}")
        out.append(t[:1500].replace("\n"," "))
        out.append("JAM LINKS: "+str(re.findall(r'href="(/jam/[^"]+)"',t)[:15]))
        i=t.find('jam_cell'); out.append("CELL: "+t[i:i+1500].replace("\n"," ") if i>=0 else "no jam_cell")
    except Exception as e:
        out.append(f"== {u} ERR {e}")
open("digest/probe.txt","w").write("\n".join(out))
