"""Etapa 2 (parte 2): gravação da importação. Um único transação: simulação = rollback; confirmação = commit.
Política padrão: campos vazios são preenchidos; valores divergentes NÃO sobrescrevem (viram pendência 'conflito').
Tabelas sem chave natural: ao reimportar a mesma fonte, as linhas anteriores DESSA fonte são substituídas."""
import re, json
import database as db
from importer import read_table, normalize_code

KINDS = [("amostras", {"sample_code", "sc_number"}), ("caixas", {"box_code", "box_dims_mm"}), ("estrutura", {"parent_code", "component_code"}),
         ("lados", {"rh_code", "lh_code"}), ("fornecedor_erp", {"erp_code", "supplier_code"}),
         ("desenvolvimento", {"rd_kind"}), ("certificados", {"perfect_code", "inmetro_number"}),
         ("de_para", {"perfect_code", "zs_code"}), ("oem", {"perfect_code", "oem_code"}),
         ("catalogo", {"perfect_code", "description"})]
LABEL = {"amostras": "Compra de amostras", "caixas": "Tipos de caixa", "estrutura": "Estrutura de produto", "lados": "Pares direito/esquerdo",
         "fornecedor_erp": "Cadastro de fornecedor (ERP)", "desenvolvimento": "Desenvolvimento / aplicações",
         "certificados": "Certificados Inmetro", "de_para": "De-para fornecedor × PERFECT", "oem": "Códigos OEM e aplicações", "catalogo": "Catálogo de produtos"}

def _s(v):
    v = None if v is None else str(v).strip()
    return v or None
def _f(v):
    try: return float(str(v).strip().replace(",", "."))
    except (TypeError, ValueError): return None
def _i(v):
    f = _f(v); return int(f) if f is not None else None

class Ctx:
    def __init__(s, c, src, name, policy="keep", sync=False):
        s.c, s.src, s.name, s.msgs, s.policy, s.sync = c, src, name, [], policy, sync
        s.n = dict(new=0, updated=0, replaced=0, conflicts=0, duplicates=0, unmatched=0, errors=0, pendencies=0, relinked=0, present=0)
        s.pid = {r[0]: r[1] for r in c.execute("SELECT perfect_code,id FROM products")}
        # modo sync: o que já está no banco é conhecido e nunca apagado; só entra o que falta
        s.known = {(r[0], r[1], r[2]) for r in c.execute("SELECT product_id,normalized_code,code_type FROM codes")} if sync else set()
    def of(s, raw):
        n, _ = normalize_code(raw); return s.pid.get(n) if n else None
    def err(s, m):
        s.n["errors"] += 1
        if len(s.msgs) < 12: s.msgs.append(m)
    def unlink(s, kind, code, row, reason):
        s.n["unmatched"] += 1
        s.c.execute("INSERT INTO unlinked_rows(kind,source_id,code,payload,reason) VALUES(?,?,?,?,?)", (kind, s.src, code, json.dumps(row, ensure_ascii=False), reason))
    def reset_unlinked(s, kind):   # linhas sem vínculo são recalculadas a cada leitura (nunca perdem dados do banco)
        s.c.execute("DELETE FROM unlinked_rows WHERE source_id=? AND kind=?", (s.src, kind))
    def replace(s, table):
        if s.sync: return
        s.n["replaced"] += s.c.execute(f"DELETE FROM {table} WHERE source_id=?", (s.src,)).rowcount
    def add_code(s, pid, raw, ctype, brand=None, seen=None):
        norm, _ = normalize_code(raw)
        if not norm: return False
        if s.sync and (pid, norm, ctype) in s.known: s.n["present"] += 1; return False
        if seen is not None and (pid, norm, ctype) in seen: return False
        if seen is not None: seen.add((pid, norm, ctype))
        s.known.add((pid, norm, ctype))
        s.c.execute("INSERT INTO codes(product_id,code,normalized_code,code_type,brand,source_id) VALUES(?,?,?,?,?,?)", (pid, raw, norm, ctype, brand, s.src)); return True

