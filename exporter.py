"""Exportação XLSX de todos os módulos (sempre TODAS as linhas do filtro atual, não só a página)."""
import io, datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
import queries as Q, equivalence, damping, database as db

def _sheet(wb, title, head, rows, widths=None):
    ws = wb.create_sheet(title[:31]); ws.append(head)
    for r in rows: ws.append(["" if v is None else v for v in r])
    for c in ws[1]: c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="243242"); c.alignment = Alignment(vertical="center", wrap_text=True)
    for i in range(1, len(head) + 1): ws.column_dimensions[get_column_letter(i)].width = (widths or [])[i - 1] if widths and i <= len(widths) else 18
    ws.freeze_panes = "A2"
    if rows: ws.auto_filter.ref = ws.dimensions
    return ws

def _finish(wb, filtros):
    ws = wb.create_sheet("Filtros aplicados")
    for k, v in [("Gerado em", datetime.datetime.now().strftime("%d/%m/%Y %H:%M"))] + [(k, v or "—") for k, v in filtros.items()]: ws.append([k, v])
    ws.column_dimensions["A"].width = 22; ws.column_dimensions["B"].width = 80
    for c in ws["A"]: c.font = Font(bold=True)
    bio = io.BytesIO(); wb.save(bio); bio.seek(0); return bio

def _codes():
    out = {}
    for r in Q.q("SELECT product_id,code_type,group_concat(DISTINCT code) c FROM codes GROUP BY product_id,code_type"): out[(r["product_id"], r["code_type"])] = r["c"].replace(",", "; ")
    return out
SYS = {"gas": "Gás", "oleo": "Óleo"}

def _products(a):
    rows = Q.products({**a, "all": 1})["rows"]; cd = _codes()
    return [("Produtos", ["Pos. catálogo", "Código PERFECT", "Descrição", "Grupo", "Família", "Sistema", "EAN", "Peso (kg)", "Lmin (mm)", "Lmax (mm)", "Aplicações", "Códigos OEM", "Códigos fornecedor", "Códigos concorrente", "Pendências abertas"],
             [[r["catalog_position"], r["perfect_code"], r["description"], r["catalog_group"], r["family"], SYS.get(r["system_type"]), r["ean"], r["weight_kg"], r["lmin_mm"], r["lmax_mm"], r["apps"],
               cd.get((r["id"], "oem")), cd.get((r["id"], "fornecedor")), cd.get((r["id"], "concorrente")), r["pend"]] for r in rows], [11, 16, 38, 18, 16, 9, 16, 10, 10, 10, 11, 30, 30, 30, 11])], len(rows)

def _apps(a):
    rows = Q.applications({**a, "all": 1})["rows"]
    return [("Aplicações", ["Montadora", "Modelo", "Versão", "Aplicação", "Ano inicial", "Ano final", "Eixo", "Lado", "Código PERFECT", "Pos. catálogo"],
             [[r["make"], r["model"], r["version"], r["application_text"], r["year_from"], r["year_to"], r["axle"], r["side"], r["perfect_code"], r["catalog_position"]] for r in rows], [16, 22, 14, 38, 11, 11, 11, 11, 16, 11])], len(rows)

