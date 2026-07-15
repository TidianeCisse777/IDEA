# Observations et validations

## Tour 1 — chargement

- Statut : réussi.
- Première tentative : erreur de transport locale liée au sandbox ; service
  Docker confirmé sain, même tour rejoué sans changer le prompt.
- Dataset : 137 128 lignes × 130 colonnes.
- Période : 3–12 septembre 2024.
- Couverture : 30 samples, un instrument, latitudes 52.5017–53.4451,
  longitudes -54.7102–-53.3292.
- Annotation annoncée : `predicted`.
- À vérifier ensuite : stations, profondeurs, colonnes exactes, BOM de
  `object_id`, hiérarchie taxonomique et volumes.
- Décision : passage au contexte scientifique.

## Tour 2 — contexte, tentative 1

- Statut : échec factuel.
- Réponse observée : Qikiqtarjuaq, 2015, projet 42, un sample et 1 124 objets.
- Contradiction : le tour 1 établit 30 samples, 137 128 lignes et septembre
  2024 ; l’inspection locale confirme des stations `HC-*`.
- Source erronée ajoutée : URL EcoTaxa du projet 42, non utilisée pour charger
  le dataset Hawke Channel.
- Défaut : contamination par un dataset antérieur ou mauvais routage vers une
  source distante au lieu de la table locale active.
- Décision : retenter en imposant la table locale et un calcul sur ses colonnes.

## Tour 2 — contexte, tentative 2

- Statut : réussi.
- Stations : 30 (`HC-02` à `HC-32`, liste exacte dans la réponse).
- Période : 3–12 septembre 2024.
- Emprise : latitude 52.5017–53.4451 ; longitude -54.7102–-53.3292.
- Profondeur objet : 5.44–579.64 m.
- Source : table locale uniquement, aucune URL distante ajoutée.
- Décision : passage à la table station–sample.

## Diagnostic du défaut du tour 2

- Alias actifs inspectés : `df`, `df_file_ecotaxa_hawkechannel_30jan` et
  `ecotaxa` pointent tous vers le bon fichier 137 128 × 130.
- BOM : correctement retiré par le chargeur ; la colonne persistée est
  `object_id`.
- Appel fautif exact :
  `summarize_ecotaxa_sample_deployment(sample_id=42000002)` après chargement
  inutile de `ecotaxa_navigation`.
- `42000002` n’est fourni ni par l’utilisateur ni par le fichier.
- Classification : mauvais routage vers une source distante + argument inventé.

## Tour 3 — stations et samples

- Statut final : réussi.
- Résultat : 30 stations, 30 samples, relation 1:1.
- Défaut intermédiaire : première tentative de calcul avec
  `sample_id.astype(int)`, refusée pour `hc_02_030924`; seconde tentative
  conserve correctement les identifiants comme chaînes.
- La réponse finale contient les 30 lignes malgré l’aperçu des résultats de
  calcul limité à 20 lignes.
- Décision : passage à l’audit biologique.

## Tour 4 — audit biologique, tentative 1

- Statut : partiel.
- Présence complète : sample, station, hiérarchie, profondeurs et coordonnées.
- Hiérarchie : 55 valeurs distinctes.
- Défaut : aucun contrôle de l’unicité `object_id`, du nombre de Copepoda, des
  volumes, des bins ou des doublons.
- Défaut : le verdict n’indique pas explicitement qu’EcoPart est requis avant
  le calcul d’abondance volumique.
- Décision : demander un complément ciblé avant passage.

## Tour 4 — audit biologique, tentative 2

- Statut : échec transport/API.
- Réponse HTTP : 500 `Internal Server Error`.
- Cause logs : trois erreurs fournisseur 429 TPM ; limite 200 000, requête
  rejetée après les retries du client.
- Défaut : `serve.py` laisse remonter `RateLimitError` en HTTP 500 au lieu de
  produire une réponse 429/contrôlée et retryable.
- Décision : rejouer le même prompt après le délai indiqué par le fournisseur.

## Tour 4 — audit biologique, tentative 3

- Statut : réussi.
- `object_id` : 137 128 uniques, aucun doublon.
- Copepoda hiérarchique : 18 498 lignes, six hiérarchies distinctes.
- Volume : `acq_volimage` détecté, mais aucun volume échantillonné utilisable
  pour une concentration.
