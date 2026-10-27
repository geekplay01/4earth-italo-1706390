"""Perfect Shock Data - rotas Flask."""
from flask import Flask, render_template, jsonify, request, abort, send_from_directory
import os, re, glob, uuid, shutil, datetime
import database as db, importer, loaders, queries, equivalence, damping, exporter, rd, updater

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024
UPLOADS = os.path.join(db.BASE, 'data', 'uploads')
CATEGORIES = ['Produtos / códigos', 'Aplicações', 'Dimensões técnicas', 'Fornecedores / concorrentes', 'Dados comerciais / logísticos', 'Personalizada']
db.init_db()

# slug, rótulo, ícone (path SVG 24x24), etapa em que será implementada
PAGES = [
 ("dashboard", "Dashboard", "M3 13h8V3H3zM13 21h8V11h-8zM3 21h8v-6H3zM13 3v6h8V3z", 1),
 ("pesquisa", "Pesquisa de amortecedores", "M11 4a7 7 0 105 12l4 4 1.5-1.5-4-4A7 7 0 0011 4z", 3),
 ("produtos", "Produtos e códigos", "M4 7l8-4 8 4v10l-8 4-8-4zM4 7l8 4 8-4M12 11v10", 3),
 ("aplicacoes", "Aplicações veiculares", "M5 16l1.5-5h11L19 16M4 16h16v3H4zM7 19v1.5M17 19v1.5", 3),
 ("comparacao", "Comparação técnica", "M8 4v16M16 4v16M3 8h5M16 14h5", 4),
 ("equivalencias", "Equivalências", "M7 7h11l-3-3M17 17H6l3 3", 4),
 ("atualizacao", "Atualização de dados", "M4 12a8 8 0 0114-5l2 2M20 4v5h-5M20 12a8 8 0 01-14 5l-2-2M4 20v-5h5", 2),
 ("importacao", "Importação de Excel", "M12 3v12M7 10l5 5 5-5M4 20h16", 2),
 ("desenvolvimento", "Em desenvolvimento", "M4 20l4-1 11-11-3-3L5 16zM14 6l3 3", 3),
 ("redesenvolvimento", "Em redesenvolvimento", "M4 4v6h6M20 20v-6h-6M20 10a8 8 0 00-14-3M4 14a8 8 0 0014 3", 3),
 ("amostras", "Compra de amostras", "M4 5h2l2 10h9l2-7H7M10 20a1 1 0 100-2 1 1 0 000 2zM17 20a1 1 0 100-2 1 1 0 000 2z", 3),
 ("damping", "Damping force", "M3 12h3l2-6 4 12 3-9 2 3h4", 3),
 ("pendencias", "Pendências de dados", "M12 3l10 18H2zM12 10v5M12 18v.5", 4),
 ("fontes", "Fontes e histórico", "M12 7v5l3 2M3 12a9 9 0 109-9", 2),
 ("configuracoes", "Configurações e backup", "M12 9a3 3 0 100 6 3 3 0 000-6zM19 12l2-1-2-4-2 1-2-1-1-2h-4l-1 2-2 1-2-1-2 4 2 1v2l-2 1 2 4 2-1 2 1 1 2h4l1-2 2-1 2 1 2-4-2-1z", 5),
]
CARDS = [  # chave, rótulo, destino, dica
 ("products", "Total de amortecedores", "produtos", "Produtos PERFECT cadastrados"),
 ("oem_codes", "Códigos OEM relacionados", "pesquisa?code_type=oem", "Códigos OEM distintos"),
 ("applications", "Aplicações cadastradas", "aplicacoes", "Veículo, modelo, ano e eixo"),
 ("des_items", "Em desenvolvimento (DES)", "desenvolvimento", "Itens novos distintos (planilha DadosR-D)"),
 ("rd_items", "Em redesenvolvimento (R-D)", "redesenvolvimento", "Itens distintos em redesenvolvimento"),
 ("imports", "Bases importadas", "fontes", "Planilhas já importadas"),
 ("pendencies", "Pendências técnicas", "pendencias", "Dados ausentes ou inconsistentes"),
 ("duplicates", "Possíveis duplicidades", "pendencias?tab=dup", "Mesmo código em produtos diferentes"),
 ("equivalences_pending", "Equivalências a validar", "equivalencias", "Sugestões aguardando decisão"),
]

@app.context_processor
def inject():
    return {"pages": PAGES}

@app.route("/")
def home():
    return render_template("home.html", s=db.stats())

@app.route("/<slug>")
def page(slug):
    p = next((x for x in PAGES if x[0] == slug), None)
    if not p: abort(404)
    return render_template("page.html", cur=p, cards=CARDS)

@app.get("/api/stats")
def api_stats(): return jsonify(db.stats())

@app.get("/api/quick-search")
def api_quick():
    q = request.args.get("q", "").strip()
    return jsonify(db.quick_search(q) if len(q) >= 2 else [])


