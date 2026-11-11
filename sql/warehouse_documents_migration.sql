-- Documents écrits consultables par les agents : protocoles, notes de méthode, rapports, publications.
--
-- warehouse.document          : un document (clé stable doc_key, titre, type, auteur, date, lien, empreinte).
-- warehouse.document_section  : son texte découpé en sections (titre de section, corps), indexé en texte intégral.
-- catalogue.documents, catalogue.document_sections : lecture par les comptes; un document rattaché à une
--   version de jeu de données n'est visible que si cette version l'est : la sécurité par ligne des tables
--   (même règle que les données) filtre seule, vues et fonctions comprises (propriétaire soumis à FORCE).
-- catalogue.search_documents(q) : recherche plein texte (français et anglais), meilleurs extraits d'abord.
--
-- Chargement : scripts/add_warehouse_document.py (un fichier .md ou .txt), et docs/warehouse_documents.json
-- (documents du dépôt, rechargés à chaque déploiement). Le texte est conservé tel quel; aucune
-- interprétation. Additive et relançable.

-- Accent-insensitive search (« copepode » finds « copépode »): French and English configurations with
-- unaccent before stemming. unaccent is a trusted extension (PostgreSQL 13+).
CREATE EXTENSION IF NOT EXISTS unaccent;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_ts_config c JOIN pg_namespace n ON n.oid = c.cfgnamespace
                   WHERE n.nspname = 'warehouse' AND c.cfgname = 'french_unaccent') THEN
        CREATE TEXT SEARCH CONFIGURATION warehouse.french_unaccent (COPY = pg_catalog.french);
        ALTER TEXT SEARCH CONFIGURATION warehouse.french_unaccent
            ALTER MAPPING FOR hword, hword_part, word WITH unaccent, french_stem;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_ts_config c JOIN pg_namespace n ON n.oid = c.cfgnamespace
                   WHERE n.nspname = 'warehouse' AND c.cfgname = 'english_unaccent') THEN
        CREATE TEXT SEARCH CONFIGURATION warehouse.english_unaccent (COPY = pg_catalog.english);
        ALTER TEXT SEARCH CONFIGURATION warehouse.english_unaccent
            ALTER MAPPING FOR hword, hword_part, word WITH unaccent, english_stem;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS warehouse.document (
    id bigserial PRIMARY KEY,
    doc_key text NOT NULL UNIQUE CHECK (doc_key ~ '^[a-z0-9][a-z0-9_-]*$'),
    title text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('protocole', 'méthode', 'note', 'rapport', 'publication', 'autre')),
    language text NOT NULL DEFAULT 'fr',
    author text,
    document_date date,
    url text,
    source_name text NOT NULL,
    dataset_key text,
    dataset_version_id bigint REFERENCES warehouse.dataset_version (id),
    summary text,
    sha256 text NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE warehouse.document IS
    'Document écrit consultable par les agents (texte d''origine, non interprété); doc_key stable, sha256 du fichier chargé.';

CREATE TABLE IF NOT EXISTS warehouse.document_section (
    document_id bigint NOT NULL REFERENCES warehouse.document (id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal >= 1),
    heading text,
    body text NOT NULL,
    PRIMARY KEY (document_id, ordinal)
);
-- The index column, (re)built with the accent-insensitive configurations (first version: plain french/english).
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'warehouse'
               AND table_name = 'document_section' AND column_name = 'search'
               AND generation_expression NOT LIKE '%unaccent%') THEN
        ALTER TABLE warehouse.document_section DROP COLUMN search;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'warehouse'
                   AND table_name = 'document_section' AND column_name = 'search') THEN
        ALTER TABLE warehouse.document_section ADD COLUMN search tsvector GENERATED ALWAYS AS (
            setweight(to_tsvector('warehouse.french_unaccent'::regconfig, coalesce(heading, '')), 'A')
            || setweight(to_tsvector('warehouse.english_unaccent'::regconfig, coalesce(heading, '')), 'A')
            || setweight(to_tsvector('warehouse.french_unaccent'::regconfig, body), 'B')
            || setweight(to_tsvector('warehouse.english_unaccent'::regconfig, body), 'B')) STORED;
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS document_section_search_idx ON warehouse.document_section USING gin (search);
COMMENT ON TABLE warehouse.document_section IS
    'Section d''un document (ordre d''origine), indexée en texte intégral français et anglais.';

-- Row security like every warehouse table (deploy readiness): a document tied to a dataset version follows
-- that version's access; its sections follow the document.
ALTER TABLE warehouse.document ENABLE ROW LEVEL SECURITY;
ALTER TABLE warehouse.document FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS access_scope ON warehouse.document;
CREATE POLICY access_scope ON warehouse.document FOR ALL USING (
    (SELECT warehouse.is_unrestricted()) OR dataset_version_id IS NULL
    OR dataset_version_id IN (SELECT warehouse.readable_versions()));
