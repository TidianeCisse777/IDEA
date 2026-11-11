"""Publier des métadonnées SQL et le contexte MCP; aucune donnée scientifique modifiée."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from warehouse_context import VIEWS, OPTIONAL_VIEWS, GRAPHICS, column_description

ROOT = Path(__file__).resolve().parents[1]

OVERVIEW = (
    'Warehouse NeoLab : EcoTaxa (objets/annotations), EcoPart (profils/bins/volumes), '
    'FILET (échantillons/analyses/abondances et biomasses source), CTD (mesures environnementales). '
    'Lire ce contexte puis demander la fiche de chaque vue utilisée avec warehouse_context(topic=nom). '
    'Avant de produire un graphique, lire warehouse_context(topic=graphs) pour les bibliothèques, '
    'le style, les règles scientifiques, la provenance et les exports. '
    'Les métadonnées et vues existent même quand les données sont absentes : lire '
    'catalogue.dataset_versions et mesurer la couverture avant de conclure. '
    'Ne pas inventer données, unités, taxons, liens ou validation scientifique. Toute réponse sur les données vient d’une requête execute_sql sur ce warehouse : ne jamais répondre de mémoire ni avec des valeurs générales (climatologie, littérature) à la place des mesures; si une requête échoue ou qu’un outil est refusé, le dire et réessayer avec execute_sql plutôt que d’estimer. '
    'Comparer FILET et UVP : explore.filet_uvp_compare(...) et explore.filet_uvp_pairs(...), décrits dans la fiche filet_uvp_abundance et le document filet-uvp-comparaison. '
    'Les documents écrits (protocoles, méthodes, notes) sont dans catalogue.documents : les chercher avec '
    'search_documents pour une question de méthode, de protocole ou de provenance, et citer doc_key et section. '
    'Ne pas interpréter biologiquement les résultats. NULL signifie absent/inconnu; zéro et absence '
    'de ligne sont différents. Garder source, versions, politiques d’annotation, stades et '
    'dénominateurs explicites. Ne pas sommer les volumes répétés par taxon ou les '
    'concentrations FILET répétées par bin. Les fichiers sources bruts ne sont pas modifiés. '
    'Accès MCP : SELECT sur deux schémas seulement, explore (les données) et catalogue (droits, catalogue des jeux de données, dictionnaire, ces fiches), sans écriture ni DDL, délai 30 s. Pour une question sur les projets ou les objets EcoTaxa en général, partir de explore.ecotaxa_projects (tous les projets), pas des seules vues uvp_*; dire dans la réponse le périmètre couvert. Pour un taxon (le chercher, le compter, savoir où il est) partir de explore.ecotaxa_sample_taxa, rapide, et non de ecotaxa_objects (15 M lignes, plus de 30 s pour un filtre sur le nom); pour un groupe (« les copépodes »), filtrer la lignée EcoTaxa (\'Copepoda\' = ANY(taxon_lineage), liste dans explore.ecotaxa_taxa) au lieu d\'énumérer des genres de mémoire, et dire quelles catégories non entières ou incertaines (part, cut, dead, eggs, like...) sont gardées. Une demande sans grandeur précise (« le profil vertical », « l\'abondance », « le projet ») se lit de plusieurs façons : abondance UVP d\'organismes, concentration de particules, ou variable CTD (température, salinité...); dire la grandeur et le projet retenus et pourquoi, ou demander. Un total d\'abondance « tous objets » contient surtout des détritus : ne compter comme individus que object_class = \'organism\' (explore.ecotaxa_taxa). Explorer avant de générer : n\'écrire une requête qu\'avec des noms de vues et de colonnes lus dans column_list (cette fiche les donne pour toutes les vues, chaque fiche de vue avec leurs types) ou dans catalogue.warehouse_dictionary; ne jamais deviner un nom (title pour ecotaxa_project_title, explore.zones...) ni sonder une table par essai-erreur. Une erreur SQL renvoyée avec un champ hint dit quoi faire ensuite. Le périmètre de chaque '
    'compte (contrats, zones, années) est dans catalogue.my_access; catalogue.my_datasets dit pour chaque '
    'version si l\'accès est complet, partiel ou nul et pourquoi. Un résultat vide peut signifier un '
    'accès limité, pas une absence de données : consulter my_datasets avant de conclure. Les vues UVP '
    'joignent EcoTaxa et EcoPart et exigent un droit sur les deux. Avec un accès partiel, une colonne '
    'issue d\'une jointure externe peut être NULL parce que la ligne liée est hors périmètre. '
    'catalogue.dataset_catalog décrit toutes les versions, même hors périmètre, et catalogue.fair_readiness '
    'mesure la complétude des métadonnées. '
    'Priorité absolue : récupérer l\'intégralité des données nécessaires avant toute analyse. Chaque '
    'réponse SQL est plafonnée (DbHub : 1 000 lignes; la réponse brute porte un champ truncated). '
    'Compter d\'abord avec count(*), puis agréger côté SQL (SUM/AVG/GROUP BY) ou paginer par tri stable '
    '(ORDER BY clé + LIMIT/OFFSET) jusqu\'à couvrir le total attendu. Pour une extraction brute qui '
    'dépasse la limite, vérifier la complétude par un hash ou un compte recalculé côté base après coup, '
    'pas seulement en confiance. Ne jamais présenter une page partielle comme le résultat complet. '
    'Une fois les données entièrement récupérées, aucune restriction supplémentaire : les croiser, les '
    'agréger, les visualiser et les calculer librement avec les outils disponibles (pandas, Matplotlib, '
    'Cartopy, etc.) sans demander de confirmation additionnelle pour l\'analyse elle-même. '
    'Le navigateur sur 127.0.0.1:8090 et le MCP sont deux accès distincts. '
    'Le filtre spatial du navigateur réduit les paires déjà enregistrées, sans changer leur statut. '
    'Les confirmations restent nécessaires avant téléchargement/calcul lourd. '
    'Répondre en français; expliciter résultat, source, méthode et limites. '
    'Raisonnement : toute réponse qui donne des chiffres ou une figure commence par une courte section '
    '« Raisonnement » (quelques puces) : comment la question a été comprise, les choix retenus (projet, '
    'grandeur, taxons, profondeur, années, politique d\'annotation, catégories exclues) avec leur raison, '
    'et les autres lectures possibles écartées; puis le résultat. Chaque chiffre de la réponse vient d\'une '
    'requête exécutée dans cette conversation; une valeur reprise d\'une fiche est signalée comme telle et '
    'recalculée si une requête le permet. '
    'Transparence pour le chercheur : toute réponse qui donne des chiffres se termine par une section '
    '« Requêtes exécutées » listant, pour chaque requête SQL qui a produit ces chiffres, son texte exact '
    'tel qu\'envoyé, le nombre de lignes renvoyées et les valeurs utilisées (un extrait si le résultat est '
    'long). Ne montrer que des requêtes réellement exécutées et leurs résultats réels, sans les reformuler; '
    'résumer en une ligne les requêtes de découverte (fiches, droits, colonnes).'
)


def publish(conn):
    """Opération transactionnelle, relançable et sans élargissement des droits bruts."""
    from psycopg import sql
    from psycopg.rows import dict_row
    with conn.transaction():
        with conn.cursor(row_factory=dict_row) as cur:
            columns = cur.execute("""SELECT table_name,column_name,data_type FROM information_schema.columns
                WHERE table_schema='explore' ORDER BY table_name,ordinal_position""").fetchall()
            readable = cur.execute("""SELECT table_schema,table_name,column_name,data_type FROM information_schema.columns
                WHERE table_schema IN ('explore','catalogue') ORDER BY table_schema <> 'explore',table_name,ordinal_position""").fetchall()
        # Explore first, then write SQL: every sheet carries the real columns of its view, read from the
        # deployed schema, and the overview the map of all readable views (agents guessed column names in
        # 47 queries of 142 battery cases, 21 of them their very first query, right after the overview).
        by_view = {}
        for row in readable:
            by_view.setdefault((row['table_schema'], row['table_name']), []).append(row)
        own_columns = {name: ', '.join(f"{r['column_name']} ({r['data_type']})" for r in cols)
                       for (_, name), cols in by_view.items()}
        schema_map = 'Colonnes réelles de chaque vue (seuls noms valides) :\n' + '\n'.join(
            f"{schema}.{name} : {', '.join(r['column_name'] for r in cols)}" for (schema, name), cols in by_view.items())
        scientific = [row for row in columns if row['table_name'] in VIEWS]
        actual = {row['table_name'] for row in scientific}
        missing = (set(VIEWS) - OPTIONAL_VIEWS) - actual
        if missing:
            raise ValueError(f'Vues scientifiques absentes : {missing}')
        # Validate coverage before performing any metadata changes.
        descriptions = {(r['table_name'], r['column_name']): column_description(r['table_name'], r['column_name'])
                        for r in scientific}
        for name, item in VIEWS.items():
            if name not in actual:
                continue  # optional view this deployment could not create (e.g. no PostGIS)
            comment = f"{item['purpose']} Grain : {item['grain']} Relations : {item['joins']} Limites : {item['caveats']}"
            cur_sql = sql.SQL('COMMENT ON VIEW explore.{} IS {}').format(sql.Identifier(name), sql.Literal(comment))
            conn.execute(cur_sql)
        for (name, column), description in descriptions.items():
            conn.execute(sql.SQL('COMMENT ON COLUMN explore.{}.{} IS {}').format(
                sql.Identifier(name), sql.Identifier(column), sql.Literal(description)))
        rows = [('overview', OVERVIEW, 'Contexte général; aucune ligne scientifique.',
                 'Consulter dataset_versions puis warehouse_dictionary et les fiches des vues.',
                 'Un catalogue documenté ne prouve ni peuplement ni validation scientifique.',
                 'SELECT * FROM catalogue.dataset_versions LIMIT 20;')]
        rows.append(('graphs', GRAPHICS['purpose'], GRAPHICS['grain'], GRAPHICS['joins'],
                     GRAPHICS['caveats'], GRAPHICS['example']))
        rows += [(name, item['purpose'], item['grain'], item['joins'], item['caveats'], item['example'])
                 for name, item in VIEWS.items() if name in actual]
        for name, purpose, grain, example in (
            ('dataset_versions', 'Inventaire vivant des versions enregistrées, sans URI de fichier local.',
             'Une version identifiée par source_instance, dataset_key et version_key.',
             'SELECT * FROM catalogue.dataset_versions LIMIT 20;'),
            ('my_access', 'Périmètre de lecture du compte connecté: source, contrat, zone et années autorisés.',
             'Une ligne par droit actif du compte; une ligne « all data » pour un accès sans filtre.',
             'SELECT * FROM catalogue.my_access;'),
            ('my_datasets', 'Accès du compte connecté à chaque version de jeu de données: complet, partiel ou aucun, la raison, et une note si une source associée manque (EcoTaxa/EcoPart pour les vues UVP).',
             'Une ligne par version; aucune donnée scientifique et aucun comptage de lignes masquées.',
             "SELECT dataset_key, my_scope, scope_detail, note FROM catalogue.my_datasets ORDER BY my_scope;"),
            ('dataset_catalog', 'Catalogue FAIR des versions de jeux de données: identifiant, licence, accès, couverture, méthode. Lisible même pour les données hors périmètre.',
             'Une ligne par version, y compris retirée.',
             'SELECT dataset_version_id, title, access_level, license, publication_status FROM catalogue.dataset_catalog LIMIT 20;'),
            ('fair_readiness', 'Complétude FAIR des métadonnées par version (critères manquants listés).',
             'Une ligne par version; mesure le catalogue, pas la validité scientifique.',
             'SELECT dataset_key, version_key, missing_criteria FROM catalogue.fair_readiness;'),
            ('warehouse_dictionary', 'Colonnes réelles, types SQL, commentaires métier et définition SQL des vues.',
             'Une colonne de vue des schémas explore et catalogue; répète sa définition SQL par colonne.',
             "SELECT * FROM catalogue.warehouse_dictionary WHERE view_name='uvp_objects';"),
            ('documents', 'Documents écrits (protocoles, notes de méthode, rapports, publications) : titre, type, auteur, date, lien, jeu de données concerné. Chercher avec search_documents, lire avec read_document; citer doc_key et section.',
             'Un document par doc_key; texte d\'origine non interprété.',
             'SELECT doc_key, kind, title, document_date, n_sections FROM catalogue.documents ORDER BY doc_key;'),
            ('document_sections', 'Texte des documents écrits, une section par ligne dans l\'ordre d\'origine.',
             'Une ligne par (doc_key, ordinal).',
             "SELECT ordinal, heading, body FROM catalogue.document_sections WHERE doc_key='filet-export-review' ORDER BY ordinal;"),
            ('warehouse_context', 'Fiches métier lisibles via MCP.', 'Une fiche par topic.',
             'SELECT topic,purpose FROM catalogue.warehouse_context;'),
        ):
            rows.append((name, purpose, grain, 'Surface de métadonnées en lecture seule.',
                         'Pas de données scientifiques et pas de garantie de couverture des sources externes.', example))
        rows = [(*row, schema_map if row[0] == 'overview' else own_columns.get(row[0], '')) for row in rows]
        literals = sql.SQL(',').join(sql.SQL('({})').format(sql.SQL(',').join(map(sql.Literal, row))) for row in rows)
        conn.execute(sql.SQL('CREATE OR REPLACE VIEW catalogue.warehouse_context '
                            '(topic,purpose,grain,relations,caveats,sql_example,column_list) AS SELECT * FROM (VALUES {}) AS entries').format(literals))
        conn.execute('''CREATE OR REPLACE VIEW catalogue.dataset_versions AS
            SELECT id AS dataset_version_id,source_instance,dataset_key,version_key,sha256
            FROM warehouse.dataset_version''')
        conn.execute('''CREATE OR REPLACE VIEW catalogue.warehouse_dictionary AS
            SELECT c.relname::text AS view_name,a.attname::text AS column_name,
                format_type(a.atttypid,a.atttypmod) AS data_type,
                col_description(c.oid,a.attnum) AS column_description,
                obj_description(c.oid,'pg_class') AS view_description,
                pg_get_viewdef(c.oid,true) AS sql_definition,
                n.nspname::text AS schema_name
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_attribute a ON a.attrelid=c.oid
            WHERE n.nspname IN ('explore','catalogue') AND c.relkind='v' AND a.attnum>0 AND NOT a.attisdropped''')
        metadata_columns = {
            'warehouse_context': dict(topic='Nom de fiche; overview pour le contexte global.', purpose='Usage et périmètre métier.',
                grain='Grain des lignes; ne pas supposer leur unicité sans lire la fiche.', relations='Clés et précautions de jointure.',
                caveats='Limites scientifiques et techniques à respecter.', sql_example='Exemple SQL descriptif; ne prouve aucune présence de données.',
                column_list='Colonnes réelles de la vue (nom et type), lues dans le schéma déployé; pour overview, toutes les vues lisibles et leurs colonnes.'),
            'dataset_versions': dict(dataset_version_id='Clé technique de warehouse.dataset_version.',
                source_instance='Source enregistrée; derived désigne des résultats calculés.',
                dataset_key='Identifiant du jeu de données dans sa source.', version_key='Version native/enregistrée du jeu.',
                sha256='Empreinte conservée du fichier/manifeste source, pas une certification scientifique.'),
            'warehouse_dictionary': dict(view_name='Nom de la vue (dans le schéma indiqué par schema_name).', column_name='Colonne exposée par la vue.',
                data_type='Type SQL effectivement déployé.', column_description='Définition métier de la colonne.',
                view_description='Usage, grain, relations et limites de la vue.', sql_definition='SELECT réel de la vue; révèle la transformation technique, sans autoriser l’accès aux tables brutes.',
                schema_name='explore pour les données, catalogue pour les droits, le catalogue et ce dictionnaire.'),
        }
        for name, cols in metadata_columns.items():
            conn.execute(sql.SQL('COMMENT ON VIEW catalogue.{} IS {}').format(sql.Identifier(name),
                sql.Literal(next(row[1] for row in rows if row[0] == name))))
            for column, description in cols.items():
                conn.execute(sql.SQL('COMMENT ON COLUMN catalogue.{}.{} IS {}').format(
                    sql.Identifier(name), sql.Identifier(column), sql.Literal(description)))
        # Service views a person opens first (rights, catalog, release): their columns are
        # described too, so a SQL client (DBeaver, pgAdmin) shows what each one means.
        service_columns = {
            'my_access': dict(grantee='Compte concerné par ce droit.', source_instance='Source autorisée (ecotaxa, ecopart, filet, amundsen_ctd…); vide = toutes.',
                contract='Contrat de données autorisé (C1, C2…); vide = tous.', zone_key='Zone maritime autorisée; vide = toutes.',
                year_min='Première année autorisée; vide = sans limite.', year_max='Dernière année autorisée; vide = sans limite.',
                note='Précision sur le droit (ex. « member of warehouse_all_access » pour un accès complet).', granted_at='Date d’attribution du droit.'),
            'my_datasets': dict(dataset_version_id='Clé technique de la version (dataset_versions, dataset_catalog).', source_instance='Source de la version.',
                dataset_key='Identifiant du jeu dans sa source (ex. numéro de projet EcoTaxa ou EcoPart).', version_key='Version du jeu.',
                title='Titre lisible du jeu de données (nom du projet source quand il est connu).', access_contract='Contrat de données de la version; vide = non attribué.',
                my_scope='Mon accès à cette version : complet, partiel ou aucun.', scope_detail='Ce qui limite l’accès (zone, années…).',
                note='Avertissement éventuel, ex. une source associée manquante pour les vues UVP.'),
            'dataset_catalog': dict(dataset_version_id='Clé technique de la version.', source_instance='Source de la version.',
                dataset_key='Identifiant du jeu dans sa source.', version_key='Version du jeu.', sha256='Empreinte du fichier ou manifeste source.',
                title='Titre lisible du jeu de données.', description='Description du jeu; « à compléter » tant qu’elle n’a pas été rédigée.',
                creators_json='Auteurs (liste JSON).', keywords_json='Mots-clés (liste JSON).', persistent_identifier='Identifiant pérenne (DOI…) s’il existe.',
                license='Licence.', license_uri='Adresse de la licence.', access_level='Niveau d’accès déclaré (internal, open…).',
                access_conditions='Conditions d’accès.', publication_status='draft, validated, published ou retired.',
                temporal_start='Début de la couverture temporelle déclarée.', temporal_end='Fin de la couverture temporelle déclarée.',
                spatial_extent_json='Couverture spatiale déclarée (JSON).', taxonomic_scope='Couverture taxonomique déclarée.',
                methodology='Méthode d’acquisition ou de calcul déclarée.', software_version='Version du logiciel ou du chargeur.',
                schema_version='Version du schéma warehouse.', metadata_standard='Standard de métadonnées déclaré.',
                related_identifiers_json='Identifiants liés (JSON).', file_count='Nombre de fichiers source enregistrés.',
                access_contract='Contrat de données (C1, C2…) qui décide qui peut lire la version.'),
            'fair_readiness': dict(dataset_version_id='Clé technique de la version.', source_instance='Source.', dataset_key='Identifiant du jeu.',
                version_key='Version.', f1_persistent_identifier='F1 : identifiant pérenne présent.', f2_rich_metadata='F2 : titre, description et auteurs renseignés.',
                f4_searchable='F4 : mots-clés présents.', a1_access_declared='A1 : niveau et conditions d’accès déclarés.',
                i1_standard_declared='I1 : standard de métadonnées déclaré.', i3_related_references='I3 : références liées présentes.',
                r1_license='R1 : licence présente.', r2_provenance='R2 : méthode, logiciel et fichiers source présents.',
                r3_validated='R3 : une validation enregistrée a réussi.', missing_criteria='Critères FAIR manquants.',
                fair_ready='Vrai quand tous les critères sont remplis (métadonnées, pas validité scientifique).'),
            'fair_column_coverage': dict(table_name='Table brute du warehouse.', column_count='Nombre de colonnes.',
                documented_count='Colonnes décrites dans column_metadata.', with_unit_count='Colonnes avec unité.',
                with_standard_uri_count='Colonnes reliées à un terme standard.'),
            'warehouse_release': dict(release='Version du warehouse déployée.', method='Mode de déploiement.',
                applied_at='Date du déploiement.', migration_count='Nombre de migrations appliquées.',
                migrations='Migrations appliquées et leur empreinte SHA-256.'),
            'access_audit': dict(problem='Problème de sécurité détecté (vide = aucun).', object_name='Objet concerné.'),
        }
        existing = {r[0] for r in conn.execute("SELECT table_name FROM information_schema.views WHERE table_schema='catalogue'").fetchall()}
        for name, cols in service_columns.items():
            if name not in existing:
                continue
            present = {r[0] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='catalogue' AND table_name=%s", (name,)).fetchall()}
            for column, description in cols.items():
                if column in present:
                    conn.execute(sql.SQL('COMMENT ON COLUMN catalogue.{}.{} IS {}').format(
                        sql.Identifier(name), sql.Identifier(column), sql.Literal(description)))
        for role in ('warehouse_reader', 'warehouse_navigator', 'warehouse_explore_reader'):
            if conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
                conn.execute(sql.SQL('GRANT SELECT ON catalogue.warehouse_context,catalogue.warehouse_dictionary,catalogue.dataset_versions TO {}').format(sql.Identifier(role)))
    return scientific, descriptions


def markdown(columns, descriptions):
    lines = ['# Dictionnaire des vues accessibles via MCP', '',
             'Généré depuis le schéma déployé et le dictionnaire métier versionné. Les données restent à qualifier.', '',
             'Dans DbHub : appeler `warehouse_context` avec `topic="overview"`, puis le nom de vue.',
             '`topic="all"` retourne toutes les fiches. Types et SQL réels : `catalogue.warehouse_dictionary`.', '',
             OVERVIEW, '', '## Règles de graphiques — topic=graphs', '']
    for key, label in (('purpose', 'Bibliothèques'), ('grain', 'Données et calcul'),
                       ('joins', 'Style'), ('caveats', 'Statut et livraison')):
        lines += [f"**{label} :** {GRAPHICS[key]}", '']
    for name, item in VIEWS.items():
        lines += [f'## explore.{name}', '', item['purpose'], '', f"**Grain :** {item['grain']}", '',
                  f"**Relations :** {item['joins']}", '', f"**Limites :** {item['caveats']}", '',
                  '| Colonne | Type SQL | Définition |', '|---|---|---|']
        for row in columns:
            if row['table_name'] == name:
                description = descriptions[(name, row['column_name'])].replace('|', '\\|')
                lines.append(f"| {row['column_name']} | {row['data_type']} | {description} |")
        lines += ['', '```sql', item['example'], '```', '']
    return '\n'.join(lines)


def connect(psycopg):
    """Variables du déploiement si présentes, sinon l'installation Windows portable."""
    import json
    import os
    if os.environ.get('WAREHOUSE_POSTGRES_PASSWORD'):
        return psycopg.connect(host=os.environ.get('WAREHOUSE_POSTGRES_HOST', '127.0.0.1'),
                               port=int(os.environ.get('WAREHOUSE_POSTGRES_PORT', '55432')),
                               dbname=os.environ.get('WAREHOUSE_POSTGRES_DB', 'neolab_warehouse'),
                               user=os.environ.get('WAREHOUSE_POSTGRES_USER', 'neolab'),
                               password=os.environ['WAREHOUSE_POSTGRES_PASSWORD'])
    passwords = json.loads((ROOT / 'data/local_warehouse/credentials.json').read_text(encoding='utf-8'))
    return psycopg.connect(host='127.0.0.1', port=55432, dbname='neolab_warehouse',
                           user='neolab', password=passwords['owner'])


if __name__ == '__main__':
    import psycopg
    with connect(psycopg) as conn:
        columns, descriptions = publish(conn)
    if '--no-doc' not in sys.argv:
        (ROOT / 'docs/WAREHOUSE_MCP_DICTIONARY.md').write_text(markdown(columns, descriptions), encoding='utf-8')
    print(f'Contexte publié : {len(VIEWS)} vues et {len(descriptions)} colonnes scientifiques documentées.')
