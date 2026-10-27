"""Gera preview.html (arquivo único, com mídias embutidas e os dados reais do banco) para visualização rápida."""
import re, sys, json, base64, os
os.environ.setdefault("PSD_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "perfect_shock.db"))
import app, database as db
c = app.app.test_client(); S = db.stats()
MIME = {"mp4": "video/mp4", "png": "image/png", "jpg": "image/jpeg"}
def inline(h):
    def r(m):
        n = m.group(1); d = base64.b64encode(open("static/img/" + n, "rb").read()).decode()
        return f"data:{MIME[n.rsplit('.', 1)[1]]};base64,{d}"
    return re.sub(r"/static/img/([\w.\-]+)", r, h)
def body(u):
    h = re.sub(r"<script.*?</script>", "", c.get(u).get_data(as_text=True), flags=re.S)
    return inline(re.search(r"<body[^>]*>(.*)</body>", h, re.S).group(1))
home, dash, imp = body("/"), body("/dashboard"), body("/importacao")
q = db.conn(); codes = {r[0]: r[1] for r in q.execute("SELECT product_id,group_concat(code,' ') FROM codes GROUP BY product_id")}
apps = {r[0]: r[1][:140] for r in q.execute("SELECT product_id,group_concat(DISTINCT coalesce(make,'')||' '||coalesce(model,'')||' '||coalesce(application_text,'')) FROM applications GROUP BY product_id")}
P = [[r["perfect_code"], r["description"] or "", codes.get(r["id"], ""), apps.get(r["id"], "")] for r in q.execute("SELECT id,perfect_code,description FROM products")]
for r in q.execute("SELECT code,suggestion,MAX(description) d,MAX(vehicle) v,MAX(status) s FROM rd_projects GROUP BY code,suggestion"): P.append([r["code"], (r["d"] or ""), "", " ".join(x for x in (r["v"], r["s"]) if x), r["suggestion"]])
pj = json.dumps(P, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
css = open("static/css/style.css").read()
html = f'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>PERFECT Shock Data</title><style>:root{{color-scheme:dark}}{css}
.pv-bar{{position:fixed;right:12px;bottom:12px;z-index:9;background:#121b25;border:1px solid var(--line);border-radius:8px;padding:8px 12px;font-size:12px;color:var(--mut);max-width:270px}}</style></head>
<body class="homebody" style="position:relative"><div id="v-home">{home}</div><div id="v-dash" hidden>{dash}</div><div id="v-imp" hidden>{imp}</div>
<div class="pv-bar" id="pv">Prévia com seus dados reais (somente leitura). O sistema completo roda no PC.</div>
<script>
const S={json.dumps(S)},P={pj};
const V={{"/":["v-home","homebody"],"/dashboard":["v-dash",""],"/importacao":["v-imp",""]}};
function go(p){{const v=V[p];if(!v){{document.getElementById("pv").textContent="Página ainda não implementada.";return}}
 for(const k in V)document.getElementById(V[k][0]).hidden=V[k][0]!==v[0];document.body.className=v[1];scrollTo(0,0)}}
document.addEventListener("click",e=>{{const a=e.target.closest("a[href^='/']");if(a){{e.preventDefault();go(a.getAttribute("href"))}}}});
document.querySelectorAll("[data-stat]").forEach(n=>n.textContent=S[n.dataset.stat]??0);
document.getElementById("v-dash").querySelector("#empty").hidden=S.products>0;
document.querySelectorAll("#v-imp input,#v-imp select,#v-imp button").forEach(n=>n.disabled=true);
const v=document.getElementById("hero-video"),still=()=>{{const i=new Image();i.src=v.dataset.fallback;i.alt="Amortecedor PERFECT";v.replaceWith(i)}};
if(matchMedia("(prefers-reduced-motion: reduce)").matches)still();else{{v.addEventListener("error",still,true);v.play().catch(()=>{{}})}}
const q=document.getElementById("quick"),ul=document.getElementById("quick-results");
document.querySelector("form.quick").addEventListener("submit",e=>e.preventDefault());
q.addEventListener("input",()=>{{const t=q.value.trim().toLowerCase();if(t.length<2){{ul.innerHTML="";return}}
 const r=P.filter(p=>p.join(" ").toLowerCase().includes(t)).sort((a,b)=>(a[4]?1:0)-(b[4]?1:0)).slice(0,12);
 ul.innerHTML=r.length?r.map(p=>"<li><span class=\\"tag "+(p[4]?p[4].replace("-",""):"cat")+"\\">"+(p[4]||"Catálogo")+"</span> <b>"+p[0]+"</b> "+p[1]+(p[3]?" — "+p[3]:"")+"</li>").join(""):"<li>Nenhum resultado.</li>"}});
</script></body></html>'''
open(sys.argv[1] if len(sys.argv) > 1 else "preview.html", "w").write(html); print(len(html) // 1024, "KB")