# ---- Importação: upload, abas e prévia (nada é gravado no banco nesta etapa) ----
def _upload_path(fid):
    if not re.fullmatch(r"[0-9a-f]{32}", fid or ""): abort(400)
    m = glob.glob(os.path.join(UPLOADS, fid + "__*"))
    if not m: abort(404)
    return m[0]

@app.post("/api/import/upload")
def api_upload():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith((".xlsx", ".xls", ".csv")):
        return jsonify(error="Selecione um arquivo .xlsx, .xls ou .csv."), 400
    os.makedirs(UPLOADS, exist_ok=True)
    fid = uuid.uuid4().hex; name = re.sub(r"[^\w.\- ]", "_", os.path.basename(f.filename))
    path = os.path.join(UPLOADS, f"{fid}__{name}"); f.save(path)
    try: sheets = importer.list_sheets(path)
    except Exception as e:
        os.remove(path); return jsonify(error=f"Não foi possível abrir o arquivo: {e}"), 400
    return jsonify(file_id=fid, name=name, sheets=sheets, categories=CATEGORIES)

@app.get("/api/import/preview")
def api_preview():
    path = _upload_path(request.args.get("file_id")); sheet = request.args.get("sheet") or None
    try: p = importer.preview(path, sheet)
    except Exception as e: return jsonify(error=f"Erro ao ler a planilha: {e}"), 400
    p["fields"] = list(importer.ALIASES); return jsonify(p)

