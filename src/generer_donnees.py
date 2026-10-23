"""
Démonstrateur MES (Manufacturing Execution System) — génération des données.

Ligne d'assemblage de 5 postes, 3 produits. Chaque ordre de fabrication (OF) suit
une GAMME (suite de postes propre au produit). À chaque poste, le MES enregistre :
début, affectation de l'opérateur, consommation d'un lot de composant, mesures,
contrôle qualité, déclaration des quantités (bonnes / rebuts), arrêts, fin.

Pour tester le système expert de vérification, on injecte volontairement des
anomalies (erreurs typiques d'une base « préconstruite »). Leur liste est gardée
à part pour mesurer si les règles les retrouvent toutes.
"""
import numpy as np
import pandas as pd
from pathlib import Path

rng = np.random.default_rng(7)
OUT = Path(__file__).resolve().parents[1] / "data"
OUT.mkdir(exist_ok=True)
T0 = pd.Timestamp("2026-01-05")

POSTES = pd.DataFrame({
    "poste_id": [1, 2, 3, 4, 5],
    "nom": ["Préparation", "Assemblage mécanique", "Câblage", "Test fonctionnel", "Emballage"],
    "temps_cycle_theorique_min": [0.6, 1.2, 1.0, 0.8, 0.4],   # par pièce
})
PRODUITS = pd.DataFrame({
    "produit_id": ["P1", "P2", "P3"],
    "nom": ["Coffret électrique", "Boîtier capteur", "Armoire de commande"],
    "gamme": ["1-2-3-4-5", "1-2-4-5", "1-2-3-4-5"],
})
COMPOSANTS = {1: "Châssis", 2: "Visserie", 3: "Faisceau de câbles", 5: "Carton"}
OPERATEURS = {p: [f"OP{p}{k}" for k in range(1, 5)] for p in range(1, 6)}

# ---- Lots de composants réceptionnés ----
lots = []
for poste, comp in COMPOSANTS.items():
    for k in range(40):
        lots.append(dict(lot_id=f"L{poste}{k:03d}", composant=comp, poste_id=poste,
                         fournisseur=f"F{int(rng.integers(1, 6))}",
                         date_reception=T0 + pd.Timedelta(days=4 * k), statut="conforme"))
lots = pd.DataFrame(lots)
# Deux lots déclarés non conformes après coup (rappel fournisseur) -> scénario de traçabilité
lots.loc[lots.lot_id.isin(["L3012", "L1025"]), "statut"] = "non conforme"