def _compare(a):
    import re
    ps = Q.compare([int(i) for i in re.findall(r"\d+", a.get("ids", ""))])
    F = [("Posição no catálogo", lambda p: p["catalog_position"]), ("Descrição", lambda p: p["description"]), ("Grupo", lambda p: p["catalog_group"]), ("Família", lambda p: p["family"]), ("Sistema", lambda p: SYS.get(p["system_type"])),
         ("Lmin (mm)", lambda p: (p["dimensions"] or {}).get("lmin_mm")), ("Lmax (mm)", lambda p: (p["dimensions"] or {}).get("lmax_mm")), ("Ø haste (mm)", lambda p: (p["dimensions"] or {}).get("rod_diameter_mm")),
         ("Ø tubo (mm)", lambda p: (p["dimensions"] or {}).get("tube_diameter_mm")), ("Peso (kg)", lambda p: p["weight_kg"]), ("EAN", lambda p: p["ean"]), ("Caixa", lambda p: p["package_code"]),
         ("Códigos OEM", lambda p: "; ".join(c["code"] for c in p["codes"] if c["code_type"] == "oem")), ("Códigos fornecedor", lambda p: "; ".join(sorted({c["code"] for c in p["codes"] if c["code_type"] == "fornecedor"}))),
         ("Aplicações", lambda p: "; ".join(f"{x['make'] or ''} {x['model'] or ''} {x['year_from'] or ''}-{x['year_to'] or ''}".strip() for x in p["applications"])),
         ("Nº Inmetro", lambda p: "; ".join(sorted({c["inmetro_number"] for c in p["certificates"] if c["inmetro_number"]}))),
         ("Fontes", lambda p: "; ".join(sorted({x["source"] for x in p["codes"] + p["applications"] if x["source"]})))]
    rows = []
    for l, fn in F:
        v = [fn(p) for p in ps]; rows.append([l] + v + ["SIM" if len({str(x or "") for x in v}) > 1 and len(ps) > 1 else ""])
    return [("Comparação", ["Campo"] + [p["perfect_code"] for p in ps] + ["Difere?"], rows, [24] + [36] * len(ps) + [10])], len(ps)

def _pend(a):
    d = Q.pendencies({**a, "all": 1})["rows"]; du = Q.duplicates()
    return [("Pendências", ["Código PERFECT", "Tipo", "Campo", "Descrição", "Status"], [[r["perfect_code"], r["kind"], r["field"], r["description"], r["status"]] for r in d], [16, 20, 14, 90, 12]),
            ("Duplicidades", ["Tipo de código", "Código", "Produtos", "Qtd. produtos"], [[r["code_type"], r["code"], r["products"], r["n"]] for r in du], [14, 20, 60, 12])], len(d)

def _fontes(a):
    h = Q.history()
    return [("Histórico", ["#", "Data", "Arquivo", "Planilha", "Categoria", "Linhas lidas", "Novos", "Atualizados", "Conflitos", "Erros", "Status"],
             [[b["id"], b["imported_at"], b["filename"], b["sheet"], b["category"], b["rows_read"], b["rows_new"], b["rows_updated"], b["rows_conflict"], b["rows_error"], b["status"]] for b in h["batches"]], [6, 20, 40, 14, 28, 12, 9, 12, 10, 8, 10]),
            ("Fontes", ["Fonte", "Categoria", "Importações", "Prioridade"], [[s["name"], s["category"], s["imports"], s["priority"]] for s in h["sources"]], [44, 30, 12, 10])], len(h["batches"])

def _samples(a):
    d = Q.samples(a); rows = []
    for r in d["rows"]:
        qs = (r["quotes"] + [{}, {}, {}])[:3]; ch = next((x["price"] for x in r["quotes"] if x.get("chosen")), None)
        rows.append([r["perfect_code"], r["sample_code"], r["sc_number"], r["ship_code"], r["application"], {"direito": "Direito (LD)", "esquerdo": "Esquerdo (LE)", "ambos": "Ambos (LD/LE)"}.get(r.get("side")), r["supplier"], r["month"], dict(d["stages"]).get(r["stage"]), "SIM" if r["to_send"] else "", "SIM" if r["pending_supplier"] else "",
                     r["tracking"], r["net_weight"], r["gross_weight"], r["credit_note"], ch] + [v for x in qs for v in (x.get("price"), x.get("link"))] + [r["notes"]])
    return [("Amostras", ["Código PERFECT", "Código amostra", "Nº SC", "Cód. envio", "Aplicação", "Lado", "Fornecedor", "Mês", "Etapa", "Enviar", "Pendente fornecedor", "Rastreio", "Peso líq.", "Peso bruto", "Credit note", "Preço escolhido",
             "Preço 1", "Link 1", "Preço 2", "Link 2", "Preço 3", "Link 3", "Observações"], rows, [16, 18, 10, 12, 40, 14, 16, 12, 18, 8, 12, 18, 9, 9, 12, 12, 10, 30, 10, 30, 10, 30, 30])], len(rows)

