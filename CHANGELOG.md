# Changelog — IDEA / NeoLab Copepod Agent

Toutes les releases significatives. Versions taggées sur GitHub :
`https://github.com/TidianeCisse777/IDEA/releases`.

Image Docker correspondante : `ghcr.io/tidianecisse777/copepod-agent:<tag>`
(workflow `.github/workflows/docker-build.yml` rebuild sur push).

Format inspiré de [Keep a Changelog](https://keepachangelog.com/).
Tracking démarré à partir de v3.3.0 — historique antérieur dans
`git log` et dans les tags.

---

## [v3.3.0] — 2026-06-22 — UVP m5/m6 routing canonique, conversion m³↔L, skill loading par intent

### Pourquoi cette release

Avant v3.3.0, sur les fichiers UVP EcoTaxa intermédiaires, l'agent
improvisait une formule de densité copépodes (`sum(objets) / sum(volumes)`
sur tout le profil) au lieu d'appliquer m5 (Vilgrain & Bourgouin 2026)
= `(densité_moyenne_surface_0_50 + densité_moyenne_fond_max_50) / 2`. Le
top-N des stations sortait faux. Cette release règle le routing,
documente la méthode canonique, et ajoute le support de la conversion
m³ ↔ L pour les comparaisons entre fichiers UVP (ind/L) et fichiers
filets NeoLabs (ind/m³).

### Added

- **`scripts/uvp_metrics_pipeline.py`** — port Python du pipeline de
  préparation de données du script R de Vilgrain & Bourgouin 2026.
  Lit les exports bruts EcoTaxa + EcoPart, produit trois tables
  intermédiaires (parquet + csv) `taxa_db`, `part_db`, `taxa_morpho_db`
  sur lesquelles m1–m6 peuvent être calculées sans re-dériver
  `sampled_volume` / `depth_bin`. Validé : reproduit exactement les
  valeurs du livrable R sur Hawke Channel 2024 (30 samples, erreur
  float negligible).

- **`agents/skills/uvp_ecotaxa.md`** — section *"🛑 READ THIS FIRST"*
  en tête avec :
  - templates m5 et m6 inline prêts à copier (raw + intermédiaire)
  - code `FORBIDDEN` montrant l'improvisation typique du LLM
    (`sum/sum`) et le piège m6 (`is_long` post-groupby qui contamine
    les moyennes avec des bins à 0)
  - règle de routing par défaut : « abondance / densité copépodes /
    top stations / profils verticaux » sans précision → m5 canonique
  - override explicite : si l'utilisateur demande la moyenne globale,
    l'agent suit et le mentionne
  - guard *"Not for net samples"* qui redirige vers
    `neolabs_abundance_analysis` quand le fichier est un échantillon
    filet (`GEAR`, `TOW_TYPE`, `MIN_SAMPLE_DEPTH`…)
  - **answer template** : oblige l'agent à écrire une ligne
    `Méthode : …` avant le tableau de résultats

- **`agents/skills/neolabs_abundance_analysis.md`** — section *"Volumes
  filtrés et conversion d'unités"* avec :
  - choix `DEPTH_CALC_VOL` vs `FLOWMETER_CALC_VOL`, formules de
    recompute si absents (`π · r² · h · E` pour la pêche verticale,
    `constante × Δtours` pour le flowmeter)
  - table de conversion m³ ↔ L (× 1000 / ÷ 1000) pour pouvoir
    comparer un dataset filet (ind/m³) avec un dataset UVP (ind/L)
  - exemple de code Python pour aligner les unités avant join/plot

- **Tests** dans `tests/test_data_tools.py` pour `_uvp_skill_hint` sur
  la signature `taxa_db.csv` (vérifie maintenant la non-activation,
  voir Changed).

### Changed

- **`agents/copepod_system_prompt.py`** — nouvelle règle *"UVP
  abundance / density intent"* qui force `load_skill("uvp_ecotaxa")`
  avant tout `run_pandas` quand l'intent utilisateur est
  abondance / densité / m5 / m6 / ranking / profils verticaux sur un
  df qui ressemble à un fichier UVP. Symétrique de la règle existante
  pour `neolabs_abundance_analysis`. Le routing se fait désormais à
  l'**intent** et plus seulement à l'évènement `load_file`.

- **`tools/data_tools.py:_uvp_skill_hint`** — resserré : ne déclenche
  plus que sur la signature UVP raw spécifique (`object_major` ou
  `fre_major` + `sample_id`), c'est-à-dire les fichiers ayant des
  colonnes morphométriques en pixels. La signature large
  `{sample_id, depth_bin, sampled_volume, category}` est retirée
  parce qu'elle matchait potentiellement un export filet ZooScan en
  minuscules. Le routing pour ces fichiers passe désormais par la
  règle d'intent du system prompt.

### Fixed

- **m5 (densité moyenne copépodes)** : agent calcule maintenant la
  vraie formule canonique `(surface 0-50 + fond max-50) / 2` au lieu
  de `sum(objets) / sum(volumes)`. Validé via curl direct, top-5
  identique aux valeurs R sur Hawke Channel 2024 (5 / 5 exact).

- **m6 (densité copépodes > 2 mm)** : agent filtre maintenant
  `size_um > 2000` **avant** le `groupby(sample_id, depth_bin)`.
  Précédemment, l'agrégation post-groupby (`sum(is_long)`) gardait des
  bins à `n_long = 0` qui contaminaient les moyennes surface/fond et
  produisaient des valeurs sous-estimées (jusqu'à -20 %). Top-5
  maintenant exact (5 / 5 valeurs).

- **Conversion d'unités UVP ↔ filet** : sur un prompt « donne-moi m5
  en ind/m³ pour pouvoir comparer à un filet », l'agent applique
  désormais `× 1000` et annonce la conversion explicitement (`Méthode :
  … · Conversion : × 1000 pour passer de ind./L à ind./m³`).

### Comportement validé (curl scenarios)

- Prompt vague : applique m5 par défaut + annonce méthode ✓
- Prompt override (« sum/sum sur tout le profil ») : suit l'utilisateur
  + annonce méthode différente ✓
- Prompt technique connue non documentée (« indice de Margalef ») :
  applique la formule standard `(S − 1) / ln(N)` direct sans demander ✓
- Prompt scope ambigu (« samples présents ») : pose une clarification,
  zéro tool call (règle ZERO-TOOL-CALL héritée de v3.2.0) ✓

### Comportements non couverts (potentiel v3.4)

- Pas de validation automatique des entrées d'un index écologique
  (Margalef sur catégories incluant `detritus` n'a pas de sens
  écologique mais l'agent applique sans filtrer).
- La ligne `Méthode : …` apparaît en tête (vague) ou en pied
  (override) selon le LLM — pas strictement « always start » comme
  prescrit dans le skill.
- Pipeline UVP : pas de support OBIS / IDEA Taxonomy comme source
  d'enrichissement post-m5.

---

## Versions antérieures

Voir `git log` et les tags GitHub (`v3.2.0`, `v3.1.0`, `v3.0.0`, …).
Le CHANGELOG démarre formellement à v3.3.0. Pour reconstituer
l'historique d'une version antérieure :

```bash
git log v3.1.0..v3.2.0 --oneline
git show v3.2.0
```