- Conclusion correcte : EcoPart obligatoire avant `abundance_ind_L` et
  `abundance_ind_m3`.
- Nuance : le décompte de répétitions `(sample_id, object_depth_min)` mesure la
  nature objet-level de la table ; il ne démontre pas encore des bins canoniques
  dupliqués.
- Décision : passage à la résolution EcoPart.

## Tour 5 — disponibilité EcoPart

- Statut : réussi.
- Projet : EcoPart 1004, « Hawke Channel 2024 ».
- Résolution : proximité bbox, 30 samples candidats.
- Limite : aucun lien EcoTaxa direct ; correspondance géographique à confirmer
  par les profils lors de la jointure.
- Export : aucun.
- Décision : préparer le dry-run explicite sur EcoPart 1004.

## Tour 6 — plan EcoPart

- Statut : réussi avec défauts éditoriaux.
- Porte de confirmation : respectée ; aucune donnée téléchargée.
- Jointure annoncée : sample et bin de profondeur.
- Défaut : formulation « projet EcoPart 1004 → EcoPart 1004 ».
- Défaut : nom interne de l’opération exposé à l’utilisateur.
- Décision : confirmer explicitement.

## Tour 7 — enrichissement et jointure EcoPart

- Statut distant : refusé ; aucune table distante validée.
- Fallback local :
  `UVP_metrics_for_MCA/data/ecopart_hawkechannel_30jan.tsv`.
- Encodage réellement détecté : Latin-1 ; chargement réussi, 1 946 lignes ×
  73 colonnes, 30 profils.
- Défaut de routage reproduit : après `load_file`, l’agent appelle
  `join_ecotaxa_ecopart(project_id=1004)`, qui exige exclusivement le résultat
  distant de `query_ecopart(1004)` et ignore la table locale chargée.
- Défaut de réponse : mention résiduelle du projet EcoTaxa 42, provenant du
  contexte antérieur et sans rapport avec Hawke Channel.
- Relance explicite via analyse pandas locale : réussie.
- Clés : `sample_id` ↔ `Profile`, puis bin de profondeur de 5 m dérivé de
  `object_depth_max` ↔ `Depth [m]`.
- Couverture annoncée : 30/30 profils, 1 946/1 946 bins et
  137 128/137 128 objets appariés ; aucun non-appariement.
- Volume retenu : `Sampled volume [L]` ; aucun volume nul annoncé.
- Tous les bins EcoPart, y compris les abondances biologiques nulles, sont
  conservés dans `df_ecotaxa_ecopart`.
- Point à auditer au tour suivant : vérifier indépendamment que le binning de
  profondeur n’a pas été forcé et que la table persistée possède bien une ligne
  canonique par sample–profondeur avant tout calcul d’abondance.

## Tour 8 — contrôle de la jointure

- Première tentative : refusée, car `df_ecotaxa_ecopart` n’était pas réellement
  persistée.
- Cause : chaque appel `run_pandas` est isolé ; une table intermédiaire n’est
  persistée que si elle respecte le contrat canonique complet. La réponse du
  tour 7 avait annoncé à tort une persistance sous `df_ecotaxa_ecopart`.
- Reconstruction et audit effectués dans un seul appel pandas.
- Clés exactes : 30/30 correspondances `sample_id = Profile`.
- Backbone : 1 946 clés EcoPart sample–bin distinctes.
- Binning contrôlé : `floor(depth / 5) * 5 + 2.5`, sur
  `object_depth_max` et `Depth [m]`.
- Distance objet–centre : minimum 0 m, médiane 0 m, maximum 2,5 m ; aucun objet
  hors bin.
- Identifiants : 137 128 uniques avant, aucun doublon ajouté par l’expansion.
- Volumes : aucun manquant, nul ou négatif.
- Couverture : aucun bin EcoPart sans objet et aucun objet EcoTaxa hors plage.
- Verdict scientifique sur les clés et le binning : validé.
- Réserve technique : le `result` de ce contrôle reste éphémère. La prochaine
  étape doit construire directement la table canonique complète, ce qui
  déclenchera sa persistance sous `df_canonical_sample_depth`.

