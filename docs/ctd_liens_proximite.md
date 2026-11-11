# Liens CTD par proximité : profils UVP et déploiements FILET

Méthode de `scripts/populate_ctd_proximity.py` et résultats du chargement du 12 novembre 2026. Les mesures CTD
viennent de l'ERDDAP public d'Amundsen Science (https://erddap.amundsenscience.com), copiées telles quelles.

## Sources CTD

| Jeu ERDDAP | Contenu | Années |
|---|---|---|
| `amundsen12713` | CTD de rosette du CCGS Amundsen | 2014–2024 |
| `amundsen11150` … `amundsen11927` (15 jeux) | CTD de rosette par campagne ArcticNet | 2010–2013 |
| `amundsen12716` | CTD montée sur le Bioness (pression, température ITS-90, salinité PSS-78, numéro du filet ouvert) | 2005–2016 |

Non utilisé : `amundsen12717` (CTD montée sur le filet Hydrobios, 2003–2022). Sur l'ERDDAP, sa pression, sa
température et sa salinité sont vides (NaN) pour tout le jeu; seul le numéro de filet est fourni (vérifié le
12 novembre 2026). Un premier chargement l'avait relié à 151 déploiements Hydrobios : liens et profils retirés. Les
déploiements Hydrobios sont reliés à la CTD de rosette.

Variables chargées : PRES, TE90, PSAL, SIGT, OXYM, pH, NTRA, FLOR (rosette); PRES, TE90, PSAL et NET (Bioness, d'après
les métadonnées ERDDAP : Pres en dbar, Temp ITS-90 en °C, Sal PSS-78 en PSU, Net = numéro du filet). Jamais de lien
vers un profil CTD sans pression.

## Règle

- Cibles : profils UVP sans lien CTD par fichier (fichier CTD cité par EcoTaxa); tous les déploiements FILET.
- Pour chaque cible et chaque source applicable (rosette pour tous; CTD du Bioness pour les déploiements Bioness), le
  profil CTD le plus proche au score distance/10 km + écart/6 h, gardé à ≤ 10 km et ≤ 12 h.
- `match_status` : `accepted` si ≤ 5 km et ≤ 6 h, sinon `candidate` (à signaler ou à exclure).
- Distance haversine entre positions; écart entre l'heure de la cible et le début du profil CTD (UTC). Aucun lien par
  nom de station; les liens par fichier (EcoTaxa) ne sont jamais modifiés.
- Vues : `explore.uvp_ctd` et `explore.filet_ctd` (`link_method`, `ctd_source`, `distance_km`, `time_gap_hours`,
  `match_status`). Un déploiement Bioness peut avoir un lien rosette et un lien bioness : filtrer par `ctd_source`.

## Résultats (12 novembre 2026)

| Cible | Source | Statut | Nombre | Distance médiane | Écart médian |
|---|---|---|---|---|---|
| Profils UVP | rosette | accepted | 97 | 0,0 km | 0,1 h |
| Profils UVP | rosette | candidate | 1 | 7,2 km | 2,7 h |
| Déploiements FILET | rosette | accepted | 1 240 | 0,4 km | 1,5 h |
| Déploiements FILET | rosette | candidate | 56 | 1,1 km | 7,1 h |
| Déploiements FILET | CTD du Bioness | accepted | 19 | 0,2 km | 0,1 h |
| Déploiements FILET | CTD du Bioness | candidate | 1 | 8,3 km | 3,0 h |

- Profils UVP avec CTD : 594 sur 686 (497 par fichier EcoTaxa, 97 + 1 par proximité). Sans CTD : 61 profils du camp de
  glace GreenEdge 2015–2016 (UVP sn008, pas de CTD du navire), 30 du lac Champlain et 1 profil de 2022 sans campagne.
- Déploiements FILET avec CTD : 1 297 sur 1 588. Sans CTD à ≤ 10 km et ≤ 12 h : 291, dont 162 en 2025 (pas encore
  dans l'ERDDAP) et 44 en 2017.
- 826 profils CTD téléchargés et gardés (1 282 au total, 7,7 millions de mesures). Aucun profil sans mesure, aucun lien
  vers un profil sans pression.

## Valeurs source à signaler

- pH : 11 418 mesures, seulement pour 40 profils des campagnes 2011 (jeux 11921, 11923, 11924).
- Nitrate (NTRA) négatif : 730 mesures de 13 campagnes 2010 (jeux 11150, 11151, 11153, 11155, 11156, 11943), jusqu'à
  −16,9; physiquement impossible (capteur). Fluorescence légèrement négative (≥ −0,04). Valeurs gardées telles
  quelles : les exclure ou les signaler, ne jamais les corriger.
