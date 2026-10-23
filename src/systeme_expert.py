"""
Système expert de vérification de la base MES.

Architecture classique d'un système expert :
  * BASE DE FAITS   : faits extraits de la base de données (étapes, consommations, lots, OF)
                      + faits déduits au fil du raisonnement (anomalies, OF à risque, alertes) ;
  * BASE DE RÈGLES  : règles métier « SI conditions ALORS conclusion », écrites séparément
                      du moteur pour qu'un expert métier puisse les lire et les compléter ;
  * MOTEUR D'INFÉRENCE : chaînage avant — on applique les règles tant qu'elles produisent
                      de nouveaux faits (point fixe). Chaque fait déduit garde la règle et
                      les faits qui l'ont produit -> le système peut EXPLIQUER ses conclusions.
"""
from __future__ import annotations
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------- faits
@dataclass(frozen=True)
class Fait:
    type: str                 # ex. 'etape', 'anomalie', 'of_a_risque', 'alerte'
    cle: tuple                # identifiant du fait, ex. ('OF00012', 4)
    attributs: tuple = ()     # paires (nom, valeur), figées pour être hashables

    def get(self, nom, defaut=None):
        return dict(self.attributs).get(nom, defaut)

@dataclass
class BaseDeFaits:
    faits: dict = field(default_factory=dict)           # (type, cle) -> Fait
    justification: dict = field(default_factory=dict)   # (type, cle) -> (règle, [faits sources])

    def ajouter(self, fait: Fait, regle: str | None = None, sources: Iterable[Fait] = ()) -> bool:
        k = (fait.type, fait.cle)
        if k in self.faits:
            return False
        self.faits[k] = fait
        if regle:
            self.justification[k] = (regle, [(s.type, s.cle) for s in sources])
        return True

    def du_type(self, t: str):
        return [f for (ty, _), f in self.faits.items() if ty == t]

    def existe(self, t: str, cle: tuple) -> bool:
        return (t, cle) in self.faits

# --------------------------------------------------------------------------- règles
@dataclass
class Regle:
    nom: str
    description: str          # la règle en langage métier (affichée dans les rapports)
    priorite: int             # plus petit = appliqué en premier (résolution des conflits)
    declencher: Callable[[BaseDeFaits], Iterable[tuple[Fait, list[Fait]]]]

def anomalie(kind, of, poste, gravite, correction, **extra):
    return Fait("anomalie", (kind, of, poste),
                tuple(sorted(dict(gravite=gravite, correction=correction, **extra).items())))

def r_fin_avant_debut(bf):
    for e in bf.du_type("etape"):
        if e.get("debut") and e.get("fin") and e.get("fin") < e.get("debut"):
            yield anomalie("fin_avant_debut", *e.cle, "moyenne",
                           "fin recalculée = début + quantité × temps de cycle (à valider)"), [e]

def r_cq_manquant(bf):
    for e in bf.du_type("etape"):
        if e.cle[1] == 4 and e.get("fin") and e.get("cq") is None:
            yield anomalie("controle_qualite_manquant", *e.cle, "haute",
                           "OF bloqué jusqu'à saisie du contrôle"), [e]

def r_etape_non_cloturee(bf):
    # Un poste a démarré alors que le poste précédent de la gamme n'est pas terminé
    for e in bf.du_type("etape"):
        prec = e.get("poste_precedent")
        if prec is None:
            continue
        p = bf.faits.get(("etape", (e.cle[0], prec)))
        if p is not None and p.get("fin") is None:
            yield anomalie("etape_non_cloturee", e.cle[0], prec, "haute",
                           "clôture manquante : vérifier la saisie au poste"), [e, p]

def r_poste_hors_gamme(bf):
    for e in bf.du_type("etape"):
        if not e.get("dans_gamme"):
            yield anomalie("poste_hors_gamme", *e.cle, "moyenne",
                           "événements à réaffecter ou supprimer"), [e]