@app.post("/api/import/run")
def api_run():
    d = request.get_json(force=True); path = _upload_path(d.get("file_id")); fname = os.path.basename(path).split("__", 1)[1]
    confirm = bool(d.get("confirm")); backup = None
    if confirm and os.path.exists(db.DB_PATH):  # backup ANTES de gravar
        os.makedirs(os.path.join(db.BASE, "backups"), exist_ok=True)
        backup = os.path.join("backups", "pre_import_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".db")
        shutil.copy2(db.DB_PATH, os.path.join(db.BASE, backup))
    try: res = loaders.run(path, d.get("sheet"), d.get("mapping"), d.get("category"), fname, confirm, "overwrite" if d.get("policy") == "overwrite" else "keep")
    except ValueError as e: return jsonify(error=str(e)), 400
    except Exception as e: return jsonify(error=f"Erro na importação; o banco foi preservado. Detalhe: {e}"), 500
    res["backup"] = backup; return jsonify(res)

# ---- Atualização de dados: lê as planilhas, compara com o banco e insere só o que falta ----
@app.post("/api/update/check")
def api_upd_check():
    try:
        if request.form.get("folder"): files, tok = updater.folder_files(), "folder"
        else:
            tok, files = updater.stash(request.files.getlist("files"))
            if not files: return jsonify(error="Selecione planilhas .xlsx, .xls ou .csv."), 400
        if not files: return jsonify(error="A pasta bases_exemplo está vazia ou não existe."), 400
        res = updater.run(files, confirm=False); res["token"] = tok; return jsonify(res)
    except Exception as e: return jsonify(error=f"Erro ao verificar: {e}"), 500
@app.post("/api/update/apply")
def api_upd_apply():
    tok = (request.get_json(force=True) or {}).get("token")
    files = updater.folder_files() if tok == "folder" else updater.stashed(tok)
    if not files: return jsonify(error="Verificação expirada. Envie as planilhas novamente."), 400
    try: res = updater.run(files, confirm=True)
    except Exception as e: return jsonify(error=f"Erro na atualização; o banco foi preservado. Detalhe: {e}"), 500
    if tok != "folder": updater.discard(tok)
    return jsonify(res)

# ---- Consulta, fichas, comparação, equivalências, pendências, fontes, backup, amostras ----
A = lambda: request.args.to_dict()
@app.get("/api/products")
def api_products(): return jsonify(queries.products(A()))
@app.get("/api/products/<int:pid>")
def api_ficha(pid): return jsonify(queries.ficha(pid) or abort(404))
@app.get("/api/compare")
def api_compare(): return jsonify(queries.compare([int(i) for i in re.findall(r"\d+", request.args.get("ids", ""))]))
@app.get("/api/applications")
def api_apps(): return jsonify(queries.applications(A()))
@app.get("/api/pendencies")
def api_pend(): return jsonify(queries.pendencies(A()))
@app.post("/api/pendencies/<int:i>")
def api_pend_set(i):
    s = (request.get_json(force=True) or {}).get("status")
    if s not in ("aberta", "resolvida", "ignorada"): abort(400)
    queries.run("UPDATE pendencies SET status=? WHERE id=?", (s, i)); return jsonify(ok=True)
@app.get("/api/duplicates")
def api_dups(): return jsonify(queries.duplicates())
@app.get("/api/history")
def api_hist(): return jsonify(queries.history())
@app.post("/api/sources/<int:i>")
def api_src(i):
    pr = int((request.get_json(force=True) or {}).get("priority", 5)); queries.run("UPDATE sources SET priority=? WHERE id=?", (max(1, min(pr, 9)), i)); return jsonify(ok=True)
def _eqf():
    g = request.args; return dict(status=g.get("status") or None, conf=g.get("confidence") or None, qtxt=g.get("q") or None, crit=g.getlist("crit"), dif=g.getlist("dif"), miss=g.getlist("miss"), diff=g.get("diff") or None, minscore=g.get("minscore") or None)
@app.get("/api/equivalences")
def api_eq(): return jsonify(equivalence.listing(page=int(request.args.get("page") or 1), **_eqf()))
@app.get("/api/equivalences/export.xlsx")
def api_eq_xlsx():
    from flask import send_file
    bio, n = equivalence.export_xlsx(**_eqf())
    return send_file(bio, as_attachment=True, download_name=f"equivalencias_{datetime.datetime.now():%Y%m%d_%H%M}.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
@app.post("/api/equivalences/generate")
def api_eq_gen(): return jsonify(equivalence.generate())
@app.post("/api/equivalences/<int:i>")
def api_eq_set(i):
    s = (request.get_json(force=True) or {}).get("status")
    if s not in ("pendente", "aprovada", "rejeitada"): abort(400)
    queries.run("UPDATE equivalence_suggestions SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (s, i)); return jsonify(ok=True)
@app.get("/api/samples")
def api_samples(): return jsonify(queries.samples(A()))
@app.get("/api/samples/prefill")
def api_sample_prefill(): return jsonify(queries.sample_prefill(request.args.get("code", "")))
@app.post("/api/samples")
def api_sample_save(): return jsonify(id=queries.sample_save(request.get_json(force=True)))
@app.delete("/api/samples/<int:i>")
def api_sample_del(i): queries.run("DELETE FROM sample_orders WHERE id=?", (i,)); return jsonify(ok=True)
@app.get("/api/backups")
def api_bk(): return jsonify(backups=queries.backups(), db=db.DB_PATH, size=os.path.getsize(db.DB_PATH) if os.path.exists(db.DB_PATH) else 0)
@app.post("/api/backups")
def api_bk_new(): return jsonify(name=queries.backup_create())
@app.post("/api/backups/restore")
def api_bk_restore():
    try: return jsonify(safety=queries.backup_restore((request.get_json(force=True) or {}).get("name")))
    except ValueError as e: return jsonify(error=str(e)), 400
@app.get("/api/backups/<name>")
def api_bk_dl(name):
    if not re.fullmatch(r"[\w\-]+\.db", name): abort(400)
    return send_from_directory(queries.BK, name, as_attachment=True)

# ---- Damping force ----
@app.get("/api/damping/rules")
def api_dr(): return jsonify(damping.rules())
@app.post("/api/damping/rules")
def api_dr_up():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".xlsx"): return jsonify(error="Envie a planilha da regra (.xlsx)."), 400
    os.makedirs(UPLOADS, exist_ok=True); p = os.path.join(UPLOADS, uuid.uuid4().hex + "__regra.xlsx"); f.save(p)
    try: n, par = damping.load_rules(p, os.path.basename(f.filename))
    except Exception as e: return jsonify(error=str(e)), 400
    finally: os.remove(p)
    return jsonify(points=n, **par)
@app.get("/api/damping/tests")
def api_dt(): return jsonify(damping.tests(request.args.get("q")))
@app.get("/api/damping/tests/<int:i>")
def api_dt1(i): return jsonify(damping.get_test(i) or abort(404))
@app.post("/api/damping/tests")
def api_dt_save():
    try: return jsonify(id=damping.save_test(request.get_json(force=True)))
    except (ValueError, KeyError) as e: return jsonify(error=str(e)), 400
@app.delete("/api/damping/tests/<int:i>")
def api_dt_del(i): queries.run("DELETE FROM damping_tests WHERE id=?", (i,)); return jsonify(ok=True)
@app.get("/api/damping/prefill")
def api_dpre(): return jsonify(damping.prefill(request.args.get("code", "")))
@app.get("/api/damping/tests/<int:i>/export.xlsx")
def api_dt_xlsx(i):
    from flask import send_file
    if not damping.get_test(i): abort(404)
    return send_file(damping.test_workbook(i), as_attachment=True, download_name=f"damping_force_{i}.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
@app.get("/api/export/<name>.xlsx")
def api_export(name):
    from flask import send_file
    try: bio, fn = exporter.build(name, request.args.to_dict())
    except ValueError as e: return jsonify(error=str(e)), 400
    return send_file(bio, as_attachment=True, download_name=fn, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ---- Em desenvolvimento (DES) / Em redesenvolvimento (R-D) ----
def _rdk(k): return rd.KINDS.get(k) or abort(404)
@app.get("/api/rd/<kind>")
def api_rd(kind): return jsonify(rd.items(_rdk(kind), A()))
@app.get("/api/rd/<kind>/facets")
def api_rd_f(kind): return jsonify(rd.facets(_rdk(kind)))
@app.get("/api/rd/<kind>/item/<path:code>")
def api_rd_d(kind, code): return jsonify(rd.detail(_rdk(kind), code) or abort(404))
@app.get("/api/filters")
def api_filters(): return jsonify(rd.filter_lists(request.args.get("make") or None))

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)), debug=False)
