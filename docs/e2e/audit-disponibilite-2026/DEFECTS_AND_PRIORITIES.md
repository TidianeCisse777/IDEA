# Défauts observés — Audit de disponibilité 2026

Le pipeline read-only (UC-D) tient bien : pas d'export intempestif, pas de valeur
inventée, trous correctement signalés. Deux défauts mineurs de qualité/outillage.

## P2 — Majeurs

### D-AU1 · Lacune non prouvée d'office (CORRIGÉ)
- **Symptôme** : à « a-t-on des données dans le Golfe du Saint-Laurent ? »,
  l'agent répondait d'abord « non vérifiable » au lieu de lancer une recherche.
- **Correctif** : règle de system prompt « Prove absence, do not punt » — pour
  une question d'absence sur une zone ou période, l'agent DOIT interroger
  (`get_zone_info` + `find_ecotaxa_samples_in_region`, ou
  `audit_ecotaxa_availability`) et rapporter le compte réel, zéro compris.

### D-AU3 · Pas d'audit de couverture classé (CORRIGÉ)
- **Symptôme** : l'agent savait répondre au cas par cas mais pas classer
  (« projets/zones avec peu de samples », « samples avec le moins d'objets »).
- **Correctif** : nouveau tool `audit_ecotaxa_availability` (repo
  `audit_ecotaxa_coverage`) — projets classés par rareté de samples, samples les
  plus pauvres en objets, le tout en lecture seule. Tests :
  `tests/test_audit_ecotaxa_availability.py` + `tests/test_ecotaxa_browser_cache_repo.py`.

## P3 — Mineurs / limites

### D-AU2 · Pas de listing temporel global (CORRIGÉ)
- **Symptôme** : « existe-t-il des données hors 2015 et 2024 ? » n'était pas
  directement confirmable.
- **Correctif** : `audit_ecotaxa_availability` fournit la distribution temporelle
  par année (n samples, n projets), indépendante de toute zone.

### D-AU5 · Audit spatial par zone nommée (CORRIGÉ)
- **Symptôme** : impossible de dire quelles zones nommées sont couvertes / où
  sont les trous géographiques ; l'audit restait au niveau projet.
- **Correctif** : nouveau tool `audit_ecotaxa_spatial_coverage` (cœur
  `core.geo.audit_zone_coverage`) — point-in-polygon des samples du cache sur les
  zones du registre, zones couvertes classées + lacunes voisines. Tests :
  `tests/test_geo.py` + `tests/test_audit_ecotaxa_spatial_coverage.py`.

### D-AU4 · Classement validé/prédit par taxon (réseau)
- **Note** : « les projets avec le moins de copépodes validés / le moins d'images
  prédites » n'est pas dans le cache (comptages V/P/D = `taxa_stats`, réseau).
  L'agent route désormais vers `count_ecotaxa_taxa` par projet (règle de system
  prompt). Un tool de classement multi-projets dédié reste une amélioration
  possible (opération réseau, à confirmer CT-AG-06).