def r_lot_non_receptionne(bf):
    for c in bf.du_type("consommation"):
        if c.get("date_reception") is None or c.get("horodatage") < c.get("date_reception"):
            yield anomalie("lot_non_receptionne", c.cle[0], c.cle[1], "moyenne",
                           "numéro de lot à corriger (lot en stock à cette date proposé)",
                           lot=c.get("lot_id"), lot_propose=c.get("lot_en_stock")), [c]

def r_quantite_incoherente(bf):
    for e in bf.du_type("etape"):
        q, qof = e.get("qte_bonne"), e.get("qte_of")
        if q is not None and q + (e.get("qte_rebut") or 0) > qof:
            yield anomalie("quantite_incoherente", *e.cle, "moyenne",
                           "quantité bonne plafonnée à la quantité de l'OF moins les rebuts"), [e]

def r_arret_long(bf):
    for e in bf.du_type("etape"):
        if (e.get("arret_min") or 0) >= 60:
            yield Fait("alerte", ("arret_long", *e.cle),
                       (("message", f"arrêt de {e.get('arret_min'):.0f} min au poste {e.cle[1]}"),)), [e]

# --- règles de 2e niveau : elles raisonnent sur des faits DÉDUITS (chaînage avant)
def r_of_a_risque_lot(bf):
    for c in bf.du_type("consommation"):
        if c.get("statut_lot") == "non conforme":
            yield Fait("of_a_risque", (c.cle[0],),
                       (("cause", f"lot non conforme {c.get('lot_id')}"),)), [c]

def r_of_a_risque_qualite(bf):
    for a in bf.du_type("anomalie"):
        if a.cle[0] in ("controle_qualite_manquant", "etape_non_cloturee") and a.cle[2] == 4:
            yield Fait("of_a_risque", (a.cle[1],), (("cause", "contrôle qualité non garanti"),)), [a]

def r_expedie_malgre_ko(bf):
    for e in bf.du_type("etape"):
        if e.cle[1] == 4 and e.get("cq") == "KO":
            emb = bf.faits.get(("etape", (e.cle[0], 5)))
            if emb is not None:
                yield anomalie("expedie_malgre_cq_ko", e.cle[0], 5, "critique",
                               "bloquer l'expédition et rappeler le lot"), [e, emb]

def r_alerte_rappel(bf):
    for r in bf.du_type("of_a_risque"):
        emb = bf.faits.get(("etape", (r.cle[0], 5)))
        if emb is not None and emb.get("fin"):
            yield Fait("alerte", ("rappel_client", r.cle[0]),
                       (("message", f"OF {r.cle[0]} expédié alors qu'il est à risque ({r.get('cause')})"),)), [r, emb]

REGLES = [
    Regle("R1", "SI la fin d'une étape est antérieure à son début ALORS anomalie d'horodatage", 1, r_fin_avant_debut),
    Regle("R2", "SI une étape de test est terminée sans contrôle qualité ALORS anomalie haute", 1, r_cq_manquant),
    Regle("R3", "SI un poste démarre alors que le poste précédent de la gamme n'est pas clôturé ALORS anomalie", 1, r_etape_non_cloturee),
    Regle("R4", "SI un OF passe par un poste absent de la gamme de son produit ALORS anomalie", 1, r_poste_hors_gamme),
    Regle("R5", "SI un lot est consommé avant sa date de réception ALORS anomalie de traçabilité", 1, r_lot_non_receptionne),
    Regle("R6", "SI la quantité déclarée dépasse la quantité de l'OF ALORS anomalie", 1, r_quantite_incoherente),
    Regle("R7", "SI un arrêt dure 60 min ou plus ALORS alerte maintenance", 1, r_arret_long),
    Regle("R8", "SI un OF a consommé un lot non conforme ALORS OF à risque", 2, r_of_a_risque_lot),
    Regle("R9", "SI l'OF a une anomalie de contrôle au poste de test ALORS OF à risque", 2, r_of_a_risque_qualite),
    Regle("R10", "SI le contrôle qualité est KO ET l'OF est passé à l'emballage ALORS anomalie critique", 2, r_expedie_malgre_ko),
    Regle("R11", "SI un OF est à risque ET il a été expédié ALORS alerte rappel client", 3, r_alerte_rappel),
]