ALTER TABLE warehouse.document_section ENABLE ROW LEVEL SECURITY;
ALTER TABLE warehouse.document_section FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS access_scope ON warehouse.document_section;
CREATE POLICY access_scope ON warehouse.document_section FOR ALL USING (
    document_id IN (SELECT id FROM warehouse.document));

CREATE OR REPLACE VIEW catalogue.documents AS
SELECT d.doc_key, d.title, d.kind, d.language, d.author, d.document_date, d.url, d.source_name,
       d.dataset_key, d.dataset_version_id, d.summary,
       (SELECT count(*) FROM warehouse.document_section s WHERE s.document_id = d.id) AS n_sections,
       d.sha256, d.loaded_at
FROM warehouse.document d;
COMMENT ON VIEW catalogue.documents IS
    'Documents écrits (protocoles, méthodes, notes, rapports, publications) : un par doc_key. Lire le texte avec catalogue.document_sections ou read_document; chercher avec search_documents.';

CREATE OR REPLACE VIEW catalogue.document_sections AS
SELECT d.doc_key, d.title, s.ordinal, s.heading, s.body
FROM warehouse.document_section s
JOIN warehouse.document d ON d.id = s.document_id;
COMMENT ON VIEW catalogue.document_sections IS
    'Texte des documents, une ligne par section dans l''ordre d''origine (doc_key, ordinal).';

-- Owner's rights (readers have no access to the warehouse schema); row security still applies to the owner
-- (FORCE) and looks at session_user, the connected account.
CREATE OR REPLACE FUNCTION catalogue.search_documents(p_query text, p_limit integer DEFAULT 8)
RETURNS TABLE (doc_key text, title text, ordinal integer, heading text, excerpt text, rank real)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, warehouse, catalogue
AS $$
    WITH q AS (
        SELECT websearch_to_tsquery('warehouse.french_unaccent', p_query) AS fr,
               websearch_to_tsquery('warehouse.english_unaccent', p_query) AS en
    )
    SELECT d.doc_key, d.title, s.ordinal, s.heading,
           ts_headline('warehouse.french_unaccent', s.body, q.fr || q.en,
                       'MaxFragments=2, MaxWords=45, MinWords=15, StartSel=«, StopSel=»') AS excerpt,
           ts_rank(s.search, q.fr || q.en) AS rank
    FROM warehouse.document_section s
    JOIN warehouse.document d ON d.id = s.document_id
    CROSS JOIN q
    WHERE s.search @@ (q.fr || q.en)
    ORDER BY rank DESC, d.doc_key, s.ordinal
    LIMIT least(greatest(coalesce(p_limit, 8), 1), 25)
$$;

-- Applied after warehouse_access_control.sql: hand the new objects to the data owner like the others
-- (views run with their owner's rights).
ALTER TABLE warehouse.document OWNER TO warehouse_data_owner;
ALTER TABLE warehouse.document_section OWNER TO warehouse_data_owner;
ALTER VIEW catalogue.documents OWNER TO warehouse_data_owner;
ALTER VIEW catalogue.document_sections OWNER TO warehouse_data_owner;
ALTER FUNCTION catalogue.search_documents(text, integer) OWNER TO warehouse_data_owner;
COMMENT ON FUNCTION catalogue.search_documents(text, integer) IS
    'Recherche plein texte dans les documents lisibles : doc_key, section, extrait (excerpt, termes entre « »), score.';

-- Paged reading (like the knowledge-base servers that cap what one call returns): six sections from
-- p_from_section, with the document's total so the agent knows whether to continue.
CREATE OR REPLACE FUNCTION catalogue.read_document(p_doc_key text, p_from_section integer DEFAULT 1)
RETURNS TABLE (doc_key text, title text, section integer, total_sections bigint, heading text, body text)
LANGUAGE sql STABLE
SET search_path = pg_catalog, catalogue
AS $$
    SELECT s.doc_key, s.title, s.ordinal, count(*) OVER (), s.heading, s.body
    FROM catalogue.document_sections s
    WHERE s.doc_key = p_doc_key
    ORDER BY s.ordinal
    OFFSET greatest(coalesce(p_from_section, 1), 1) - 1
    LIMIT 6
$$;
ALTER FUNCTION catalogue.read_document(text, integer) OWNER TO warehouse_data_owner;
COMMENT ON FUNCTION catalogue.read_document(text, integer) IS
    'Six sections d''un document à partir de p_from_section (défaut 1), avec le nombre total de sections.';
