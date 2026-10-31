-- Additive migration: reference knowledge on copepod developmental stages, for
-- FILET (stage codes of the abundance export) and UVP (no stage field), so an
-- agent can read what a stage code means, how stages are ordered and which
-- codes are aggregates, instead of guessing. Reference table, not occurrence
-- data: no row security (like taxon_mapping, marine_zone).
--
-- What is established in this repository and what is not is kept explicit:
--   * established: the 18 codes (CHECK on warehouse.filet_abundance.stage and
--     scripts/populate_filet.py STAGES), is_aggregate (generated column of
--     filet_abundance), filet_has_biomass (columns present in the FILET export,
--     STAGES_WITH_BIOMASS), and "never add an aggregate to its components"
--     (docs/FILET_EXPORT_REVIEW.md);
--   * not established here: the exact meaning of COP_NS / NAUP_NS and the
--     composition of COPEPODID / NAUPLIUS / ALL_STAGES (adults included or not).
--     The lab's FILET dictionary (copepod abund&biomass-metadata.csv) defines
--     them; it is not loaded in the warehouse. Those rows say "à confirmer"
--     rather than guess. Labels of N1-N6, C1-C5, M, F follow the usual copepod
--     stage naming, also flagged for confirmation against that dictionary.
CREATE TABLE IF NOT EXISTS warehouse.copepod_stage (
    stage_code text PRIMARY KEY,
    label_fr text NOT NULL,
    life_phase text NOT NULL CHECK (life_phase IN ('nauplius', 'copépodite', 'adulte', 'agrégat')),
    development_order integer,
    sex text CHECK (sex IN ('mâle', 'femelle')),
    is_aggregate boolean NOT NULL,
    aggregate_of text,
    filet_has_biomass boolean NOT NULL,
    definition_status text NOT NULL CHECK (definition_status IN ('convention usuelle, à confirmer', 'à confirmer')),
    note text
);

INSERT INTO warehouse.copepod_stage AS s
    (stage_code, label_fr, life_phase, development_order, sex, is_aggregate, aggregate_of, filet_has_biomass,
     definition_status, note)
VALUES
    ('N1', 'nauplius, stade 1', 'nauplius', 1, NULL, false, NULL, false, 'convention usuelle, à confirmer', NULL),
    ('N2', 'nauplius, stade 2', 'nauplius', 2, NULL, false, NULL, false, 'convention usuelle, à confirmer', NULL),
    ('N3', 'nauplius, stade 3', 'nauplius', 3, NULL, false, NULL, false, 'convention usuelle, à confirmer', NULL),
    ('N4', 'nauplius, stade 4', 'nauplius', 4, NULL, false, NULL, false, 'convention usuelle, à confirmer', NULL),
    ('N5', 'nauplius, stade 5', 'nauplius', 5, NULL, false, NULL, false, 'convention usuelle, à confirmer', NULL),
    ('N6', 'nauplius, stade 6', 'nauplius', 6, NULL, false, NULL, false, 'convention usuelle, à confirmer', NULL),
    ('NAUP_NS', 'nauplius, stade non précisé (sens de NS à confirmer)', 'nauplius', NULL, NULL, false, NULL, false,
     'à confirmer', 'Nauplius dont le stade n''est pas attribué, d''après le code; définition exacte dans le dictionnaire FILET.'),
    ('C1', 'copépodite, stade 1', 'copépodite', 7, NULL, false, NULL, true, 'convention usuelle, à confirmer', NULL),
    ('C2', 'copépodite, stade 2', 'copépodite', 8, NULL, false, NULL, true, 'convention usuelle, à confirmer', NULL),
    ('C3', 'copépodite, stade 3', 'copépodite', 9, NULL, false, NULL, true, 'convention usuelle, à confirmer', NULL),
    ('C4', 'copépodite, stade 4', 'copépodite', 10, NULL, false, NULL, true, 'convention usuelle, à confirmer', NULL),
    ('C5', 'copépodite, stade 5', 'copépodite', 11, NULL, false, NULL, true, 'convention usuelle, à confirmer', NULL),
    ('COP_NS', 'copépodite, stade non précisé (sens de NS à confirmer)', 'copépodite', NULL, NULL, false, NULL, true,
     'à confirmer', 'Copépodite dont le stade n''est pas attribué, d''après le code; définition exacte dans le dictionnaire FILET.'),
    ('M', 'adulte mâle', 'adulte', 12, 'mâle', false, NULL, true, 'convention usuelle, à confirmer', NULL),
    ('F', 'adulte femelle', 'adulte', 12, 'femelle', false, NULL, true, 'convention usuelle, à confirmer', NULL),
    ('COPEPODID', 'total copépodites (agrégat)', 'agrégat', NULL, NULL, true,
     'copépodites C1-C5 et COP_NS; inclusion des adultes M et F à confirmer', true, 'à confirmer',
     'Ne jamais additionner à ses composants.'),
    ('NAUPLIUS', 'total nauplii (agrégat)', 'agrégat', NULL, NULL, true, 'N1-N6 et NAUP_NS (à confirmer)', false,
     'à confirmer', 'Ne jamais additionner à ses composants. Pas de biomasse dans l''export FILET.'),
    ('ALL_STAGES', 'tous stades (agrégat)', 'agrégat', NULL, NULL, true,
     'ensemble des stades du taxon (composition exacte à confirmer)', false, 'à confirmer',
     'Ne jamais additionner aux autres stades. Pas de biomasse dans l''export FILET.')
ON CONFLICT (stage_code) DO UPDATE SET
    label_fr = EXCLUDED.label_fr, life_phase = EXCLUDED.life_phase, development_order = EXCLUDED.development_order,
    sex = EXCLUDED.sex, is_aggregate = EXCLUDED.is_aggregate, aggregate_of = EXCLUDED.aggregate_of,
    filet_has_biomass = EXCLUDED.filet_has_biomass, definition_status = EXCLUDED.definition_status, note = EXCLUDED.note;

COMMENT ON TABLE warehouse.copepod_stage IS
    'Référence des stades de développement des copépodes (codes FILET). Établi dans le dépôt : les codes, is_aggregate, filet_has_biomass, et la règle de ne jamais additionner un agrégat à ses composants. Libellés et composition des agrégats : definition_status indique ce qui reste à confirmer avec le dictionnaire FILET du labo.';

CREATE OR REPLACE VIEW explore.copepod_stages AS
SELECT stage_code, label_fr, life_phase, development_order, sex, is_aggregate, aggregate_of, filet_has_biomass,
       definition_status, note
FROM warehouse.copepod_stage;

COMMENT ON VIEW explore.copepod_stages IS
    'Stades de développement des copépodes : une ligne par code de stade FILET (N1-N6, NAUP_NS, C1-C5, COP_NS, M, F, agrégats COPEPODID, NAUPLIUS, ALL_STAGES). Joindre sur filet_data.stage ou filet_uvp_abundance.filet_stage. UVP : aucun champ de stade dans le warehouse; un stade n''existe côté UVP que si la catégorie EcoTaxa (taxon_key) le nomme, et sa correspondance avec un stade FILET passe par taxon_mapping, décision d''un biologiste. definition_status signale ce qui reste à confirmer : ne pas présenter ces libellés comme validés.';