def _merge(x, pid, vals):
    cur = x.c.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone(); sets = {}
    for k, v in vals.items():
        if v is None: continue
        old = cur[k]
        if old is None: sets[k] = v
        elif str(old) != str(v) and x.policy == "overwrite": sets[k] = v   # regra escolhida: a planilha prevalece
        elif str(old) != str(v):
            x.n["conflicts"] += 1
            x.c.execute("DELETE FROM pendencies WHERE product_id=? AND kind='conflito' AND field=? AND status='aberta'", (pid, k))
            x.c.execute("INSERT INTO pendencies(product_id,kind,field,description) VALUES(?,?,?,?)",
                        (pid, "conflito", k, f"Valor atual «{old}» × importado «{v}» (fonte {x.name}). Nada foi sobrescrito."))
    if sets:
        x.c.execute(f"UPDATE products SET {','.join(k + '=?' for k in sets)},updated_at=CURRENT_TIMESTAMP WHERE id=?", [*sets.values(), pid]); x.n["updated"] += 1

def _axle_side(desc):
    d = (desc or "").upper(); ax = "dianteiro" if "DIANT" in d else "traseiro" if "TRAS" in d else None
    sd = "ambos" if re.search(r"LD\s*/\s*LE|LE\s*/\s*LD", d) else "direito" if re.search(r"\bLD\b", d) else "esquerdo" if re.search(r"\bLE\b", d) else None
    return ax, sd

def _relink(x):
    """Linhas guardadas sem vínculo (de-para, lados) são ligadas automaticamente quando o produto passa a existir no catálogo."""
    for u in x.c.execute("SELECT * FROM unlinked_rows WHERE kind IN ('de_para','lados')").fetchall():
        r = json.loads(u["payload"]); ok = False
        if u["kind"] == "de_para" and "suspeito" not in (u["reason"] or ""):
            pid, z = x.of(r.get("perfect_code")), _s(r.get("zs_code"))
            if pid and z:
                nz, _ = normalize_code(z)
                x.c.execute("INSERT INTO codes(product_id,code,normalized_code,code_type,brand,source_id) VALUES(?,?,?,?,?,?)", (pid, z, nz, "fornecedor", "ZS", u["source_id"])); ok = True
        elif u["kind"] == "lados":
            a, b = x.of(r.get("rh_code")), x.of(r.get("lh_code"))
            if a and b: x.c.execute("INSERT OR IGNORE INTO side_pairs(right_product_id,left_product_id,source_id) VALUES(?,?,?)", (a, b, u["source_id"])); ok = True
        if ok: x.c.execute("DELETE FROM unlinked_rows WHERE id=?", (u["id"],)); x.n["relinked"] += 1

