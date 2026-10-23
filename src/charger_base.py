"""Crée la base SQLite mes.db à partir des CSV et des scripts SQL."""
import sqlite3
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "mes.db"

def charger(db_path=DB, data_dir=ROOT / "data"):
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript((ROOT / "sql" / "schema.sql").read_text(encoding="utf-8"))
    for table in ["postes", "produits", "lots_composants", "ordres_fabrication", "evenements"]:
        df = pd.read_csv(data_dir / f"{table}.csv")
        df.to_sql(table, con, if_exists="append", index=False)
    con.executescript((ROOT / "sql" / "indicateurs.sql").read_text(encoding="utf-8"))
    con.commit()
    return con

if __name__ == "__main__":
    con = charger()
    for t in ["postes", "produits", "lots_composants", "ordres_fabrication", "evenements"]:
        print(f"{t:20s} {con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:>7}")
    print(pd.read_sql("SELECT * FROM v_trs_poste", con).to_string(index=False))
