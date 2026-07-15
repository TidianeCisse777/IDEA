# Défauts observés — Archipel arctique 2024 (leg4)

Défauts relevés pendant l'exécution e2e, classés par priorité. Les contrats
scientifiques récents ont tous **tenu** ; les défauts ci-dessous portent sur
l'outillage et le workflow autour d'eux.

## P1 — Bloquants

### D-A1 · Pas de pont label → sample_id numérique (CORRIGÉ)
- **Symptôme** : l'agent ne pouvait pas préparer l'export car il tenait les
  labels de samples (`am_leg4_RA76_1`) mais aucun tool ne renvoyait le
  `sample_id` numérique (`17498000023`).
- **Cause** : `preview_ecotaxa_project` n'expose que des `orig_id` d'objets ;
  `query_ecotaxa_sample` exige déjà le numéro ; aucun résolveur label → id.
- **Correctif** : nouveau tool `list_ecotaxa_project_samples` + règle de routage
  system prompt + tests TDD. **Résolu et vérifié en réel** (§3).

### D-A2 · Manifeste du livrable PDF contradictoire (CORRIGÉ)
- **Symptôme** : PDF impossible à générer ; des DOI EcoTaxa/EcoPart présents dans
  les références étaient rejetés comme non déclarés.
- **Cause** : `_manifest_source_urls` (l'allow-list) n'extrayait que `url`/`urls`
  et ignorait le champ libre `citation` et un éventuel `doi` — alors que le rendu
  des références, lui, émet les URLs de la citation. Le contrat se contredisait.
- **Correctif** : l'allow-list couvre désormais le champ `doi`/`dois` (formes
  bare + doi.org) et les URLs présentes dans `citation`/`name` d'une source
  **déclarée**. Le garde-fou reste strict : tout lien non rattaché à une source
  déclarée est toujours rejeté (on ne veut pas de lien non pertinent). Le skill
  `deliverable_writer` interdit explicitement d'inventer un DOI. Tests :
  `tests/test_deliverable.py` (+4).

## P2 — Majeurs

### D-B1 · Sélection implicite du mauvais dataframe (`df` nu) (ATTÉNUÉ)
- **Symptôme** : audit initial sur la table EcoPart (216 col) au lieu de la
  finale Amundsen (226 col) ; température/salinité « non trouvées » (§6).
  Récidive au §8 (corrélations sur une table sans colonnes env.).
- **Cause** : l'agent retombe sur `df` nu / une table intermédiaire au lieu de
  la variable de session explicite, malgré la règle du system prompt.
- **Correctif** : `run_pandas` transforme désormais une `KeyError` de colonne
  absente en indice actionnable — il nomme les variables `df_*` persistées qui
  **contiennent** la colonne visée, pour que l'agent recible au lieu de conclure
  « colonne absente ». Le routage reste piloté par le system prompt ; ce
  correctif rend l'erreur auto-corrigeable. Test : `tests/test_data_tools.py`.

### D-B2 · Intermédiaires canoniques non persistés (CORRIGÉ)
- **Symptôme** : la table canonique portant abondance + env (bâtie au §8) ne
  peut pas être réutilisée au §10 ; l'agent doit tout reconstruire.
- **Cause** : `run_pandas` ne persistait `df_canonical_sample_depth` que si le
  `result` final était la table canonique ; un intermédiaire (avec `result` =
  corrélations) était perdu.
- **Correctif** : `run_pandas` scanne aussi les variables intermédiaires et
  persiste la table canonique la **plus large** (colonnes env. conservées), même
  quand `result` est autre chose. Test : `tests/test_data_tools.py`.

## P3 — Mineurs / à noter

### D-C1 · Diagramme T–S non produit
- Conséquence de D-B1/D-B2 + absence de colonne station/profondeur propre dans
  la table active. Aucune interprétation faussée : l'agent a refusé plutôt que
  d'inventer (§10).

### D-C2 · depth_max incohérent entre présentation et cache
- Le tour 2 (aperçu) annonçait des profondeurs max (RA76 48,95 m) différentes du
  cache `samples_cache` (RA76 116,2 m) : l'aperçu reflète un sous-échantillon
  d'objets, le cache la profondeur de déploiement. À clarifier dans l'affichage.

## Ce qui a bien tenu (non-défauts)

- Taxonomie stricte, table sample–profondeur canonique, provenance
  d'enrichissement (100 %) et graph contracts ont tous bloqué les raccourcis
  incorrects sans jamais inventer de valeur — comportement conforme.
