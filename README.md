# Démonstrateur MES avec système expert de vérification des données

Projet personnel — **Frédéric Marcel TCHOUEN**, élève ingénieur en 5e année à l'ESIGELEC (Big Data & Transformation Numérique).

## Objectif
Un **MES** (*Manufacturing Execution System*) est le logiciel de suivi de production d'une usine : il enregistre tout ce qui se passe sur les lignes. Ce projet simule la base de données d'un MES, puis construit un **système expert** qui :
- **vérifie** la base avec des règles métier et détecte les incohérences ;
- **explique** chacune de ses conclusions (quelle règle, à partir de quelles données) ;
- **corrige** ce qui peut l'être sans risque et transmet le reste à un humain ;
- est validé par des **tests qui simulent des situations réelles** (panne, rappel d'un lot fournisseur, contrôle qualité en échec).

## Données (simulées, reproductibles)
| Élément | Volume |
|---|---|
| Postes | 5 (Préparation, Assemblage mécanique, Câblage, Test fonctionnel, Emballage) |
| Produits | 3, chacun avec sa gamme |
| Ordres de fabrication (OF) | 2 000 |
| Événements MES | ~53 000 |
| Lots de composants | 160, dont 2 non conformes |
| Anomalies injectées | 140, de 5 types |

Un **dictionnaire de données** décrit chaque colonne, sa règle de qualité et son responsable métier : [`docs/Dictionnaire_de_donnees_MES.xlsx`](docs/Dictionnaire_de_donnees_MES.xlsx).

## Le système expert ([`src/systeme_expert.py`](src/systeme_expert.py))
- **Base de faits** : les étapes et les consommations de lots extraites de la base, plus les faits déduits.
- **Base de règles** : 11 règles métier « SI … ALORS … », sur 3 niveaux. Les règles de niveau 2 et 3 s'appuient sur des faits déjà déduits.
- **Moteur d'inférence** : chaînage avant jusqu'à ce qu'aucun fait nouveau n'apparaisse.
- **Explication** : chaque conclusion garde la règle et les faits qui l'ont produite.
- **Correction** : corrections automatiques quand la bonne valeur est certaine, validation humaine sinon, et journal de toutes les actions.

## Résultats
- **140 anomalies détectées sur 140**, sans fausse alerte.
- **85 corrigées automatiquement**, **55 transmises** pour validation humaine (contrôles qualité manquants, étapes non clôturées).
- Traçabilité d'un lot (tous les OF touchés) en **moins de 2 secondes**.
- **5 tests sur 5** réussis.

## Installation
```bash
pip install -r requirements.txt
python src/demo.py init
```

## Démonstration rapide
```bash
python src/demo.py verifier          # détection : 140 anomalies
python src/demo.py pourquoi OF00071  # raisonnement : R2 -> R9 -> R11
python src/demo.py corriger          # correction : 85 corrigées, 55 à valider
python src/demo.py simuler panne     # test d'une situation réelle
```

## Toutes les commandes
| Commande | Rôle |
|---|---|
| `python src/demo.py init` | Crée la base `data/mes.db` (et la remet à zéro) |
| `python src/demo.py regles` | Affiche les 11 règles |
| `python src/demo.py verifier` | Lance le système expert et exporte `data/rapport_anomalies.csv` |
| `python src/demo.py pourquoi OF00071` | Explique les conclusions du système sur un OF |
| `python src/demo.py tracer L3012` | Tous les OF qui ont consommé un lot |
| `python src/demo.py tracer OF00845` | Les lots d'un OF, et les OF liés si un lot est défectueux |
| `python src/demo.py corriger` | Corrige ce qui est sûr, transmet le reste |
| `python src/demo.py simuler panne` | Rejoue une situation réelle sur une copie de la base (`panne`, `rappel`, `ko`) |
| `python src/demo.py trs` | Taux de rendement synthétique par poste |
| `python tests/lancer_tests.py` | Lance les 5 tests (ou `python -m pytest -v`) |

## Structure
```
data/    données CSV (générées par src/generer_donnees.py)
sql/     schema.sql (tables, contraintes, index), indicateurs.sql (vues)
src/     generer_donnees.py, charger_base.py, systeme_expert.py, demo.py
tests/   test_scenarios.py, lancer_tests.py
docs/    guide utilisateur et plan de formation, explication du projet, dictionnaire de données
```

## Limites et pistes
- Les données sont simulées : l'intérêt est la méthode (règles, tests, traçabilité), pas les valeurs.
- Base SQLite pour la démonstration ; le schéma se porte sur PostgreSQL.
- Pistes : règles dans un fichier lisible par les experts métier, interface web, chaînage arrière pour répondre à « cet OF peut-il être livré ? ».
