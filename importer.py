"""Etapa 2 (parte 1): leitura, prévia, mapeamento automático e normalização. NÃO grava no banco.
Regras confirmadas pelo usuário:
 - Códigos como 1BP31901AB são códigos de MONTADORAS (OEM): mantidos como tal.
 - Prefixo 'MP-' = item sem embalagem (a granel); 'PA' = produto acabado.
 - R&D.SUGESTAO: DES = desenvolvimento (item novo); R-D = redesenvolvimento.
 - CaixasAMD: dimensões corrigidas a partir da coluna 'Dimensões (mm)' (texto 425x85x60)."""
import os, re, unicodedata
import pandas as pd

NA = [""]  # só vazio vira nulo ('NA', 'N/A' são dados válidos)
RD_KIND = {"DES": "desenvolvimento (item novo)", "R-D": "redesenvolvimento"}

def norm_header(h):
    s = unicodedata.normalize("NFKD", str(h)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.replace("\t", " ")).strip().lower()

# campo interno -> cabeçalhos conhecidos (já normalizados). Só correspondência exata; o resto o usuário mapeia.
ALIASES = {
 "perfect_code": ["codigo do produto", "perfect", "perfect code", "perfect pn", "pn perfect (corresp.)"],
 "oem_code": ["pn ford"], "oem_code_alt": ["ford pn"], "oem_code_proj": ["ford proj"], "rh_code": ["rh"], "lh_code": ["lh"],
 "description": ["descricao do produto", "descricao", "descricao certificado"],
 "description_es": ["descricao do produto em espanhol"], "description_en": ["descricao do produto em ingles"],
 "ean": ["cod. barras", "cod barras"], "ncm": ["cod. ncm"], "weight_kg": ["peso (kg)"],
 "measure_min_max": ["medida"], "observation": ["observacao do produto"],
 "make": ["montadora"], "vehicle": ["veiculo", "modelo"], "application": ["aplicacao"],
 "year_from": ["ano_inicial"], "year_to": ["ano_final"], "year_range": ["ano"],
 "rd_kind": ["sugestao"], "status": ["status"], "sub_status_drawing": ["sub_status_desenho"],
 "sub_status_validation": ["sub_status_validacao"], "supplier": ["fornecedor", "fornecedores"],
 "sample_bought": ["amostra_comprada"], "sample_sent": ["amostra_enviada"],
 "group_name": ["descricao do grupo do produto"], "ship_code": ["codigo envio"], "sc_number": ["n sc"], "sample_code": ["codigo amostra"],
 "price1": ["preco 1"], "link1": ["link 1 / contato"], "price2": ["preco 2"], "link2": ["link 2"], "price3": ["preco 3"], "link3": ["link3"],
 "sc_open": ["sc aberta"], "arrived": ["chegou"], "finished": ["projeto finalizado"], "approved": ["projeto aprovado"], "to_send": ["enviar"],
 "tracking": ["cod. rastreio"], "month": ["mes"], "credit_note": ["credit note"], "net_weight": ["peso liq. (kg)"], "gross_weight": ["peso brut. (kg)"],
 "erp_code": ["produto"], "item_type": ["tipo prod."], "supplier_code": ["cod.prod.for"], "supplier_code2": ["cod. forn. 2"],
 "supplier_name": ["nome"], "zs_code": ["zs no."],
 "inmetro_number": ["inmetro number", "inmetro no", "inmetro"], "family": ["familia", "family", "tipo"],
 "box_code": ["caixa"], "box_dims_mm": ["dimensoes (mm)"], "box_dims_cm": ["dimensoes (cm)"],
 "parent_code": ["codigo"], "component_code": ["componente"], "component_desc": ["descricao comp."],
 "qty": ["quantidade"], "seq": ["sequencia"], "date_from": ["dt inicial"], "date_to": ["dt final"],
}
_REV = {a: f for f, al in ALIASES.items() for a in al}

def normalize_code(raw):
    """Retorna (código_normalizado, a_granel). Original deve ser guardado à parte, como texto."""
    if raw is None or str(raw).strip() == "": return None, False
    s = str(raw).strip(); bulk = s.upper().startswith("MP-")
    if bulk: s = s[3:]
    return re.sub(r"[/\s]", "", s), bulk

def list_sheets(path):
    if path.lower().endswith((".csv", ".txt")): return ["(csv)"]
    return pd.ExcelFile(path).sheet_names

def read_table(path, sheet=None):
    """Lê tudo como texto. Detecta a linha de cabeçalho e descarta colunas totalmente vazias."""
    if path.lower().endswith((".csv", ".txt")):
        raw = pd.read_csv(path, sep=";", encoding="latin-1", dtype=str, header=None, keep_default_na=False, na_values=NA)
    else:
        raw = pd.read_excel(path, sheet_name=sheet or 0, dtype=str, header=None, keep_default_na=False, na_values=NA)
    raw = raw.dropna(how="all").dropna(axis=1, how="all")
    if raw.empty: return pd.DataFrame(), None
    counts = raw.head(10).notna().sum(axis=1); hdr = counts[counts >= max(2, 0.6 * counts.max())].index[0]
    names, seen = [], {}
    for v in raw.loc[hdr]:
        n = re.sub(r"\s+", " ", str(v).replace("\t", " ")).strip() if pd.notna(v) else "(sem nome)"
        seen[n] = seen.get(n, 0) + 1; names.append(n if seen[n] == 1 else f"{n}.{seen[n]-1}")
    df = raw.loc[raw.index > hdr].copy(); df.columns = names
    return df.reset_index(drop=True), int(hdr)

def suggest_mapping(columns):
    """{coluna: campo sugerido ou None}. Campo repetido fica só na 1ª coluna (as demais vão para revisão)."""
    out, used = {}, set()
    for c in columns:
        nh = norm_header(re.sub(r"\.\d+$", "", c)); f = _REV.get(nh) or ("pending_des" if nh.startswith("pendente des") else None)
        if f and f not in used: out[c] = f; used.add(f)
        else: out[c] = None
    return out

def preview(path, sheet=None, n=8):
    df, hdr = read_table(path, sheet)
    return {"rows_total": len(df), "header_row": hdr, "mapping": suggest_mapping(df.columns),
            "sample": df.head(n).fillna("").to_dict("records")}

def parse_boxes(df):
    """Corrige CaixasAMD: usa 'Dimensões (mm)' (ex.: 425x85x60) como fonte; as colunas separadas estão em cm arredondado.
    Retorna (linhas, avisos). Avisa quando a coluna em cm diverge do arredondamento do valor em mm."""
    rows, warns = [], []
    for _, r in df.iterrows():
        code = str(r["Caixa"]).strip(); m = re.fullmatch(r"(\d+)x(\d+)x(\d+)", str(r["Dimensões (mm)"]).strip())
        if not m: warns.append(f"{code}: dimensão em mm ilegível: {r['Dimensões (mm)']!r}"); continue
        L, W, H = map(float, m.groups())
        rows.append({"code": code, "length_mm": L, "width_mm": W, "height_mm": H, "raw_dims": r["Dimensões (mm)"]})
        cm = [float(x.replace(",", ".")) for x in str(r["Dimensões (cm)"]).split("x")]
        if cm != [round(L/10, 1), round(W/10, 1), round(H/10, 1)]:
            warns.append(f"{code}: mm={int(L)}x{int(W)}x{int(H)} mas coluna cm={r['Dimensões (cm)']}; usado o valor em mm — verificar")
    return rows, warns
