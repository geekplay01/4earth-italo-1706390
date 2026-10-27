"""Módulos 'Em desenvolvimento' (DES = item novo) e 'Em redesenvolvimento' (R-D), a partir da planilha DadosR-D e DES.
Item = código distinto dentro do tipo. Um código pode ter várias linhas (aplicações) e pode existir em DES e R-D ao mesmo tempo."""
import database as db
from queries import q, q1

KINDS = {"des": "DES", "rd": "R-D"}

def _where(kind, f):
    w, p = ["r.suggestion=:kind"], {"kind": kind}
    for i, t in enumerate((f.get("q") or "").split()):
        w.append(f"(r.code LIKE :t{i} OR r.description LIKE :t{i} OR r.make LIKE :t{i} OR r.vehicle LIKE :t{i} OR r.application_text LIKE :t{i} OR r.supplier LIKE :t{i})"); p[f"t{i}"] = f"%{t}%"
    if f.get("make"): w.append("upper(trim(r.make))=upper(trim(:make))"); p["make"] = f["make"]
    if f.get("model"): w.append("upper(trim(r.vehicle))=upper(trim(:model))"); p["model"] = f["model"]
    if (f.get("year") or "").isdigit(): w.append("r.year_from<=:year AND coalesce(r.year_to,9999)>=:year"); p["year"] = int(f["year"])
    for k, col in (("status", "status"), ("drawing", "drawing_substatus"), ("validation", "validation_substatus"), ("supplier", "supplier")):
        if f.get(k): w.append(f"r.{col}=:{k}"); p[k] = f[k]
    if f.get("catalog") == "sim": w.append("r.product_id IS NOT NULL")
    if f.get("catalog") == "nao": w.append("r.product_id IS NULL")
    s = f.get("sample")
    if s == "comprada": w.append("r.sample_bought IS NOT NULL")
    elif s == "enviada": w.append("r.sample_sent IS NOT NULL")
    elif s == "nenhuma": w.append("r.sample_bought IS NULL AND r.sample_sent IS NULL")
    return " AND ".join(w), p

def _j(v): return (v or "").replace(",", " · ")

def items(kind, f):
    w, p = _where(kind, f)
    size = 10**9 if f.get("all") else 50; off = 0 if f.get("all") else (max(int(f.get("page") or 1), 1) - 1) * size
    total = q1(f"SELECT COUNT(DISTINCT r.code) n FROM rd_projects r WHERE {w}", p)["n"]
    rows = q(f"""SELECT r.code,MAX(r.description) description,MAX(r.product_id) product_id,COUNT(*) n_rows,group_concat(DISTINCT r.make) makes,group_concat(DISTINCT r.vehicle) vehicles,
        group_concat(DISTINCT r.status) statuses,group_concat(DISTINCT r.drawing_substatus) drawing,group_concat(DISTINCT r.validation_substatus) validation,group_concat(DISTINCT r.supplier) suppliers,
        MAX(substr(r.sample_bought,1,10)) bought,MAX(substr(r.sample_sent,1,10)) sent,
        EXISTS(SELECT 1 FROM rd_projects o WHERE o.code=r.code AND o.suggestion<>:kind) also_other
        FROM rd_projects r WHERE {w} GROUP BY r.code ORDER BY r.code LIMIT {size} OFFSET {off}""", p)
    for r in rows:
        for k in ("makes", "vehicles", "statuses", "drawing", "validation", "suppliers"): r[k] = _j(r[k])
    return {"total": total, "rows": rows, "size": size, "kind": KINDS.get(kind, kind)}

def facets(kind):
    g = lambda col: q(f"SELECT {col} v,COUNT(DISTINCT code) n FROM rd_projects WHERE suggestion=? AND {col} IS NOT NULL AND trim({col})<>'' GROUP BY {col} ORDER BY n DESC", (kind,))
    tot = q1("SELECT COUNT(DISTINCT code) n,COUNT(*) l FROM rd_projects WHERE suggestion=?", (kind,))
    return {"status": g("status"), "drawing": g("drawing_substatus"), "validation": g("validation_substatus"), "supplier": g("supplier"), "make": g("make"), "total": tot["n"], "lines": tot["l"]}

