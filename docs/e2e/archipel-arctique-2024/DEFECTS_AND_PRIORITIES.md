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

### D-A2 · Manifeste du livrable PDF contradictoire (À CORRIGER)
- **Symptôme** : PDF impossible à générer ; le bloc de références auto-injecté
  ajoute des DOI EcoTaxa/EcoPart que la validation du manifeste rejette ensuite
  comme non déclarés.
- **Cause probable** : `deliverable_tool` / manifeste — l'auto-injection de DOI
  depuis le registre de sources entre en conflit avec la déclaration URL-only.
  Dépend des données : projets avec DOI enregistré (17498, EcoPart 1100)
  déclenchent la contradiction ; Baffin (14859, sans DOI) passait.
- **Priorité** : réconcilier l'auto-injection et la validation dans le manifeste.

## P2 — Majeurs

### D-B1 · Sélection implicite du mauvais dataframe (`df` nu)
- **Symptôme** : audit initial sur la table EcoPart (216 col) au lieu de la
  finale Amundsen (226 col) ; température/salinité « non trouvées » (§6).
  Récidive au §8 (corrélations sur une table sans colonnes env.).
- **Cause** : l'agent retombe sur `df` nu / une table intermédiaire au lieu de
  la variable de session explicite, malgré la règle du system prompt.
- **Priorité** : renforcer le routage vers les variables `df_*` explicites, ou
  faire échouer plus tôt quand la colonne visée est absente.

### D-B2 · Intermédiaires canoniques non persistés
- **Symptôme** : la table canonique portant abondance + env (bâtie au §8) ne
  peut pas être réutilisée au §10 ; l'agent doit tout reconstruire.
- **Cause** : les tables dérivées calculées via `run_pandas` ne sont pas
  systématiquement stockées comme variables de session réutilisables.
- **Priorité** : persister les tables canoniques nommées pour réutilisation
  inter-tours.

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
