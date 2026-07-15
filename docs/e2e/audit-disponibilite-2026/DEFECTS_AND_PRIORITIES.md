# Défauts observés — Audit de disponibilité 2026

Le pipeline read-only (UC-D) tient bien : pas d'export intempestif, pas de valeur
inventée, trous correctement signalés. Deux défauts mineurs de qualité/outillage.

## P2 — Majeurs

### D-AU1 · Lacune non prouvée d'office
- **Symptôme** : à « a-t-on des données dans le Golfe du Saint-Laurent ? »,
  l'agent répond d'abord « non vérifiable » au lieu de lancer une recherche par
  zone. Il faut le relancer pour obtenir le compte réel (0 sample).
- **Cause** : routage — pour une question de lacune sur une zone nommée, l'agent
  ne déclenche pas systématiquement `get_zone_info` + `find_ecotaxa_samples_in_region`.
- **Priorité** : ajouter au system prompt une règle « pour une question
  d'absence sur une zone nommée, prouver par requête zone, ne pas répondre 'non
  vérifiable' sans avoir cherché ».

## P3 — Mineurs / limites

### D-AU2 · Pas de listing temporel global
- **Symptôme** : « existe-t-il des données hors 2015 et 2024 ? » n'est pas
  directement confirmable — la recherche exige une bbox.
- **Cause** : pas de tool « distribution temporelle du cache » (années couvertes,
  n samples par année) indépendant d'une zone.
- **Priorité** : envisager un résumé temporel du cache (UC-D5-like) pour répondre
  aux audits « quelles périodes couvre-t-on ».