def detail(kind, code):
    rows = q("SELECT make,vehicle,application_text,year_from,year_to,status,drawing_substatus,validation_substatus,supplier,substr(sample_bought,1,10) bought,substr(sample_sent,1,10) sent,description,product_id FROM rd_projects WHERE code=? AND suggestion=? ORDER BY make,vehicle,year_from", (code, kind))
    if not rows: return None
    pid = max([r["product_id"] for r in rows if r["product_id"]] or [0])
    return {"code": code, "kind": kind, "description": next((r["description"] for r in rows if r["description"]), None), "rows": rows,
            "other": q("SELECT suggestion,COUNT(*) n FROM rd_projects WHERE code=? AND suggestion<>? GROUP BY suggestion", (code, kind)),
            "product": q1("SELECT id,perfect_code,description FROM products WHERE id=?", (pid,)) if pid else None,
            "samples": q("SELECT id,sc_number,sample_code,supplier,stage FROM sample_orders WHERE perfect_code=? OR sample_code=?", (code, code)),
            "damping": q("SELECT id,test_date FROM damping_tests WHERE perfect_code=?", (code,))}

def filter_lists(make=None):
    mk = [r["m"] for r in q("SELECT DISTINCT upper(trim(make)) m FROM (SELECT make FROM applications UNION ALL SELECT make FROM rd_projects) WHERE make IS NOT NULL AND trim(make)<>'' ORDER BY m")]
    a = {"mk": make} if make else {}
    mw = "AND upper(trim(make))=upper(:mk)" if make else ""
    models = [r["m"] for r in q(f"SELECT DISTINCT upper(trim(m)) m FROM (SELECT make,model m FROM applications UNION ALL SELECT make,vehicle FROM rd_projects) WHERE m IS NOT NULL AND trim(m)<>'' {mw} ORDER BY m", a)]
    y = q1("SELECT MIN(y1) a,MAX(y2) b FROM (SELECT year_from y1,coalesce(year_to,year_from) y2 FROM applications UNION ALL SELECT year_from,coalesce(year_to,year_from) FROM rd_projects) WHERE y1>=1950 AND y2<=2040")
    return {"makes": mk, "models": models, "years": list(range(y["b"], y["a"] - 1, -1)) if y and y["a"] else []}

def quick(term, limit=5):
    like = f"%{term.strip()}%"
    prods = q("""SELECT DISTINCT p.perfect_code code,p.description FROM products p LEFT JOIN codes k ON k.product_id=p.id LEFT JOIN applications a ON a.product_id=p.id
        WHERE p.perfect_code LIKE ?1 OR p.description LIKE ?1 OR k.code LIKE ?1 OR a.make LIKE ?1 OR a.model LIKE ?1 ORDER BY p.catalog_position LIMIT ?2""", (like, limit))
    out = [{"kind": "Catálogo", "code": r["code"], "text": r["description"], "url": "/pesquisa?q=" + r["code"]} for r in prods]
    for k, label, slug in (("DES", "DES", "desenvolvimento"), ("R-D", "R-D", "redesenvolvimento")):
        rs = q("""SELECT code,MAX(description) d,MAX(vehicle) v,MAX(status) s FROM rd_projects WHERE suggestion=?1 AND (code LIKE ?2 OR description LIKE ?2 OR vehicle LIKE ?2 OR make LIKE ?2 OR application_text LIKE ?2)
            GROUP BY code ORDER BY code LIMIT ?3""", (k, like, limit))
        out += [{"kind": label, "code": r["code"], "text": " · ".join(x for x in (r["d"], r["v"], r["s"]) if x), "url": f"/{slug}?q=" + r["code"]} for r in rs]
    return out
