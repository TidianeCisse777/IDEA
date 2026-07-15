# Défauts observés — Bio-ORACLE prospectif 2026

Défauts relevés pendant le scénario prospectif (densité copépode × réchauffement
projeté). Tous **corrigés** au cours du scénario ; ce fichier trace le diagnostic
et la résolution.

## P1 — Bloquants (corrigés)

### D-BO1 · Calcul d'abondance copépode faux par l'agent (CORRIGÉ)
- **Symptôme** : l'agent calculait la « densité copépode » par une **moyenne de
  `Total abundance` sur toutes les lignes brutes** (199 taxons, dont ~50 % non
  copépodes, tous stades/profondeurs), présentait des **comptages de lignes comme
  des stations**, et n'émettait que 4 grappes. Écart : Hudson Complex 162,78 (faux)
  vs 3 968 ind/m³ (correct), 24×.
- **Cause racine** : garde-fou **advisory** (skill + prompt) sans **contrat
  déterministe**, et pas d'auto-détection du format NeoLab au `load_file`. Le LLM
  pouvait donc hand-roll un `run_pandas` sans aucune contrainte.
- **Correctif** (4 verrous) :
  1. contrat `core.neolabs_abundance.neolabs_copepod_density` (filtre
     `CLASS == 'Copepoda'`, somme par `SAMPLE_ID`, moyenne par station) ;
  2. auto-détection NeoLab dans `load_file` → hint vers le contrat ;
  3. règle de routage system prompt interdisant le hand-roll ;
  4. **garde-fou `run_pandas`** qui bloque une agrégation copépode faite à la main
     et renvoie vers le contrat (enforcement réel).
- **Validé e2e sur l'agent** : médiane **395,8** ind/m³ via le contrat (vs 590,2
  au hand-roll). Suite complète : 925 verts.

## P2 — Majeurs (corrigés)

### D-BO2 · Enrichissement Bio-ORACLE lent sur points dispersés (CORRIGÉ)
- **Symptôme** : enrichir 125 stations dispersées touchait ~45 tuiles 5° × 2
  scénarios ≈ 90 requêtes HTTP → plusieurs minutes.
- **Correctif** : `enrich_with_bio_oracle` bascule en **mode région** (1 tuile
  bornante à stride grossier) au-delà de 6 tuiles fines → **5,9 s / 2 requêtes**,
  125/125 appariées. Précision fine conservée pour les jeux groupés.

### D-BO3 · Deltas différents au même endroit (artefact de coloriage) (CORRIGÉ)
- **Symptôme** : sur la carte, des stations voisines avaient des couleurs
  différentes — coloriage **par zone**, avec sauts artificiels aux frontières.
- **Correctif** : coloriage **par station** (delta Bio-ORACLE propre à chaque
  point) → champ lisse, lisible d'un coup d'œil.

## P3 — Mineurs

### D-BO4 · Alignement Bio-ORACLE via session store périmé
- **Symptôme** : première version du script récupérait des dataframes périmés du
  session store → deltas négatifs impossibles.
- **Correctif** : thread frais par appel / lookup local sur tuile région.

### D-BO5 · Traçabilité `dataset_id`/`time` en mode région
- En mode région les colonnes `dataset_id`/`time` reviennent vides (la valeur est
  correcte). Amélioration possible ; non bloquant.

### D-BO6 · Centroïdes de zone sur la terre
- Quelques centroïdes de zones (moyenne des coordonnées de stations) tombent sur
  la côte. Résolu en traçant les stations réelles plutôt que les centroïdes.