def L_catalogo(x, rows):
    for pos, r in enumerate(rows, 1):  # posição no catálogo = ordem das linhas da planilha
        code, _ = normalize_code(r.get("perfect_code"))
        if not code: x.err("linha sem código PERFECT"); continue
        v = {"description": _s(r.get("description")), "description_es": _s(r.get("description_es")), "description_en": _s(r.get("description_en")),
             "ean": _s(r.get("ean")), "ncm": _s(r.get("ncm")), "weight_kg": _f(r.get("weight_kg")), "catalog_group": _s(r.get("group_name"))}
        obs = _s(r.get("observation")) or ""
        m = re.search(r"Sistema\.?:\s*(.+)", obs, re.I)
        if m:
            u = m.group(1).upper(); v["features"] = "Sistema: " + m.group(1).strip()
            v["system_type"] = "gas" if re.search(r"G[ÁA]S", u) else "oleo" if re.search(r"[ÓO]LEO", u) else None
        m = re.search(r"Medida emb\.?:\s*(.+)", obs, re.I)
        if m: v["package_note"] = m.group(1).strip()
        pid = x.pid.get(code)
        if pid is None:
            cols = [k for k, val in v.items() if val is not None]
            pid = x.c.execute(f"INSERT INTO products(perfect_code{''.join(',' + k for k in cols)}) VALUES(?{',?' * len(cols)})", [code] + [v[k] for k in cols]).lastrowid
            x.pid[code] = pid; x.n["new"] += 1
        else: _merge(x, pid, v); x.n["present"] += 1
        x.c.execute("UPDATE products SET catalog_position=? WHERE id=?", (pos, pid))
        mm = re.search(r"MIN:\s*(\d+).*?M[ÁA]X:\s*(\d+)", _s(r.get("measure_min_max")) or "", re.I)
        if mm: x.c.execute("INSERT INTO dimensions(product_id,lmin_mm,lmax_mm,source_id) VALUES(?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET lmin_mm=excluded.lmin_mm,lmax_mm=excluded.lmax_mm,source_id=excluded.source_id",
                           (pid, float(mm.group(1)), float(mm.group(2)), x.src))
    _relink(x)
    x.c.execute("DELETE FROM pendencies WHERE kind='campo_ausente' AND status='aberta'")
    for fld, cond, fr in [("Lmin/Lmax", "d.lmin_mm IS NULL OR d.lmax_mm IS NULL", "LEFT JOIN dimensions d ON d.product_id=p.id"),
                          ("peso", "p.weight_kg IS NULL", ""), ("EAN", "p.ean IS NULL", "")]:
        x.n["pendencies"] += x.c.execute(f"INSERT INTO pendencies(product_id,kind,field,description) SELECT p.id,'campo_ausente','{fld}','Campo ausente: {fld}' FROM products p {fr} WHERE {cond}").rowcount

RD_KEY = ("code", "suggestion", "make", "vehicle", "application_text", "year_from", "year_to")
RD_UPD = ("status", "drawing_substatus", "validation_substatus", "supplier", "sample_bought", "sample_sent", "description", "product_id")

def L_desenvolvimento(x, rows):
    x.replace("rd_projects"); x.replace("applications"); seen = set()
    have_apps = {tuple(r) for r in x.c.execute("SELECT product_id,make,model,application_text,year_from,year_to,axle,side FROM applications")} if x.sync else set()
    existing = {}
    if x.sync:   # linhas já cadastradas, agrupadas pela chave natural (cada ocorrência da chave casa com uma linha do banco)
        for r in x.c.execute("SELECT id,%s,%s FROM rd_projects" % (",".join(RD_KEY), ",".join(RD_UPD))).fetchall():
            existing.setdefault(tuple(r[k] for k in RD_KEY), []).append(r)
    used = {}
    for r in rows:
        code = _s(r.get("perfect_code") or r.get("parent_code"))
        if not code: x.err("linha sem código"); continue
        pid = x.of(code); yf, yt = _i(r.get("year_from")), _i(r.get("year_to"))
        vals = dict(code=code, suggestion=_s(r.get("rd_kind")), make=_s(r.get("make")), vehicle=_s(r.get("vehicle")), application_text=_s(r.get("application")), year_from=yf, year_to=yt,
                    status=_s(r.get("status")), drawing_substatus=_s(r.get("sub_status_drawing")), validation_substatus=_s(r.get("sub_status_validation")), supplier=_s(r.get("supplier")),
                    sample_bought=_s(r.get("sample_bought")), sample_sent=_s(r.get("sample_sent")), description=_s(r.get("description")), product_id=pid)
        key = tuple(vals[k] for k in RD_KEY); hit = None
        if x.sync:
            n = used.get(key, 0); used[key] = n + 1; lst = existing.get(key, [])
            hit = lst[n] if n < len(lst) else None
        if hit is not None:   # já existe: só atualiza o que mudou na planilha (status, fornecedor, amostras...)
            ch = {k: vals[k] for k in RD_UPD if vals[k] is not None and str(hit[k]) != str(vals[k])}
            if ch:
                x.c.execute("UPDATE rd_projects SET " + ",".join(k + "=?" for k in ch) + " WHERE id=?", [*ch.values(), hit["id"]]); x.n["updated"] += 1
            else: x.n["present"] += 1
        else:
            x.c.execute("INSERT INTO rd_projects(code,product_id,suggestion,status,drawing_substatus,validation_substatus,supplier,sample_bought,sample_sent,make,vehicle,application_text,year_from,year_to,description,source_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (code, pid, vals["suggestion"], vals["status"], vals["drawing_substatus"], vals["validation_substatus"], vals["supplier"], vals["sample_bought"], vals["sample_sent"], vals["make"], vals["vehicle"],
                         vals["application_text"], yf, yt, vals["description"], x.src))
            x.n["new"] += 1
        if not pid: x.n["unmatched"] += 1; continue
        ax, sd = _axle_side(_s(r.get("description")))
        key = (pid, _s(r.get("make")), _s(r.get("vehicle")), _s(r.get("application")), yf, yt, ax, sd)
        if key in seen or tuple(key) in have_apps: x.n["duplicates"] += (key in seen); continue
        seen.add(key)
        x.c.execute("INSERT INTO applications(product_id,make,model,application_text,year_from,year_to,axle,side,source_id) VALUES(?,?,?,?,?,?,?,?,?)", (pid, key[1], key[2], key[3], yf, yt, ax, sd, x.src))

