-- Vue des étapes : une ligne par (OF, poste) avec début, fin, arrêts, quantités
DROP VIEW IF EXISTS v_etapes;
CREATE VIEW v_etapes AS
SELECT e.of_id, e.poste_id,
       MAX(CASE WHEN e.type = 'debut' THEN e.horodatage END)                AS debut,
       MAX(CASE WHEN e.type = 'fin'   THEN e.horodatage END)                AS fin,
       COALESCE(SUM(CASE WHEN e.type = 'arret' THEN e.valeur END), 0)       AS arret_min,
       MAX(CASE WHEN e.type = 'declaration_quantite' THEN e.valeur END)     AS qte_bonne,
       MAX(CASE WHEN e.type = 'declaration_quantite'
                THEN CAST(SUBSTR(e.resultat, 7) AS INTEGER) END)            AS qte_rebut,
       MAX(CASE WHEN e.type = 'controle_qualite' THEN e.resultat END)       AS cq
FROM evenements e
GROUP BY e.of_id, e.poste_id;

-- TRS (taux de rendement synthétique) par poste = Disponibilité × Performance × Qualité
-- Calculé uniquement sur les étapes cohérentes (début et fin présents, fin > début)
DROP VIEW IF EXISTS v_trs_poste;
CREATE VIEW v_trs_poste AS
WITH base AS (
    SELECT s.poste_id, p.nom, p.temps_cycle_theorique_min AS tc,
           (JULIANDAY(s.fin) - JULIANDAY(s.debut)) * 1440 AS duree_min,
           s.arret_min, s.qte_bonne, s.qte_rebut
    FROM v_etapes s JOIN postes p USING (poste_id)
    WHERE s.debut IS NOT NULL AND s.fin IS NOT NULL AND s.fin > s.debut
      AND s.qte_bonne IS NOT NULL
)
SELECT poste_id, nom,
       COUNT(*)                                                    AS nb_etapes,
       ROUND(SUM(duree_min) / 60.0, 1)                             AS temps_ouverture_h,
       ROUND(1 - SUM(arret_min) / SUM(duree_min), 3)               AS disponibilite,
       ROUND(SUM(tc * (qte_bonne + qte_rebut)) / SUM(duree_min - arret_min), 3) AS performance,
       ROUND(SUM(qte_bonne) * 1.0 / SUM(qte_bonne + qte_rebut), 3) AS qualite,
       ROUND((1 - SUM(arret_min) / SUM(duree_min))
             * (SUM(tc * (qte_bonne + qte_rebut)) / SUM(duree_min - arret_min))
             * (SUM(qte_bonne) * 1.0 / SUM(qte_bonne + qte_rebut)), 3) AS trs
FROM base
GROUP BY poste_id, nom
ORDER BY poste_id;

-- Traçabilité descendante : à partir d'un lot de composant, tous les OF touchés et leur statut
DROP VIEW IF EXISTS v_tracabilite_lots;
CREATE VIEW v_tracabilite_lots AS
SELECT l.lot_id, l.composant, l.fournisseur, l.statut AS statut_lot,
       c.of_id, o.produit_id, o.quantite, c.horodatage AS date_consommation,
       CASE WHEN EXISTS (SELECT 1 FROM evenements f
                         WHERE f.of_id = c.of_id AND f.poste_id = 5 AND f.type = 'fin')
            THEN 'expédié' ELSE 'en cours / bloqué' END AS statut_of
FROM lots_composants l
JOIN evenements c ON c.lot_id = l.lot_id AND c.type = 'consommation'
JOIN ordres_fabrication o ON o.of_id = c.of_id;