## Campagne de correction — C1

- Statut : corrigé et validé le 2026-07-15.
- Correction : la jointure locale accepte les variables persistées EcoTaxa et
  EcoPart explicitement et refuse leur combinaison avec un `project_id`.
- Protection mémoire : pour deux fichiers locaux, le routage ignore les IDs de
  projet EcoPart provenant des tours antérieurs.
- Tests ciblés : 121 réussis.
- Validation sur la conversation polluée : un seul appel métier, avec
  `ecotaxa_variable=df_file_ecotaxa_hawkechannel_30jan` et
  `ecopart_variable=df_file_ecopart_hawkechannel_30jan`, sans `project_id` et
  sans fallback pandas.
- Registre après curl : `df_ecotaxa_ecopart`, 137 128 × 202,
  137 128 lignes appariées, `depth_col_used=object_depth_min`.

## Campagne de correction — C2

- Statut : corrigé et validé le 2026-07-15.
- La formule de bin 5 m est centralisée et partagée par la jointure et l'audit.
- Un contrôle métier audite désormais la table persistée sans la reconstruire
  avec pandas.
- Défaut supplémentaire découvert : la jointure orientée EcoTaxa supprimait six
  bins EcoPart échantillonnés sans objet.
- Bins restaurés : `hc_04_030924/2.5`, `hc_08_040924/17.5`,
  `hc_10_040924/187.5`, `hc_18_060924/582.5`,
  `hc_20_070924/32.5`, `hc_32_090924/7.5`.
- Ces bins sont maintenant représentés par une ligne sans `object_id`, avec le
  volume EcoPart conservé ; ils deviendront des zéros dans la table canonique.
- Validation curl : 137 134 lignes = 137 128 objets appariés + 6 bins zéro.
- Audit : 1 946 clés sample–bin, zéro doublon objet, zéro volume manquant,
  non positif ou contradictoire, zéro objet hors bin.
- Trace : un seul appel `audit_ecotaxa_ecopart_join`, aucun `run_pandas`.
- Limite restante : les URLs projet 42/1004 ajoutées par le modèle restent à
  corriger dans C4/C6.

## Campagne de correction — C3

- Statut : corrigé et validé le 2026-07-15.
- Une table pandas ordinaire annonce désormais
  `Persistence: persisted=false; variable=null` et est effectivement absente au
  tour suivant.
- Une table canonique annonce
  `Persistence: persisted=true; variable=df_canonical_sample_depth` et est
  réutilisable au tour suivant.
- Premier contrôle avant exposition du compteur : le modèle avait annoncé à
  tort 1 018 bins zéro. Cause confirmée : le tool ne fournissait pas ce nombre
  et laissait le modèle l'estimer depuis le contexte pollué.
- Correctif complémentaire : calcul et stockage automatiques de
  `n_zero_abundance` lors de la persistance canonique.
- Rejeu curl corrigé : `n_rows=1946`, `n_zero_abundance=143`.
- Registre : table `1946 × 7`, métadonnée `n_zero_abundance=143`, comptage direct
  `copepod_count == 0` égal à 143.
- Trace `019f6645-6397-7b81-ab7c-797967ffa5f9` : uniquement le constructeur
  canonique officiel via `run_pandas`.

## Campagne de correction — C4

- Statut : corrigé et validé le 2026-07-15.
- État injecté à chaque requête : dataset actif
  `df_file_ecotaxa_hawkechannel_30jan`, source locale, dimensions et colonnes
  d'identité, sans valeurs de lignes ni ancien projet.
- Protection déterministe : les identifiants EcoTaxa provenant uniquement de
  tours anciens sont refusés avant l'exécution du tool.
- Les identifiants restent autorisés lorsqu'ils sont explicitement donnés par
  l'utilisateur, présents dans les métadonnées actives ou découverts par un tool
  pendant le même tour.
- Rejeu curl pollué par le projet 42/sample 42000002 : réponse fondée sur Hawke
  Channel, 137 128 lignes, 30 stations, période 2024-09-03–2024-09-12.
- Audit de trace : seulement `run_pandas` sur la variable locale exacte ; aucun
  appel `summarize_ecotaxa_sample_deployment` et aucun ID ancien.