# --------------------------------------------------------------------------- moteur
def chainage_avant(bf: BaseDeFaits, regles=REGLES, max_cycles=20):
    """Applique les règles par priorité jusqu'à ce qu'aucun fait nouveau n'apparaisse."""
    trace = []
    for cycle in range(1, max_cycles + 1):
        nouveaux = 0
        for r in sorted(regles, key=lambda r: r.priorite):
            for fait, sources in list(r.declencher(bf)):
                if bf.ajouter(fait, r.nom, sources):
                    nouveaux += 1
                    trace.append((cycle, r.nom, fait.type, fait.cle))
        if nouveaux == 0:
            return trace, cycle
    return trace, max_cycles

def expliquer(bf: BaseDeFaits, t: str, cle: tuple, niveau=0) -> str:
    """Remonte la chaîne de justification d'un fait (« pourquoi ? »)."""
    k = (t, cle)
    lignes = ["  " * niveau + f"- {t} {cle}"]
    fait = bf.faits.get(k)
    if fait is not None:                       # détails utiles : lot, cause, message, poste…
        details = {n: v for n, v in fait.attributs
                   if n in ("lot_id", "statut_lot", "cause", "message", "cq", "debut", "fin") and v is not None}
        if details:
            lignes[-1] += "  " + str(details)
    if k in bf.justification:
        regle, sources = bf.justification[k]
        desc = next(r.description for r in REGLES if r.nom == regle)
        lignes[-1] += f"  <= {regle} : {desc}"
        for st, sc in sources:
            lignes.append(expliquer(bf, st, sc, niveau + 1))
    else:
        lignes[-1] += "  (fait issu de la base de données)"
    return "\n".join(lignes)

# --------------------------------------------------------------------------- faits depuis la base
def faits_depuis_base(con: sqlite3.Connection) -> BaseDeFaits:
    bf = BaseDeFaits()
    gammes = {p: list(map(int, g.split("-"))) for p, g in con.execute("SELECT produit_id, gamme FROM produits")}
    et = pd.read_sql("""SELECT s.*, o.produit_id, o.quantite AS qte_of
                        FROM v_etapes s JOIN ordres_fabrication o USING (of_id)""", con)
    for r in et.itertuples(index=False):
        g = gammes[r.produit_id]
        dans = r.poste_id in g
        prec = g[g.index(r.poste_id) - 1] if dans and g.index(r.poste_id) > 0 else None
        attrs = dict(debut=r.debut, fin=r.fin, cq=r.cq, arret_min=r.arret_min,
                     qte_bonne=None if pd.isna(r.qte_bonne) else r.qte_bonne,
                     qte_rebut=None if pd.isna(r.qte_rebut) else r.qte_rebut,
                     qte_of=r.qte_of, dans_gamme=dans, poste_precedent=prec)
        attrs = {k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in attrs.items()}
        bf.ajouter(Fait("etape", (r.of_id, r.poste_id), tuple(sorted(attrs.items(), key=lambda x: x[0]))))
    co = pd.read_sql("""SELECT c.of_id, c.poste_id, c.lot_id, c.horodatage,
                               l.date_reception, l.statut AS statut_lot
                        FROM evenements c LEFT JOIN lots_composants l USING (lot_id)
                        WHERE c.type = 'consommation'""", con)
    lots = pd.read_sql("SELECT lot_id, poste_id, date_reception FROM lots_composants ORDER BY date_reception", con)
    for r in co.itertuples(index=False):
        dispo = lots[(lots.poste_id == r.poste_id) & (lots.date_reception <= r.horodatage)]
        attrs = dict(lot_id=r.lot_id, horodatage=r.horodatage, date_reception=r.date_reception,
                     statut_lot=r.statut_lot, lot_en_stock=dispo.lot_id.iloc[-1] if len(dispo) else None)
        bf.ajouter(Fait("consommation", (r.of_id, r.poste_id), tuple(sorted(attrs.items()))))
    return bf

def verifier(con: sqlite3.Connection):
    bf = faits_depuis_base(con)
    trace, cycles = chainage_avant(bf)
    an = pd.DataFrame([dict(type_anomalie=f.cle[0], of_id=f.cle[1], poste_id=f.cle[2], **dict(f.attributs))
                       for f in bf.du_type("anomalie")])
    return bf, an, trace, cycles