def L_oem(x, rows):
    x.replace("codes"); x.replace("applications"); x.replace("unlinked_rows")
    if x.sync: x.reset_unlinked("oem")
    seen = set()
    have = {(r[0], r[1], r[2], r[3], r[4]) for r in x.c.execute("SELECT product_id,model,application_text,year_from,year_to FROM applications")} if x.sync else set()
    for r in rows:
        pid = x.of(r.get("perfect_code"))
        if not pid: x.unlink("oem", _s(r.get("perfect_code")), r, "código PERFECT não está no catálogo"); continue
        for f in ("oem_code", "oem_code_alt", "oem_code_proj"):
            raw = _s(r.get(f))
            if raw and raw != "-":
                if x.add_code(pid, raw, "oem", seen=seen) and x.sync: x.n["new"] += 1
        yr = (_s(r.get("year_range")) or "").split("/"); yf, yt = (_i(yr[0]), _i(yr[-1])) if yr[0] else (None, None)
        ak = (pid, _s(r.get("vehicle")), _s(r.get("application")), yf, yt)
        if ak in have: x.n["present"] += 1
        else:
            have.add(ak)
            x.c.execute("INSERT INTO applications(product_id,model,application_text,year_from,year_to,source_id) VALUES(?,?,?,?,?,?)", (pid, ak[1], ak[2], yf, yt, x.src)); x.n["new"] += 1
        _merge(x, pid, {"family": (_s(r.get("family")) or "").upper() or None, "package_code": _s(r.get("box_code"))})

def L_de_para(x, rows):
    x.replace("codes"); x.replace("unlinked_rows")
    if x.sync: x.reset_unlinked("de_para")
    seen = set()
    for r in rows:
        z = _s(r.get("zs_code"))
        if not z: x.err("linha sem código de fornecedor"); continue
        pid = x.of(r.get("perfect_code"))
        if len(z) > 30 or " " in z: x.unlink("de_para", _s(r.get("perfect_code")), r, "código de fornecedor suspeito (guardado sem vínculo)"); continue
        if not pid: x.unlink("de_para", _s(r.get("perfect_code")), r, "código PERFECT não está no catálogo"); continue
        if (pid, z) in seen: x.n["duplicates"] += 1; continue
        seen.add((pid, z))
        if x.add_code(pid, z, "fornecedor", "ZS", seen): x.n["new"] += 1