def lot_en_stock(poste, ts):
    """Dernier lot réceptionné à la date ts pour le composant du poste."""
    k = min(int((ts - T0).days // 4), 39)
    return f"L{poste}{max(k, 0):03d}"

# ---- OF et événements ----
ofs, ev = [], []
def add(of, poste, typ, ts, lot=None, operateur=None, valeur=None, resultat=None):
    ev.append(dict(of_id=of, poste_id=poste, type=typ, horodatage=ts, lot_id=lot,
                   operateur=operateur, valeur=valeur, resultat=resultat))

t = T0 + pd.Timedelta(hours=30)
for i in range(1, 2001):
    prod = PRODUITS.iloc[int(rng.integers(0, 3))]
    of = f"OF{i:05d}"
    qte = int(rng.integers(10, 40))
    t += pd.Timedelta(minutes=int(rng.integers(40, 120)))
    ofs.append(dict(of_id=of, produit_id=prod.produit_id, quantite=qte, date_lancement=t))
    ts = t
    for poste in map(int, prod.gamme.split("-")):
        tc = POSTES.temps_cycle_theorique_min[poste - 1]
        ts += pd.Timedelta(minutes=int(rng.integers(5, 45)))
        add(of, poste, "debut", ts)
        add(of, poste, "affectation_operateur", ts, operateur=str(rng.choice(OPERATEURS[poste])))
        if poste in COMPOSANTS:
            add(of, poste, "consommation", ts + pd.Timedelta(minutes=1), lot=lot_en_stock(poste, ts))
        duree = qte * tc * rng.uniform(1.0, 1.4)                  # pertes de performance
        if rng.random() < 0.06:                                    # arrêt (panne, réglage)
            arret = int(rng.integers(10, 90))
            add(of, poste, "arret", ts + pd.Timedelta(minutes=duree / 2), valeur=arret,
                resultat=str(rng.choice(["panne", "réglage", "manque composant"])))
            duree += arret
        fin = ts + pd.Timedelta(minutes=duree)
        if poste == 2:
            add(of, poste, "mesure_couple_Nm", fin - pd.Timedelta(minutes=2),
                valeur=round(rng.normal(12, 0.4), 2))
        if poste == 4:
            add(of, poste, "mesure_tension_V", fin - pd.Timedelta(minutes=3), valeur=round(rng.normal(230, 2), 1))
            add(of, poste, "mesure_isolement_MOhm", fin - pd.Timedelta(minutes=2), valeur=round(rng.uniform(50, 500), 0))
            cq_ok = rng.random() > 0.03
            add(of, poste, "controle_qualite", fin - pd.Timedelta(minutes=1),
                resultat="OK" if cq_ok else "KO")
        rebut = int(rng.binomial(qte, 0.02))
        add(of, poste, "declaration_quantite", fin, valeur=qte - rebut, resultat=f"rebut={rebut}")
        add(of, poste, "fin", fin)
        ts = fin
        if poste == 4 and not cq_ok:      # OF bloqué : il ne part pas à l'emballage
            break

ofs = pd.DataFrame(ofs)
ev = pd.DataFrame(ev)
ev.insert(0, "evenement_id", np.arange(1, len(ev) + 1))
anom = []
def log(kind, idx):
    for j in idx:
        anom.append(dict(type_anomalie=kind, evenement_id=int(ev.at[j, "evenement_id"]),
                         of_id=ev.at[j, "of_id"], poste_id=int(ev.at[j, "poste_id"])))

# A1 : fin enregistrée AVANT le début (erreur d'horodatage)
idx = rng.choice(ev.index[ev.type == "fin"], 40, replace=False)
ev.loc[idx, "horodatage"] = ev.loc[idx, "horodatage"] - pd.Timedelta(hours=30)
log("fin_avant_debut", idx)
# A2 : contrôle qualité manquant au poste de test
idx = rng.choice(ev.index[ev.type == "controle_qualite"], 30, replace=False)
log("controle_qualite_manquant", idx)
ev = ev.drop(index=idx)
# A3 : lot consommé AVANT sa date de réception
idx = rng.choice(ev.index[(ev.type == "consommation") & (ev.horodatage < T0 + pd.Timedelta(days=100))],
                 25, replace=False)
ev.loc[idx, "lot_id"] = ev.loc[idx, "poste_id"].map(lambda p: f"L{p}039")
log("lot_non_receptionne", idx)
# A4 : OF déclaré au poste d'emballage sans fin au poste de test (étape sautée)
cand = ev.index[(ev.type == "fin") & (ev.poste_id == 4)].difference(
    ev.index[ev.evenement_id.isin([a["evenement_id"] for a in anom])])
idx = rng.choice(cand, 25, replace=False)
log("etape_non_cloturee", idx)
ev = ev.drop(index=idx)
# A5 : quantité déclarée supérieure à la quantité de l'OF
idx = rng.choice(ev.index[ev.type == "declaration_quantite"], 20, replace=False)
ev.loc[idx, "valeur"] = ev.loc[idx, "of_id"].map(ofs.set_index("of_id").quantite) + 5
log("quantite_incoherente", idx)

ev["horodatage"] = pd.to_datetime(ev.horodatage).dt.floor("s")
ofs["date_lancement"] = ofs.date_lancement.dt.floor("s")
ev = ev.sort_values(["of_id", "horodatage", "evenement_id"]).reset_index(drop=True)
POSTES.to_csv(OUT / "postes.csv", index=False)
PRODUITS.to_csv(OUT / "produits.csv", index=False)
lots.to_csv(OUT / "lots_composants.csv", index=False)
ofs.to_csv(OUT / "ordres_fabrication.csv", index=False)
ev.to_csv(OUT / "evenements.csv", index=False)
pd.DataFrame(anom).to_csv(OUT / "anomalies_injectees_NE_PAS_UTILISER.csv", index=False)
print(f"{len(ofs)} OF | {len(ev)} événements | {len(lots)} lots | {len(anom)} anomalies injectées")