# --------------------------------------------------------------------------- correction
def corriger(con: sqlite3.Connection, anomalies: pd.DataFrame) -> dict:
    """Applique les corrections sûres ; marque les autres « à valider » dans une table de suivi."""
    con.execute("""CREATE TABLE IF NOT EXISTS journal_corrections (
                     type_anomalie TEXT, of_id TEXT, poste_id INTEGER,
                     action TEXT, statut TEXT, horodatage TEXT DEFAULT CURRENT_TIMESTAMP)""")
    n = {"corrigé": 0, "à valider": 0}
    for a in anomalies.itertuples(index=False):
        statut = "à valider"
        if a.type_anomalie == "lot_non_receptionne" and isinstance(getattr(a, "lot_propose", None), str):
            con.execute("""UPDATE evenements SET lot_id = ? WHERE of_id = ? AND poste_id = ?
                           AND type = 'consommation'""", (a.lot_propose, a.of_id, a.poste_id))
            statut = "corrigé"
        elif a.type_anomalie == "quantite_incoherente":
            con.execute("""UPDATE evenements SET valeur = (SELECT quantite FROM ordres_fabrication o
                             WHERE o.of_id = evenements.of_id)
                             - CAST(SUBSTR(resultat, 7) AS INTEGER)
                           WHERE of_id = ? AND poste_id = ? AND type = 'declaration_quantite'""",
                        (a.of_id, a.poste_id))
            statut = "corrigé"
        elif a.type_anomalie == "fin_avant_debut":
            con.execute("""UPDATE evenements SET horodatage = (
                             SELECT STRFTIME('%Y-%m-%d %H:%M:%S', d.horodatage,
                                    '+' || CAST(ROUND(o.quantite * p.temps_cycle_theorique_min * 60) AS INTEGER) || ' seconds')
                             FROM evenements d, ordres_fabrication o, postes p
                             WHERE d.of_id = evenements.of_id AND d.poste_id = evenements.poste_id
                               AND d.type = 'debut' AND o.of_id = d.of_id AND p.poste_id = d.poste_id)
                           WHERE of_id = ? AND poste_id = ? AND type = 'fin'""", (a.of_id, a.poste_id))
            statut = "corrigé"
        con.execute("INSERT INTO journal_corrections (type_anomalie, of_id, poste_id, action, statut) VALUES (?,?,?,?,?)",
                    (a.type_anomalie, a.of_id, int(a.poste_id), a.correction, statut))
        n[statut] += 1
    con.commit()
    return n

if __name__ == "__main__":
    import sys, time
    sys.path.insert(0, str(Path(__file__).parent))
    from charger_base import charger
    con = charger()
    t = time.perf_counter()
    bf, an, trace, cycles = verifier(con)
    print(f"Faits en base : {len(bf.faits)} | règles : {len(REGLES)} | cycles d'inférence : {cycles} "
          f"| durée : {time.perf_counter() - t:.1f} s")
    print(an.type_anomalie.value_counts().to_string())
    print("Alertes :", pd.Series([f.cle[0] for f in bf.du_type("alerte")]).value_counts().to_dict())
    print("OF à risque :", len(bf.du_type("of_a_risque")))
    # Comparaison avec les anomalies injectées
    vrai = pd.read_csv(ROOT / "data" / "anomalies_injectees_NE_PAS_UTILISER.csv")
    k = lambda d: set(zip(d.type_anomalie, d.of_id, d.poste_id.astype(int)))
    trouve, attendu = k(an), k(vrai)
    print(f"Rappel : {len(trouve & attendu)}/{len(attendu)} | détections hors injection : {len(trouve - attendu)}")
    print(sorted(trouve - attendu)[:10])
    exemple = next(f for f in bf.du_type("alerte") if f.cle[0] == "rappel_client")
    print(expliquer(bf, exemple.type, exemple.cle))
    print(corriger(con, an))
    bf2, an2, _, _ = verifier(con)
    print("Après correction :", an2.type_anomalie.value_counts().to_dict())