def L_fornecedor_erp(x, rows):
    x.replace("supplier_items"); x.replace("codes"); seen = set()
    have = {(r[0], r[1], r[2], r[3]) for r in x.c.execute("SELECT supplier_name,erp_code,supplier_code,supplier_code2 FROM supplier_items")} if x.sync else set()
    for r in rows:
        pid = x.of(r.get("supplier_code")); sup = _s(r.get("supplier_name"))
        k = (sup, _s(r.get("erp_code")), _s(r.get("supplier_code")), _s(r.get("supplier_code2")))
        if k in have: x.n["present"] += 1
        else:
            have.add(k)
            x.c.execute("INSERT INTO supplier_items(supplier_name,erp_code,item_type,supplier_code,supplier_code2,description,product_id,source_id) VALUES(?,?,?,?,?,?,?,?)",
                        (sup, _s(r.get("erp_code")), _s(r.get("item_type")), _s(r.get("supplier_code")), _s(r.get("supplier_code2")), _s(r.get("description")), pid, x.src)); x.n["new"] += 1
            if not pid: x.n["unmatched"] += 1
        if pid and _s(r.get("supplier_code2")): x.add_code(pid, _s(r.get("supplier_code2")), "fornecedor", sup, seen)

def L_certificados(x, rows):
    x.replace("certificates")
    have = {(r[0], r[1], r[2]) for r in x.c.execute("SELECT perfect_code_raw,inmetro_number,cert_description FROM certificates")} if x.sync else set()
    for r in rows:
        pid = x.of(r.get("perfect_code")); fam = (_s(r.get("family")) or "").upper() or None
        k = (_s(r.get("perfect_code")), _s(r.get("inmetro_number")), _s(r.get("description")))
        if k in have: x.n["present"] += 1; continue
        have.add(k)
        x.c.execute("INSERT INTO certificates(product_id,perfect_code_raw,inmetro_number,family,cert_description,source_id) VALUES(?,?,?,?,?,?)",
                    (pid, k[0], k[1], fam, k[2], x.src)); x.n["new"] += 1
        if not pid: x.n["unmatched"] += 1; continue
        _merge(x, pid, {"ean": _s(r.get("ean")), "family": fam})  # nº Inmetro fica só em certificates (um por fornecedor)

def L_estrutura(x, rows):
    x.replace("product_components")
    have = {(r[0], r[1], r[2], r[3]) for r in x.c.execute("SELECT parent_code,component_code,seq,date_from FROM product_components")} if x.sync else set()
    for r in rows:
        par, comp = _s(r.get("parent_code")), _s(r.get("component_code"))
        if not par or not comp: x.err("linha sem pai ou componente"); continue
        pid = x.of(par); k = (par, comp, _i(r.get("seq")), _s(r.get("date_from")))
        if k in have: x.n["present"] += 1; continue
        have.add(k)
        x.c.execute("INSERT INTO product_components(parent_code,product_id,component_code,component_desc,seq,qty,date_from,date_to,source_id) VALUES(?,?,?,?,?,?,?,?,?)",
                    (par, pid, comp, _s(r.get("component_desc")), k[2], _f(r.get("qty")), k[3], _s(r.get("date_to")), x.src)); x.n["new"] += 1
        if not pid: x.n["unmatched"] += 1
        elif comp.upper().startswith("PP"): _merge(x, pid, {"package_code": comp})

def L_lados(x, rows):
    x.replace("side_pairs"); x.replace("unlinked_rows")
    if x.sync: x.reset_unlinked("lados")
    for r in rows:
        a, b = x.of(r.get("rh_code")), x.of(r.get("lh_code"))
        if a and b:
            if x.c.execute("INSERT OR IGNORE INTO side_pairs(right_product_id,left_product_id,source_id) VALUES(?,?,?)", (a, b, x.src)).rowcount: x.n["new"] += 1
            else: x.n["present"] += 1
        else: x.unlink("lados", _s(r.get("rh_code")), r, "um dos códigos não está no catálogo")

