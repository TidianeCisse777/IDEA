-- Documents écrits consultables par les agents : protocoles, notes de méthode, rapports, publications.
--
-- warehouse.document          : un document (clé stable doc_key, titre, type, auteur, date, lien, empreinte).
-- warehouse.document_section  : son texte découpé en sections (titre de section, corps), indexé en texte intégral.
-- catalogue.documents, catalogue.document_sections : lecture par les comptes; un document rattaché à une
--   version de jeu de données n'est visible que si cette version l'est (catalogue.my_datasets).
-- catalogue.search_documents(q) : recherche plein texte (français et anglais), meilleurs extraits d'abord.
--
-- Chargement : scripts/add_warehouse_document.py (un fichier .md ou .txt), et docs/warehouse_documents.json
-- (documents du dépôt, rechargés à chaque déploiement). Le texte est conservé tel quel; aucune
-- interprétation. Additive et relançable.

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
    search tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('french', coalesce(heading, '')), 'A')
        || setweight(to_tsvector('english', coalesce(heading, '')), 'A')
        || setweight(to_tsvector('french', body), 'B')
        || setweight(to_tsvector('english', body), 'B')) STORED,
    PRIMARY KEY (document_id, ordinal)
);
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
FROM warehouse.document d
WHERE d.dataset_version_id IS NULL OR d.dataset_version_id IN (SELECT warehouse.readable_versions());
COMMENT ON VIEW catalogue.documents IS
    'Documents écrits (protocoles, méthodes, notes, rapports, publications) : un par doc_key. Lire le texte avec catalogue.document_sections ou read_document; chercher avec search_documents.';

CREATE OR REPLACE VIEW catalogue.document_sections AS
SELECT d.doc_key, d.title, s.ordinal, s.heading, s.body
FROM warehouse.document_section s
JOIN warehouse.document d ON d.id = s.document_id
WHERE d.dataset_version_id IS NULL OR d.dataset_version_id IN (SELECT warehouse.readable_versions());
COMMENT ON VIEW catalogue.document_sections IS
    'Texte des documents, une ligne par section dans l''ordre d''origine (doc_key, ordinal).';

-- Owner's rights (readers have no access to the warehouse schema), the same dataset filter as the views:
-- readable_versions() looks at session_user, the connected account.
CREATE OR REPLACE FUNCTION catalogue.search_documents(p_query text, p_limit integer DEFAULT 8)
RETURNS TABLE (doc_key text, title text, ordinal integer, heading text, excerpt text, rank real)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, warehouse, catalogue
AS $$
    WITH q AS (
        SELECT websearch_to_tsquery('french', p_query) AS fr, websearch_to_tsquery('english', p_query) AS en
    )
    SELECT d.doc_key, d.title, s.ordinal, s.heading,
           ts_headline('french', s.body, q.fr || q.en,
                       'MaxFragments=2, MaxWords=45, MinWords=15, StartSel=«, StopSel=»') AS excerpt,
           ts_rank(s.search, q.fr || q.en) AS rank
    FROM warehouse.document_section s
    JOIN warehouse.document d ON d.id = s.document_id
    CROSS JOIN q
    WHERE s.search @@ (q.fr || q.en)
      AND (d.dataset_version_id IS NULL OR d.dataset_version_id IN (SELECT warehouse.readable_versions()))
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
