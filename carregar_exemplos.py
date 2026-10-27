"""Carrega as bases de bases_exemplo/ no banco, na ordem correta (o catálogo primeiro). Seguro para repetir."""
import os, glob, importer, loaders, database as db
B = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bases_exemplo")
ORDEM = [("CatalogoAMD.xlsx", None), ("CaixasAMD.xlsx", None), ("Lados - Amortecedores.xlsx", None), ("CodigosZSxPERFECT.xlsx", None),
         ("ItensMotorcraft.xlsx", "MOTORCRAFT"), ("DadosR-D e DES.xlsx", None), ("EstruturaAMD.xls", None),
         ("InmetroZS - Todos - Certificado.xlsx", None), ("InmetroE-win - Todos - Certificado.xlsx", None), ("ZS.csv", "(csv)"), ("e-win.csv", "(csv)"), ("Compra_de_amostra.xlsx", None)]
if __name__ == "__main__":
    db.init_db()
    for f, sh in ORDEM:
        g = glob.glob(os.path.join(B, f.replace("ó", "*")))
        if not g: print("ausente:", f); continue
        p = g[0]
        df, _ = importer.read_table(p, None if sh in (None, "(csv)") else sh)
        s = loaders.run(p, sh, importer.suggest_mapping(df.columns), None, os.path.basename(p), True)
        print(f"{f}: {s['label']} | {s['rows']} linhas | {s['counts']}")
    import damping, glob
    g = glob.glob(os.path.join(B, "DAMPING*"))
    if g: print("damping:", damping.load_rules(g[0], os.path.basename(g[0])))
    import equivalence; print("equivalências:", equivalence.generate())
    print(db.stats())
