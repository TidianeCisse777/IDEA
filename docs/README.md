# docs/

Documentation secondaire du projet IDEA. La documentation **canonique** (à lire
en premier) reste à la racine du repo : `README.md`, `CONTEXT.md`,
`ARCHITECTURE.md`, `TOOLS.md`, `SPEC.md`, `PARTAGE.md`, `SEQUENCES.md`,
`CHANGELOG.md`, `CLAUDE.md`, `AGENTS.md`.

Ce dossier contient deux catégories :

## Documentation trackée (versionnée, visible sur GitHub)

| Chemin | Contenu |
|---|---|
| `deploy/DEPLOY.md` | Runbook prod détaillé : hardening, TLS, backups, migration. |
| `features/ENRICHMENT_ECOTAXA_ECOPART.md` | Enrichissement EcoTaxa ↔ EcoPart et métriques d'abondance. |
| `mcp/MCP_CAPABILITIES.md` | Catalogue des demandes utilisateur couvertes par le MCP EcoTaxa. |
| `mcp/MCP_ECOTAXA_ORCHESTRATION.md` | Orchestration des 4 couches (prompt → skill → tool → MCP) et pistes. |
| `mcp/MCP_ECOTAXA_SHARE_GUIDE.md` | Partage, lancement et test du serveur MCP EcoTaxa. |
| `biodiversity_graph_test_plan.md` | Plan de test du graphe biodiversité. |

## Notes internes (locales, non versionnées)

Tout le reste de `docs/` est ignoré par git (voir `.gitignore`) : test maps,
brouillons, cartes d'exploration. Ces fichiers restent sur le poste de travail
et ne sont pas publiés. Pour rendre un nouveau document visible, l'ajouter à une
des sous-catégories trackées ci-dessus (ou whitelister son chemin dans
`.gitignore`).