def L_caixas(x, rows):
    for r in rows:
        code, dims = _s(r.get("box_code")), _s(r.get("box_dims_mm"))
        m = re.fullmatch(r"(\d+)x(\d+)x(\d+)", dims or "")
        if not code or not m: x.err(f"caixa {code}: dimensão em mm ilegível ({dims})"); continue
        L, W, H = map(float, m.groups())
        ex = x.c.execute("SELECT 1 FROM packaging_boxes WHERE code=?", (code,)).fetchone()
        if ex and x.sync: x.n["present"] += 1; continue
        x.c.execute("INSERT INTO packaging_boxes(code,length_mm,width_mm,height_mm,raw_dims,source_id) VALUES(?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET length_mm=excluded.length_mm,width_mm=excluded.width_mm,height_mm=excluded.height_mm,raw_dims=excluded.raw_dims,source_id=excluded.source_id", (code, L, W, H, dims, x.src))
        x.n["updated" if ex else "new"] += 1
        cm = _s(r.get("box_dims_cm"))
        if cm:
            try: ok = [float(t.replace(",", ".")) for t in cm.split("x")] == [round(L / 10, 1), round(W / 10, 1), round(H / 10, 1)]
            except ValueError: ok = False
            if not ok and len(x.msgs) < 12: x.msgs.append(f"Aviso {code}: {dims} mm × coluna cm «{cm}». Usado o valor em mm.")

def _yes(v): return str(v or "").strip().upper() in ("SIM", "S", "1", "TRUE")

SAMPLE_FILL = (("ship_code", "ship_code"), ("sc_number", "sc_number"), ("application", "application"), ("supplier", "supplier"), ("month", "month"), ("tracking", "tracking"), ("credit_note", "credit_note"))

def L_amostras(x, rows):
    x.replace("sample_orders"); existing, used = {}, {}
    if x.sync:   # identidade da amostra = código PERFECT + código da amostra (o resto pode mudar ao longo do projeto)
        for r in x.c.execute("SELECT * FROM sample_orders").fetchall():
            existing.setdefault((r["perfect_code"] or "", r["sample_code"] or ""), []).append(r)
    for r in rows:
        pc, sc = _s(r.get("perfect_code")), _s(r.get("sample_code"))
        if not (pc or sc): continue
        k = (pc or "", sc or ""); n = used.get(k, 0); used[k] = n + 1; lst = existing.get(k, [])
        if x.sync and n < len(lst):   # já existe: preenche só campos vazios; etapa e edições feitas no sistema são preservadas
            cur = lst[n]; ch = {c: _s(r.get(f)) for f, c in SAMPLE_FILL if cur[c] in (None, "") and _s(r.get(f))}
            for f, c in (("net_weight", "net_weight"), ("gross_weight", "gross_weight")):
                if cur[c] is None and _f(r.get(f)) is not None: ch[c] = _f(r.get(f))
            if cur["side"] is None and db.side_from_text(_s(r.get("application"))): ch["side"] = db.side_from_text(_s(r.get("application")))
            if ch:
                x.c.execute("UPDATE sample_orders SET " + ",".join(c + "=?" for c in ch) + ",updated_at=CURRENT_TIMESTAMP WHERE id=?", [*ch.values(), cur["id"]]); x.n["updated"] += 1
            else: x.n["present"] += 1
            continue
        stage = "aprovado" if _yes(r.get("approved")) else "finalizado" if _yes(r.get("finished")) else "chegou" if _yes(r.get("arrived")) else "sc_aberta" if _yes(r.get("sc_open")) else "cotacao"
        ship = _s(r.get("ship_code")) or (("D-" + pc) if pc else None)
        oid = x.c.execute("INSERT INTO sample_orders(product_id,perfect_code,ship_code,sc_number,application,sample_code,supplier,month,tracking,net_weight,gross_weight,credit_note,stage,to_send,pending_supplier,side,source_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (x.of(pc), pc, ship, _s(r.get("sc_number")), _s(r.get("application")), sc, _s(r.get("supplier")), _s(r.get("month")), _s(r.get("tracking")),
             _f(r.get("net_weight")), _f(r.get("gross_weight")), _s(r.get("credit_note")), stage, int(_yes(r.get("to_send"))), int(_yes(r.get("pending_des"))), db.side_from_text(_s(r.get("application"))), x.src)).lastrowid
        x.n["new"] += 1
        for i in (1, 2, 3):
            pr, lk = _f(r.get(f"price{i}")), _s(r.get(f"link{i}"))
            if pr is not None or (lk and lk != "-"): x.c.execute("INSERT INTO sample_quotes(order_id,price,link,chosen) VALUES(?,?,?,?)", (oid, pr, None if lk == "-" else lk, int(i == 1)))
        if not x.of(pc): x.n["unmatched"] += 1

