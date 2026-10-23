"""
Scénarios de test simulant des situations opérationnelles.
Chaque test part d'une base propre (copie), provoque une situation, puis vérifie
que le système expert et les indicateurs réagissent comme attendu.
Lancer : python -m pytest -v
"""
import sqlite3, sys, time
from pathlib import Path
import pandas as pd
try:
    import pytest
    fixture = pytest.fixture
except ImportError:                      # exécution via tests/lancer_tests.py
    fixture = lambda *a, **k: (lambda f: f) if not (a and callable(a[0])) else a[0]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from charger_base import charger
from systeme_expert import verifier, corriger, expliquer

@fixture(scope="module")
def base_ref(tmp_path_factory):
    db = tmp_path_factory.mktemp("ref") / "mes.db"
    charger(db).close()
    return db

@fixture
def con(base_ref, tmp_path):
    copie = tmp_path / "mes.db"
    src, dst = sqlite3.connect(base_ref), sqlite3.connect(copie)
    src.backup(dst); src.close()
    yield dst
    dst.close()

def trs(con, poste):
    return pd.read_sql("SELECT * FROM v_trs_poste", con).set_index("poste_id").loc[poste]

# -------------------------------------------------------------- base de référence
def test_detection_de_toutes_les_anomalies_injectees(con):
    _, an, _, _ = verifier(con)
    vrai = pd.read_csv(ROOT / "data" / "anomalies_injectees_NE_PAS_UTILISER.csv")
    k = lambda d: set(zip(d.type_anomalie, d.of_id, d.poste_id.astype(int)))
    assert k(vrai) <= k(an)                 # rappel = 100 %
    assert k(an) - k(vrai) == set()         # aucune fausse alerte

def test_correction_puis_reverification(con):
    _, an, _, _ = verifier(con)
    bilan = corriger(con, an)
    _, an2, _, _ = verifier(con)
    corrigeables = {"fin_avant_debut", "lot_non_receptionne", "quantite_incoherente"}
    assert not corrigeables & set(an2.type_anomalie)   # plus aucune anomalie corrigeable
    assert bilan["corrigé"] + bilan["à valider"] == len(an)
    assert con.execute("SELECT COUNT(*) FROM journal_corrections").fetchone()[0] == len(an)

# -------------------------------------------------------------- scénario 1 : panne de poste
def test_scenario_panne_poste_cablage(con):
    """Une panne de 3 h sur le poste Câblage : alerte maintenance + baisse de disponibilité."""
    avant = trs(con, 3)
    of = con.execute("""SELECT of_id FROM evenements WHERE poste_id = 3 AND type = 'debut'
                        ORDER BY horodatage LIMIT 1 OFFSET 500""").fetchone()[0]
    debut = con.execute("SELECT horodatage FROM evenements WHERE of_id=? AND poste_id=3 AND type='debut'", (of,)).fetchone()[0]
    con.execute("""INSERT INTO evenements (of_id, poste_id, type, horodatage, valeur, resultat)
                   VALUES (?, 3, 'arret', ?, 180, 'panne')""", (of, debut))
    con.execute("""UPDATE evenements SET horodatage = DATETIME(horodatage, '+180 minutes')
                   WHERE of_id = ? AND poste_id = 3 AND type = 'fin'""", (of,))
    bf, _, _, _ = verifier(con)
    assert bf.existe("alerte", ("arret_long", of, 3))
    assert trs(con, 3).disponibilite < avant.disponibilite

# -------------------------------------------------------------- scénario 2 : lot non conforme
def test_scenario_rappel_fournisseur_lot_non_conforme(con):
    """Le fournisseur rappelle un lot : on retrouve tous les OF touchés en moins de 2 s."""
    lot = "L2010"
    con.execute("UPDATE lots_composants SET statut = 'non conforme' WHERE lot_id = ?", (lot,))
    t = time.perf_counter()
    trace = pd.read_sql("SELECT * FROM v_tracabilite_lots WHERE lot_id = ?", con, params=(lot,))
    assert time.perf_counter() - t < 2
    attendus = {r[0] for r in con.execute(
        "SELECT DISTINCT of_id FROM evenements WHERE lot_id = ? AND type = 'consommation'", (lot,))}
    assert set(trace.of_id) == attendus and len(attendus) > 0
    bf, _, _, _ = verifier(con)
    risques = {f.cle[0] for f in bf.du_type("of_a_risque")}
    assert attendus <= risques
    expedies = set(trace.of_id[trace.statut_of == "expédié"])
    assert all(bf.existe("alerte", ("rappel_client", of)) for of in expedies)
    # le système sait expliquer pourquoi
    of = next(iter(expedies))
    assert "R8" in expliquer(bf, "alerte", ("rappel_client", of))

# -------------------------------------------------------------- scénario 3 : contrôle qualité KO
def test_scenario_cq_ko_puis_expedition(con):
    """Un OF en échec au test est quand même emballé : anomalie critique."""
    of = con.execute("""SELECT of_id FROM evenements WHERE type = 'controle_qualite' AND resultat = 'KO'
                        LIMIT 1""").fetchone()[0]
    _, an, _, _ = verifier(con)
    assert "expedie_malgre_cq_ko" not in set(an.type_anomalie)   # situation normale : OF bloqué
    fin4 = con.execute("SELECT horodatage FROM evenements WHERE of_id=? AND poste_id=4 AND type='fin'", (of,)).fetchone()[0]
    for typ, minutes in [("debut", 10), ("fin", 25)]:
        con.execute("""INSERT INTO evenements (of_id, poste_id, type, horodatage)
                       VALUES (?, 5, ?, DATETIME(?, ?))""", (of, typ, fin4, f"+{minutes} minutes"))
    _, an, _, _ = verifier(con)
    crit = an[an.type_anomalie == "expedie_malgre_cq_ko"]
    assert list(crit.of_id) == [of] and (crit.gravite == "critique").all()
