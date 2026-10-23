"""
Démonstrateur MES — outil en ligne de commande.

  python src/demo.py init                 crée la base à partir des CSV
  python src/demo.py verifier             lance le système expert et exporte le rapport
  python src/demo.py corriger             applique les corrections sûres, puis revérifie
  python src/demo.py tracer L3012         traçabilité d'un lot de composant
  python src/demo.py tracer OF00845       lots utilisés par une commande (et commandes liées si lot défectueux)
  python src/demo.py pourquoi OF00845     explique les conclusions du système sur un OF
  python src/demo.py simuler panne        rejoue une situation réelle (panne, rappel, ko) sur une copie de la base
  python src/demo.py trs                  TRS par poste
  python src/demo.py regles               affiche la base de règles
"""
import argparse, sqlite3, sys, time
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from charger_base import charger, DB, ROOT
from systeme_expert import verifier, corriger, expliquer, REGLES

pd.set_option("display.width", 140)

def connexion():
    if not DB.exists():
        sys.exit("Base absente : lancez d'abord  python src/demo.py init")
    return sqlite3.connect(DB)

def cmd_init(_):
    con = charger()
    n = con.execute("SELECT COUNT(*) FROM evenements").fetchone()[0]
    print(f"Base créée : {DB}  ({n} événements)")

def cmd_verifier(_):
    con = connexion(); t = time.perf_counter()
    bf, an, _, cycles = verifier(con)
    print(f"Vérification terminée en {time.perf_counter() - t:.1f} s ({cycles} cycles d'inférence)\n")
    if an.empty:
        print("Aucune anomalie."); return
    print(an.groupby(["type_anomalie", "gravite"]).size().rename("nombre").to_string(), "\n")
    al = pd.Series([f.cle[0] for f in bf.du_type("alerte")]).value_counts()
    print("Alertes :", al.to_dict(), "| OF à risque :", len(bf.du_type("of_a_risque")))
    out = ROOT / "data" / "rapport_anomalies.csv"
    an.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"Rapport détaillé : {out}")

def cmd_corriger(_):
    con = connexion()
    _, an, _, _ = verifier(con)
    print("Corrections :", corriger(con, an))
    _, an2, _, _ = verifier(con)
    print("Anomalies restantes (validation humaine) :",
          an2.type_anomalie.value_counts().to_dict() if len(an2) else 0)

def cmd_tracer(a):
    con = connexion()
    if a.lot.upper().startswith("OF"):           # on part d'une commande : quels lots a-t-elle utilisés ?
        of = a.lot.upper()
        lots = pd.read_sql("""SELECT DISTINCT l.lot_id, l.composant, l.fournisseur, l.statut
                              FROM evenements e JOIN lots_composants l USING (lot_id)
                              WHERE e.of_id = ? AND e.type = 'consommation'""", con, params=(of,))
        if lots.empty:
            print(f"Commande {of} inconnue ou sans consommation de lot."); return
        print(f"Lots utilisés par {of} :\n")
        print(lots.to_string(index=False), "\n")
        for lot in lots.lot_id[lots.statut == "non conforme"]:
            print(f"Le lot {lot} est non conforme : voici toutes les commandes qui l'ont utilisé.\n")
            a.lot = lot; cmd_tracer(a)
        return
    df = pd.read_sql("SELECT * FROM v_tracabilite_lots WHERE lot_id = ?", con, params=(a.lot,))
    if df.empty:
        print("Lot inconnu ou jamais consommé."); return
    r = df.iloc[0]
    print(f"Lot {a.lot} — {r.composant}, fournisseur {r.fournisseur}, statut : {r.statut_lot}")
    print(f"{len(df)} OF touchés, {int((df.statut_of == 'expédié').sum())} déjà expédiés, "
          f"{int(df.quantite.sum())} pièces\n")
    print(df[["of_id", "produit_id", "quantite", "date_consommation", "statut_of"]].to_string(index=False))

def cmd_pourquoi(a):
    con = connexion()
    bf, _, _, _ = verifier(con)
    faits = [(t, c) for (t, c) in bf.justification if a.of in c]
    if not faits:
        print(f"Aucune conclusion du système sur {a.of}."); return
    for t, c in faits:
        print(expliquer(bf, t, c), "\n")

def cmd_trs(_):
    print(pd.read_sql("SELECT * FROM v_trs_poste", connexion()).to_string(index=False))

def cmd_regles(_):
    for r in sorted(REGLES, key=lambda r: r.priorite):
        print(f"{r.nom:4s} (niveau {r.priorite})  {r.description}")

