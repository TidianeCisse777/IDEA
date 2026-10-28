"""Publier des métadonnées SQL et le contexte MCP; aucune donnée scientifique modifiée."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from warehouse_context import VIEWS, GRAPHICS, column_description

ROOT = Path(__file__).resolve().parents[1]

OVERVIEW = (
    'Warehouse NeoLab : EcoTaxa (objets/annotations), EcoPart (profils/bins/volumes), '
    'FILET (échantillons/analyses/abondances et biomasses source), CTD (mesures environnementales). '
    'Lire ce contexte puis demander la fiche de chaque vue utilisée avec warehouse_context(topic=nom). '
    'Avant de produire un graphique, lire warehouse_context(topic=graphs) pour les bibliothèques, '
    'le style, les règles scientifiques, la provenance et les exports. '
    'Les métadonnées et vues existent même quand les données sont absentes : lire '
    'explore.dataset_versions et mesurer la couverture avant de conclure. '
    'Ne pas inventer données, unités, taxons, liens ou validation scientifique. '
    'Ne pas interpréter biologiquement les résultats. NULL signifie absent/inconnu; zéro et absence '
    'de ligne sont différents. Garder source, versions, politiques d’annotation, stades et '
    'dénominateurs explicites. Ne pas sommer les volumes répétés par taxon ou les '
    'concentrations FILET répétées par bin. Les fichiers sources bruts ne sont pas modifiés. '
    'Accès MCP : SELECT explore uniquement, sans écriture ni DDL, délai 30 s. Le périmètre de chaque '
    'compte (contrats, zones, années) est dans explore.my_access; un résultat vide peut signifier un '
    'accès limité, pas une absence de données. explore.dataset_catalog décrit toutes les versions, même '
    'hors périmètre, et explore.fair_readiness mesure la complétude des métadonnées. '
    'Le navigateur sur 127.0.0.1:8090 et le MCP sont deux accès distincts. '
    'Le filtre spatial du navigateur réduit les paires déjà enregistrées, sans changer leur statut. '
    'Les confirmations restent nécessaires avant téléchargement/calcul lourd. '
    'Répondre en français; expliciter résultat, source, méthode et limites.'
)


def publish(conn):
    """Opération transactionnelle, relançable et sans élargissement des droits bruts."""
    from psycopg import sql
    from psycopg.rows import dict_row
    with conn.transaction():
        with conn.cursor(row_factory=dict_row) as cur:
            columns = cur.execute("""SELECT table_name,column_name,data_type FROM information_schema.columns
                WHERE table_schema='explore' ORDER BY table_name,ordinal_position""").fetchall()
        scientific = [row for row in columns if row['table_name'] in VIEWS]
        actual = {row['table_name'] for row in scientific}
        if actual != set(VIEWS):
            raise ValueError(f'Vues scientifiques absentes : {set(VIEWS)-actual}')
        # Validate coverage before performing any metadata changes.
        descriptions = {(r['table_name'], r['column_name']): column_description(r['table_name'], r['column_name'])
                        for r in scientific}
        for name, item in VIEWS.items():
            comment = f"{item['purpose']} Grain : {item['grain']} Relations : {item['joins']} Limites : {item['caveats']}"
            cur_sql = sql.SQL('COMMENT ON VIEW explore.{} IS {}').format(sql.Identifier(name), sql.Literal(comment))
            conn.execute(cur_sql)
        for (name, column), description in descriptions.items():
            conn.execute(sql.SQL('COMMENT ON COLUMN explore.{}.{} IS {}').format(
                sql.Identifier(name), sql.Identifier(column), sql.Literal(description)))
        rows = [('overview', OVERVIEW, 'Contexte général; aucune ligne scientifique.',
                 'Consulter dataset_versions puis warehouse_dictionary et les fiches des vues.',
                 'Un catalogue documenté ne prouve ni peuplement ni validation scientifique.',
                 'SELECT * FROM explore.dataset_versions LIMIT 20;')]
        rows.append(('graphs', GRAPHICS['purpose'], GRAPHICS['grain'], GRAPHICS['joins'],
                     GRAPHICS['caveats'], GRAPHICS['example']))
        rows += [(name, item['purpose'], item['grain'], item['joins'], item['caveats'], item['example'])
                 for name, item in VIEWS.items()]
        for name, purpose, grain, example in (
            ('dataset_versions', 'Inventaire vivant des versions enregistrées, sans URI de fichier local.',
             'Une version identifiée par source_instance, dataset_key et version_key.',
             'SELECT * FROM explore.dataset_versions LIMIT 20;'),
            ('my_access', 'Périmètre de lecture du compte connecté: source, contrat, zone et années autorisés.',
             'Une ligne par droit actif du compte; une ligne « all data » pour un accès sans filtre.',
             'SELECT * FROM explore.my_access;'),
            ('dataset_catalog', 'Catalogue FAIR des versions de jeux de données: identifiant, licence, accès, couverture, méthode. Lisible même pour les données hors périmètre.',
             'Une ligne par version, y compris retirée.',
             'SELECT dataset_version_id, title, access_level, license, publication_status FROM explore.dataset_catalog LIMIT 20;'),
            ('fair_readiness', 'Complétude FAIR des métadonnées par version (critères manquants listés).',
             'Une ligne par version; mesure le catalogue, pas la validité scientifique.',
             'SELECT dataset_key, version_key, missing_criteria FROM explore.fair_readiness;'),
            ('warehouse_dictionary', 'Colonnes réelles, types SQL, commentaires métier et définition SQL des vues.',
             'Une colonne de vue explore; répète sa définition SQL par colonne.',
             "SELECT * FROM explore.warehouse_dictionary WHERE view_name='uvp_objects';"),
            ('warehouse_context', 'Fiches métier lisibles via MCP.', 'Une fiche par topic.',
             'SELECT topic,purpose FROM explore.warehouse_context;'),
        ):
            rows.append((name, purpose, grain, 'Surface de métadonnées en lecture seule.',
                         'Pas de données scientifiques et pas de garantie de couverture des sources externes.', example))
        literals = sql.SQL(',').join(sql.SQL('({})').format(sql.SQL(',').join(map(sql.Literal, row))) for row in rows)
        conn.execute(sql.SQL('CREATE OR REPLACE VIEW explore.warehouse_context '
                            '(topic,purpose,grain,relations,caveats,sql_example) AS SELECT * FROM (VALUES {}) AS entries').format(literals))
        conn.execute('''CREATE OR REPLACE VIEW explore.dataset_versions AS
            SELECT id AS dataset_version_id,source_instance,dataset_key,version_key,sha256
            FROM warehouse.dataset_version''')
        conn.execute('''CREATE OR REPLACE VIEW explore.warehouse_dictionary AS
            SELECT c.relname::text AS view_name,a.attname::text AS column_name,
                format_type(a.atttypid,a.atttypmod) AS data_type,
                col_description(c.oid,a.attnum) AS column_description,
                obj_description(c.oid,'pg_class') AS view_description,
                pg_get_viewdef(c.oid,true) AS sql_definition
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_attribute a ON a.attrelid=c.oid
            WHERE n.nspname='explore' AND c.relkind='v' AND a.attnum>0 AND NOT a.attisdropped''')
        metadata_columns = {
            'warehouse_context': dict(topic='Nom de fiche; overview pour le contexte global.', purpose='Usage et périmètre métier.',
                grain='Grain des lignes; ne pas supposer leur unicité sans lire la fiche.', relations='Clés et précautions de jointure.',
                caveats='Limites scientifiques et techniques à respecter.', sql_example='Exemple SQL descriptif; ne prouve aucune présence de données.'),
            'dataset_versions': dict(dataset_version_id='Clé technique de warehouse.dataset_version.',
                source_instance='Source enregistrée; derived désigne des résultats calculés.',
                dataset_key='Identifiant du jeu de données dans sa source.', version_key='Version native/enregistrée du jeu.',
                sha256='Empreinte conservée du fichier/manifeste source, pas une certification scientifique.'),
            'warehouse_dictionary': dict(view_name='Nom de vue dans explore.', column_name='Colonne exposée par la vue.',
                data_type='Type SQL effectivement déployé.', column_description='Définition métier de la colonne.',
                view_description='Usage, grain, relations et limites de la vue.', sql_definition='SELECT réel de la vue; révèle la transformation technique, sans autoriser l’accès aux tables brutes.'),
        }
        for name, cols in metadata_columns.items():
            conn.execute(sql.SQL('COMMENT ON VIEW explore.{} IS {}').format(sql.Identifier(name),
                sql.Literal(next(row[1] for row in rows if row[0] == name))))
            for column, description in cols.items():
                conn.execute(sql.SQL('COMMENT ON COLUMN explore.{}.{} IS {}').format(
                    sql.Identifier(name), sql.Identifier(column), sql.Literal(description)))
        for role in ('warehouse_reader', 'warehouse_navigator', 'warehouse_explore_reader'):
            if conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
                conn.execute(sql.SQL('GRANT SELECT ON explore.warehouse_context,explore.warehouse_dictionary,explore.dataset_versions TO {}').format(sql.Identifier(role)))
    return scientific, descriptions


def markdown(columns, descriptions):
    lines = ['# Dictionnaire des vues accessibles via MCP', '',
             'Généré depuis le schéma déployé et le dictionnaire métier versionné. Les données restent à qualifier.', '',
             'Dans DbHub : appeler `warehouse_context` avec `topic="overview"`, puis le nom de vue.',
             '`topic="all"` retourne toutes les fiches. Types et SQL réels : `explore.warehouse_dictionary`.', '',
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
