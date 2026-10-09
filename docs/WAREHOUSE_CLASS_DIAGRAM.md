# Diagramme de classes de la base warehouse NeoLab

Ce document accompagne le PDF généré dans
`output/pdf/warehouse_database_class_diagram.pdf`. La source modifiable du
diagramme est [warehouse_class_diagram.mmd](warehouse_class_diagram.mmd).

## Périmètre

- 26 tables du schéma `warehouse` ;
- clés primaires, clés étrangères et principales colonnes métier ;
- tables de liaison EcoTaxa, EcoPart, UVP, CTD et FILET ;
- relations logiques sans contrainte SQL signalées en pointillé ;
- vues de lecture du schéma `explore` inventoriées dans le PDF.

Le diagramme est consolidé à partir de :

- [warehouse_schema_proposal.sql](warehouse_schema_proposal.sql) ;
- [warehouse_ecopart_migration.sql](warehouse_ecopart_migration.sql) ;
- [warehouse_filet_zone_migration.sql](warehouse_filet_zone_migration.sql).
- [warehouse_metadata_migration.sql](warehouse_metadata_migration.sql).

Il ne constitue pas une introspection de l'instance PostgreSQL : le service
warehouse n'était pas actif lors de la génération du 7 octobre 2026. Les vues
`explore` sont une surface de lecture et ne sont pas traitées comme des classes
persistées.

## Régénération du PDF

```bash
uv run --with reportlab scripts/generate_warehouse_class_diagram.py
```

Le PDF est produit en format A3 paysage afin que les noms de tables et les
relations restent lisibles à l'écran ou à l'impression.