def _damping(a):
    ts = damping.tests(a.get("q")); pts = []
    for t in ts:
        full = damping.get_test(t["id"])
        for p in full["points"]: pts.append([t["id"], t["perfect_code"], t["label"], t["test_date"], p["table_name"], p["velocity"], p["tolerance"], p["drawing"], p["min"], p["max"], p["found"], p["result"]])
    return [("Ensaios", ["#", "Código PERFECT", "Identificação", "Data", "Resultado geral"], [[t["id"], t["perfect_code"], t["label"], t["test_date"], t["overall"]] for t in ts], [6, 16, 30, 12, 16]),
            ("Pontos", ["Ensaio", "Código PERFECT", "Identificação", "Data", "Tabela", "VM/S", "Tolerância", "DRAWING", "Mín (N)", "Máx (N)", "FOUND", "Resultado"], pts, [8, 16, 26, 12, 8, 8, 10, 10, 10, 10, 10, 16])], len(ts)

def _backups(a):
    return [("Backups", ["Arquivo", "Data", "Tamanho (bytes)"], [[b["name"], b["date"], b["size"]] for b in Q.backups()], [50, 20, 16])], 0

def _rd(kind):
    def f(a):
        import rd as R
        its = R.items(kind, {**a, "all": 1})["rows"]
        lines = Q.q("SELECT code,suggestion,description,make,vehicle,application_text,year_from,year_to,status,drawing_substatus,validation_substatus,supplier,substr(sample_bought,1,10) b,substr(sample_sent,1,10) s,product_id FROM rd_projects WHERE suggestion=? ORDER BY code,make,vehicle", (kind,))
        return [("Itens", ["Código", "Descrição", "Montadoras", "Veículos", "Linhas (aplicações)", "Status", "Pendência desenho", "Pendência validação", "Fornecedores", "Amostra comprada", "Amostra enviada", "No catálogo", "Também no outro tipo"],
                 [[r["code"], r["description"], r["makes"], r["vehicles"], r["n_rows"], r["statuses"], r["drawing"], r["validation"], r["suppliers"], r["bought"], r["sent"], "SIM" if r["product_id"] else "", "SIM" if r["also_other"] else ""] for r in its], [16, 36, 20, 30, 10, 28, 26, 36, 18, 14, 14, 10, 12]),
                ("Linhas (todas)", ["Código", "Tipo", "Descrição", "Montadora", "Veículo", "Aplicação", "Ano inicial", "Ano final", "Status", "Pend. desenho", "Pend. validação", "Fornecedor", "Amostra comprada", "Amostra enviada"],
                 [[l["code"], l["suggestion"], l["description"], l["make"], l["vehicle"], l["application_text"], l["year_from"], l["year_to"], l["status"], l["drawing_substatus"], l["validation_substatus"], l["supplier"], l["b"], l["s"]] for l in lines], [16, 8, 34, 16, 18, 40, 10, 10, 24, 22, 30, 12, 14, 14])], len(its)
    return f

BUILD = {"desenvolvimento": _rd("DES"), "redesenvolvimento": _rd("R-D"), "produtos": _products, "pesquisa": _products, "aplicacoes": _apps, "comparacao": _compare, "pendencias": _pend, "fontes": _fontes, "amostras": _samples, "damping": _damping, "configuracoes": _backups}

def build(name, args):
    if name not in BUILD: raise ValueError("Módulo sem exportação.")
    a = {k: v for k, v in args.items() if v}; sheets, n = BUILD[name](a); wb = Workbook(); wb.remove(wb.active)
    for s in sheets: _sheet(wb, *s)
    bio = _finish(wb, {"Módulo": name, **{k: v for k, v in a.items() if k != "all"}})
    return bio, f"{name}_{datetime.datetime.now():%Y%m%d_%H%M}.xlsx"
