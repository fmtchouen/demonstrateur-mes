-- Démonstrateur MES — schéma de la base (SQLite, compatible PostgreSQL à quelques types près)
DROP TABLE IF EXISTS evenements;
DROP TABLE IF EXISTS ordres_fabrication;
DROP TABLE IF EXISTS lots_composants;
DROP TABLE IF EXISTS produits;
DROP TABLE IF EXISTS postes;

CREATE TABLE postes (
    poste_id                   INTEGER PRIMARY KEY,
    nom                        TEXT NOT NULL,
    temps_cycle_theorique_min  REAL NOT NULL CHECK (temps_cycle_theorique_min > 0)
);
CREATE TABLE produits (
    produit_id TEXT PRIMARY KEY,
    nom        TEXT NOT NULL,
    gamme      TEXT NOT NULL            -- suite des postes, ex. '1-2-4-5'
);
CREATE TABLE lots_composants (
    lot_id          TEXT PRIMARY KEY,
    composant       TEXT NOT NULL,
    poste_id        INTEGER NOT NULL REFERENCES postes(poste_id),
    fournisseur     TEXT NOT NULL,
    date_reception  TEXT NOT NULL,
    statut          TEXT NOT NULL CHECK (statut IN ('conforme', 'non conforme'))
);
CREATE TABLE ordres_fabrication (
    of_id           TEXT PRIMARY KEY,
    produit_id      TEXT NOT NULL REFERENCES produits(produit_id),
    quantite        INTEGER NOT NULL CHECK (quantite > 0),
    date_lancement  TEXT NOT NULL
);
CREATE TABLE evenements (
    evenement_id  INTEGER PRIMARY KEY,
    of_id         TEXT NOT NULL REFERENCES ordres_fabrication(of_id),
    poste_id      INTEGER NOT NULL REFERENCES postes(poste_id),
    type          TEXT NOT NULL,
    horodatage    TEXT NOT NULL,
    lot_id        TEXT REFERENCES lots_composants(lot_id),
    operateur     TEXT,
    valeur        REAL,
    resultat      TEXT
);
CREATE INDEX idx_evt_of    ON evenements(of_id, poste_id, type);
CREATE INDEX idx_evt_lot   ON evenements(lot_id);
CREATE INDEX idx_evt_poste ON evenements(poste_id, type);