LOADERS = {"amostras": L_amostras, "caixas": L_caixas, "estrutura": L_estrutura, "lados": L_lados, "fornecedor_erp": L_fornecedor_erp, "desenvolvimento": L_desenvolvimento,
           "certificados": L_certificados, "de_para": L_de_para, "oem": L_oem, "catalogo": L_catalogo}

def run(path, sheet, mapping, category, filename, confirm, policy="keep", sync=False, conn=None):
    """Simula (confirm=False -> rollback) ou grava (confirm=True). Retorna o resumo."""
    mapping = {c: f for c, f in (mapping or {}).items() if f}
    fields = list(mapping.values()); dup = sorted({f for f in fields if fields.count(f) > 1})
    if dup: raise ValueError("Campo mapeado em mais de uma coluna: " + ", ".join(dup))
    kind = next((k for k, req in KINDS if req <= set(fields)), None)
    if not kind: raise ValueError("Mapeamento insuficiente para reconhecer o tipo de dado. Mapeie ao menos o código e um campo característico (ex.: descrição, RH/LH, inmetro, componente).")
    df, _ = read_table(path, None if sheet in (None, "", "(csv)") else sheet)
    miss = [c for c in mapping if c not in df.columns]
    if miss: raise ValueError("Colunas não encontradas na planilha: " + ", ".join(miss))
    rows = df[list(mapping)].rename(columns=mapping).fillna("").to_dict("records")
    name = filename + (f" [{sheet}]" if sheet and sheet != "(csv)" else "")
    own = conn is None; conn = conn or db.conn()
    try:
        norm = lambda s: re.sub(r"[\s_]+", " ", s.lower()).strip()   # 'DadosR-D_e_DES.xlsx' == 'DadosR-D e DES.xlsx' (mesma fonte, nova versão)
        r = next(((i,) for i, n_ in conn.execute("SELECT id,name FROM sources") if norm(n_) == norm(name)), None)
        src = r[0] if r else conn.execute("INSERT INTO sources(name,category) VALUES(?,?)", (name, category or LABEL[kind])).lastrowid
        x = Ctx(conn, src, name, policy, sync); LOADERS[kind](x, rows)
        n = x.n; bid = conn.execute("INSERT INTO import_batches(source_id,filename,sheet,category,rows_new,rows_updated,rows_conflict,rows_error,rows_read,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (src, filename, sheet, category or LABEL[kind], n["new"], n["updated"], n["conflicts"], n["errors"], len(rows), "ok" if confirm else "simulado")).lastrowid
        if own: conn.commit() if confirm else conn.rollback()
        return {"kind": kind, "label": LABEL[kind], "rows": len(rows), "counts": n, "messages": x.msgs, "confirmed": confirm, "batch_id": bid if confirm else None}
    except Exception:
        if own: conn.rollback()
        raise
    finally:
        if own: conn.close()