def cmd_simuler(a):
    """Rejoue une situation opérationnelle sur une COPIE de la base et montre la réaction du système."""
    src = connexion()
    copie = ROOT / "data" / "simulation.db"
    con = sqlite3.connect(copie); src.backup(con); src.close()      # la vraie base reste intacte
    print(f"Simulation sur une copie de la base ({copie.name}).\n")

    if a.situation == "panne":
        of = con.execute("""SELECT of_id FROM evenements WHERE poste_id = 3 AND type = 'debut'
                            ORDER BY horodatage LIMIT 1 OFFSET 500""").fetchone()[0]
        print(f"1. SITUATION : panne de 3 h (180 min) au poste 3 - Câblage, pendant la commande {of}.")
        debut = con.execute("SELECT horodatage FROM evenements WHERE of_id=? AND poste_id=3 AND type='debut'", (of,)).fetchone()[0]
        con.execute("INSERT INTO evenements (of_id, poste_id, type, horodatage, valeur, resultat) VALUES (?, 3, 'arret', ?, 180, 'panne')", (of, debut))
        con.execute("UPDATE evenements SET horodatage = DATETIME(horodatage, '+180 minutes') WHERE of_id = ? AND poste_id = 3 AND type = 'fin'", (of,))
        print("   ATTENDU : une alerte maintenance sur cette commande, au poste 3.\n")
        bf, _, _, _ = verifier(con)
        alerte = bf.existe("alerte", ("arret_long", of, 3))
        print("2. RÉACTION DU SYSTÈME :")
        print(f"   Alerte « arrêt long » sur {of} au poste 3 : {'OUI' if alerte else 'NON'}\n")
        ok = alerte
        print("   Explication :"); print(expliquer(bf, "alerte", ("arret_long", of, 3)))

    elif a.situation == "rappel":
        lot = "L2010"
        print(f"1. SITUATION : le fournisseur rappelle le lot de visserie {lot} (déclaré non conforme).")
        print("   ATTENDU : toutes les commandes du lot retrouvées en moins de 2 s, et une alerte pour celles déjà expédiées.\n")
        bf0, _, _, _ = verifier(con)
        con.execute("UPDATE lots_composants SET statut = 'non conforme' WHERE lot_id = ?", (lot,))
        t = time.perf_counter()
        df = pd.read_sql("SELECT * FROM v_tracabilite_lots WHERE lot_id = ?", con, params=(lot,))
        duree = time.perf_counter() - t
        bf, _, _, _ = verifier(con)
        expedies = set(df.of_id[df.statut_of == "expédié"])
        alertes = {of for of in expedies if bf.existe("alerte", ("rappel_client", of))}
        print("2. RÉACTION DU SYSTÈME :")
        print(f"   Commandes retrouvées : {len(df)} en {duree:.2f} s, dont {len(expedies)} déjà expédiées")
        print(f"   Alertes de rappel client : {len(alertes)} sur {len(expedies)} commandes expédiées")
        print(f"   OF à risque : {len(bf0.du_type('of_a_risque'))} -> {len(bf.du_type('of_a_risque'))}\n")
        ok = len(df) > 0 and duree < 2 and alertes == expedies
        of = sorted(alertes)[0]
        print(f"   Explication pour {of} :"); print(expliquer(bf, "alerte", ("rappel_client", of)))

    else:  # ko
        of = con.execute("SELECT of_id FROM evenements WHERE type = 'controle_qualite' AND resultat = 'KO' LIMIT 1").fetchone()[0]
        print(f"1. SITUATION : la commande {of} a échoué au contrôle qualité (KO), mais quelqu'un l'envoie quand même à l'emballage.")
        print("   ATTENDU : une anomalie CRITIQUE sur cette commande.\n")
        _, an0, _, _ = verifier(con)
        fin4 = con.execute("SELECT horodatage FROM evenements WHERE of_id=? AND poste_id=4 AND type='fin'", (of,)).fetchone()[0]
        for typ, m in [("debut", 10), ("fin", 25)]:
            con.execute("INSERT INTO evenements (of_id, poste_id, type, horodatage) VALUES (?, 5, ?, DATETIME(?, ?))", (of, typ, fin4, f"+{m} minutes"))
        bf, an, _, _ = verifier(con)
        crit = an[an.type_anomalie == "expedie_malgre_cq_ko"]
        print("2. RÉACTION DU SYSTÈME :")
        print(f"   Anomalies critiques avant : {int((an0.type_anomalie == 'expedie_malgre_cq_ko').sum())}, après : {len(crit)}")
        if len(crit):
            print(f"   -> {crit.iloc[0].of_id}, gravité {crit.iloc[0].gravite} : {crit.iloc[0].correction}\n")
        ok = list(crit.of_id) == [of]
        print("   Explication :"); print(expliquer(bf, "anomalie", ("expedie_malgre_cq_ko", of, 5)))

    print(f"\n3. VERDICT : {'TEST RÉUSSI - le système réagit comme attendu' if ok else 'ÉCHEC - à analyser'}")
    con.close(); copie.unlink(missing_ok=True)

p = argparse.ArgumentParser(description="Démonstrateur MES avec système expert de vérification")
sp = p.add_subparsers(dest="commande", required=True)
for nom, f in [("init", cmd_init), ("verifier", cmd_verifier), ("corriger", cmd_corriger),
               ("trs", cmd_trs), ("regles", cmd_regles)]:
    sp.add_parser(nom).set_defaults(f=f)
x = sp.add_parser("tracer"); x.add_argument("lot"); x.set_defaults(f=cmd_tracer)
x = sp.add_parser("pourquoi"); x.add_argument("of"); x.set_defaults(f=cmd_pourquoi)
x = sp.add_parser("simuler"); x.add_argument("situation", choices=["panne", "rappel", "ko"]); x.set_defaults(f=cmd_simuler)
a = p.parse_args(); a.f(a)
