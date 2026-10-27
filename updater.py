"""Atualização de dados: lê as planilhas (reconhecidas pelo NOME do arquivo), compara com o banco e insere só o que falta.
Nada é apagado: linhas já cadastradas ficam como estão (campos vazios podem ser preenchidos; em Desenvolvimento, status/fornecedor/amostras
são atualizados quando mudam na planilha). Tudo roda em UMA transação: a verificação desfaz no final, a aplicação grava (com backup antes)."""
import os, re, shutil, uuid
import database as db, importer, loaders, queries

# nome da planilha (ordem de carga: o catálogo primeiro) -> aba
KNOWN = [("CatalogoAMD.xlsx", None), ("CaixasAMD.xlsx", None), ("Lados - Amortecedores.xlsx", None), ("CodigosZSxPERFECT.xlsx", None),
         ("ItensMotorcraft.xlsx", "MOTORCRAFT"), ("DadosR-D e DES.xlsx", None), ("EstruturaAMD.xls", None),
         ("InmetroZS - Todos - Certificado.xlsx", None), ("InmetroE-win - Todos - Certificado.xlsx", None), ("ZS.csv", "(csv)"), ("e-win.csv", "(csv)"),
         ("Compra_de_amostra.xlsx", None), ("DAMPING FORCE - REGRA.xlsx", "damping")]
FOLDER = os.path.join(db.BASE, "bases_exemplo")
TMP = os.path.join(db.BASE, "data", "uploads")

def _norm(name):
    n = os.path.splitext(os.path.basename(name))[0].lower()
    n = re.sub(r"\s*\(\d+\)$", "", n)            # "Compra_de_amostra (1).xlsx" (cópia do navegador)
    return re.sub(r"[\s_]+", " ", n).strip(), os.path.splitext(name)[1].lower()
_IDX = {_norm(f): (i, f, sh) for i, (f, sh) in enumerate(KNOWN)}

def identify(name):
    """(ordem, nome oficial, aba) ou None."""
    n, ext = _norm(name)
    return _IDX.get((n, ext)) or next((v for (kn, ke), v in _IDX.items() if kn == n and ke in (".xlsx", ".xls") and ext in (".xlsx", ".xls")), None)

def folder_files():
    return [(f, os.path.join(FOLDER, f)) for f in sorted(os.listdir(FOLDER)) if os.path.isfile(os.path.join(FOLDER, f))] if os.path.isdir(FOLDER) else []

def _damping(path, name, confirm):
    import damping
    rules, _ = damping.parse_rules(path)
    cur = [(r["table_name"], r["seq"], r["velocity"], r["tolerance"]) for r in queries.q("SELECT table_name,seq,velocity,tolerance FROM damping_rules ORDER BY table_name,seq")]
    new = sorted((n, s, float(v), float(t)) for n, s, v, t in rules); old = sorted((n, s, float(v), float(t)) for n, s, v, t in cur)
    if new == old: return {"rows": len(rules), "counts": {"new": 0, "updated": 0, "present": len(rules)}, "messages": [], "label": "Regra de damping force"}
    if confirm: damping.load_rules(path, name)
    return {"rows": len(rules), "counts": {"new": 0, "updated": len(rules), "present": 0}, "messages": ["Regra diferente da cadastrada: será recarregada por completo."], "label": "Regra de damping force"}

def run(files, confirm=False):
    """files: [(nome, caminho)]. Retorna {results, totals, backup}."""
    items, results = [], []
    for name, path in files:
        k = identify(name)
        if k: items.append((k[0], k[1], k[2], name, path))
        else: results.append({"file": name, "status": "ignorado", "label": "—", "rows": 0, "counts": {}, "messages": ["Nome não reconhecido. Mantenha o mesmo nome das planilhas originais (ou use Importação de Excel)."]})
    items.sort()
    backup = queries.backup_create("pre_atualizacao") if confirm and os.path.exists(db.DB_PATH) else None
    conn = db.conn(); post = []
    try:
        for _, official, sheet, name, path in items:
            if sheet == "damping": post.append((official, name, path)); continue
            conn.execute("SAVEPOINT f")
            try:
                df, _ = importer.read_table(path, None if sheet in (None, "(csv)") else sheet)
                r = loaders.run(path, sheet, importer.suggest_mapping(df.columns), None, official, confirm, "keep", True, conn)
                conn.execute("RELEASE f"); r.update(file=name, status="ok"); results.append(r)
            except Exception as e:
                conn.execute("ROLLBACK TO f"); conn.execute("RELEASE f")
                results.append({"file": name, "status": "erro", "label": official, "rows": 0, "counts": {}, "messages": [f"Não foi possível ler/gravar: {e}. Esta planilha foi pulada; o banco não foi alterado por ela."]})
        conn.commit() if confirm else conn.rollback()
    except Exception:
        conn.rollback(); raise
    finally: conn.close()
    for official, name, path in post:
        try: r = _damping(path, official, confirm); r.update(file=name, status="ok"); results.append(r)
        except Exception as e: results.append({"file": name, "status": "erro", "label": "Regra de damping force", "rows": 0, "counts": {}, "messages": [str(e)]})
    new_products = sum(r["counts"].get("new", 0) for r in results if r.get("label") == loaders.LABEL["catalogo"])
    eq = None
    if confirm and new_products:
        import equivalence; eq = equivalence.generate()
    tot = {k: sum(r["counts"].get(k, 0) for r in results) for k in ("new", "updated", "present", "unmatched", "conflicts", "errors")}
    return {"results": results, "totals": tot, "backup": backup, "confirmed": confirm, "equivalences": eq}

# ---- arquivos enviados ficam guardados até o usuário confirmar ----
def stash(uploads):
    tok = uuid.uuid4().hex; d = os.path.join(TMP, "upd_" + tok); os.makedirs(d, exist_ok=True); out = []
    for f in uploads:
        name = os.path.basename(f.filename or "").strip()
        if not name.lower().endswith((".xlsx", ".xls", ".csv")): continue
        p = os.path.join(d, name); f.save(p); out.append((name, p))
    return tok, out
def stashed(tok):
    if not re.fullmatch(r"[0-9a-f]{32}", tok or ""): return None
    d = os.path.join(TMP, "upd_" + tok)
    return [(f, os.path.join(d, f)) for f in sorted(os.listdir(d))] if os.path.isdir(d) else None
def discard(tok):
    if re.fullmatch(r"[0-9a-f]{32}", tok or ""): shutil.rmtree(os.path.join(TMP, "upd_" + tok), ignore_errors=True)
