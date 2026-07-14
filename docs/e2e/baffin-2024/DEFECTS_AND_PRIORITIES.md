# Défauts observés et priorités de correction

Backlog issu du scénario E2E « baie de Baffin 2024 ». Les priorités reflètent
d'abord le risque de produire un résultat scientifique faux, puis la capacité à
terminer le workflow, et enfin la qualité de restitution.

## Synthèse des priorités

| Priorité | Thème | Pourquoi maintenant |
|---|---|---|
| P0 | Résolution taxonomique hiérarchique | Change directement les comptages et les abondances |
| P0 | Table canonique sample–profondeur | Évite doublons, zéros incohérents et corrélations biaisées |
| P0 | Validation des calculs d'abondance | Empêche de publier des concentrations non reproductibles |
| P1 | Résolution automatique du schéma d'enrichissement | Évite les échecs Amundsen sur des colonnes pourtant présentes |
| P1 | Provenance et manifeste de traçabilité | Garantit des sources exactes et un PDF générable du premier coup |
| P1 | Contrats de graphiques | Empêche les axes invalides et les demandes partiellement exécutées |
| P1 | Rapport final déterministe | Empêche les chiffres perdus et les affirmations contradictoires |
| P2 | Sobriété des tools et du contexte | Réduit latence, sorties massives et erreurs de quota |
| P2 | Qualité éditoriale et UI | Améliore lisibilité sans changer les résultats |

## P0 — Bloquants pour la validité scientifique

### D01 — Le filtre « Copepoda » n'est pas hiérarchique

- **Symptôme :** le premier filtre recherchait la chaîne `copepod` dans
  `object_annotation_category`.
- **Preuve :** RA18 contenait `Calanoida`, mais a été exclu du premier tableau.
- **Contournement observé :** liste manuelle de noms (`Calanoida`,
  `Heterorhabdidae`, `Paraeuchaeta`, etc.).
- **Risque :** faux négatifs, comptages incomplets et résultats différents selon
  les noms ajoutés au prompt.
- **Correction attendue :** un résolveur taxonomique unique qui sélectionne
  Copepoda et tous ses descendants à partir d'une hiérarchie/identifiant stable,
  réutilisé par les tables, analyses et graphiques.
- **Test de régression :** une fixture contenant `Copepoda`, `Calanoida`, un
  descendant plus profond et un taxon hors Copepoda doit produire exactement le
  même masque dans tous les workflows.

### D02 — Incohérence des comptages RA18 entre deux analyses

- **Symptôme :** RA18 avait un Calanoida à 214 m, puis le recalcul sur tous les
  bins a déclaré 10 bins à abondance nulle.
- **Risque :** les profils, corrélations, cartes et le PDF peuvent reposer sur des
  données différentes au sein de la même session.
- **Cause probable à vérifier :** reconstruction répétée du masque taxonomique et
  de la table sample–profondeur dans chaque bloc de code.
- **Correction attendue :** matérialiser une table canonique versionnée contenant
  `sample_id`, station, bin, volume, compte taxonomique, abondance et variables
  environnementales ; tous les calculs aval doivent la réutiliser.
- **Test de régression :** RA18 doit conserver le même compte dans le tableau,
  les corrélations et les datasets de graphiques.

### D03 — Bins dupliqués lors de l'agrégation

- **Symptôme :** deux lignes RA02 ont été affichées à 512 m avec le même volume,
  mais des comptes séparés.
- **Cause probable à vérifier :** groupement sur une valeur flottante de volume
  ou arrondi appliqué à des moments différents.
- **Risque :** division incorrecte du compte, profils fragmentés et moyennes
  faussées.
- **Correction attendue :** clé de groupe stable `(sample_id, depth_bin_id)` ; le
  volume devient une valeur agrégée/validée, jamais une composante de la clé.
- **Test de régression :** des volumes flottants quasi identiques dans un même bin
  doivent produire une seule ligne avec un compte consolidé.

### D04 — Définition de l'abondance insuffisamment verrouillée

- **Symptôme :** le workflow assimile les objets UVP annotés à des individus et
  divise leur nombre par `ecopart_Sampled volume [L]` sans contrôle formel de
  l'unicité du volume par bin.
- **Risque :** unité scientifiquement ambiguë ou double utilisation du volume.
- **Correction attendue :** fonction dédiée et testée qui explicite le numérateur,
  le dénominateur, l'unité, les exclusions, les zéros et les règles de volume.
- **Test de régression :** cas manuel simple avec comptes et volumes connus,
  vérifié en ind./L et ind./m³.

### D05 — Corrélations initiales calculées seulement sur les bins positifs

- **Symptôme :** la première analyse a retenu 23 bins contenant des copépodes et
  a exclu tous les zéros.
- **Impact observé :** les coefficients ont changé nettement après inclusion des
  137 bins échantillonnés.
- **Risque :** biais de sélection et associations surestimées.
- **Correction attendue :** par défaut, partir de tous les bins effectivement
  échantillonnés et remplir les absences taxonomiques par zéro ; toute analyse
  « présence seulement » doit être explicitement demandée.
- **Test de régression :** vérifier `n` et les coefficients sur une fixture avec
  bins positifs et nuls.

### D06 — Indicateur `m5` inventé et formule non justifiée

- **Symptôme :** la première analyse a créé un indicateur `m5` en moyennant
  surface et fond, alors qu'il n'était pas demandé.
- **Risque :** métrique non définie présentée comme résultat scientifique.
- **Correction attendue :** interdire toute métrique métier non chargée depuis un
  skill/référentiel ou non explicitement demandée ; validation de formule avant
  exécution.
- **Test de régression :** une demande générique d'abondance ne doit jamais
  produire `m5`/`m6` spontanément.

## P1 — Bloquants pour un workflow E2E fiable

### D07 — Mauvaise colonne temporelle choisie pour Amundsen

- **Symptôme :** première tentative avec `sampledatetime`, colonne absente ; la
  seconde a réussi avec `object_date`.
- **Risque :** rupture d'un workflow autonome après un enrichissement réussi.
- **Correction attendue :** inspection de schéma déterministe et alias de
  colonnes (`object_date`, `sampledatetime`, etc.) avant l'appel lourd ; message
  de plan indiquant les colonnes résolues.
- **Test de régression :** table EcoTaxa–EcoPart avec `object_date` seulement.

### D08 — Source Amundsen absente de la réponse d'enrichissement

- **Symptôme :** l'enrichissement Amundsen a annoncé 3 650/3 650 appariements,
  mais la réponse ne citait qu'EcoTaxa et EcoPart.
- **Risque :** résultat non traçable et source difficile à reconstruire dans le
  PDF.
- **Correction attendue :** chaque enrichissement réussi doit retourner un objet
  de provenance structuré : source, dataset, URL, paramètres, date et couverture.
- **Test de régression :** une réussite Amundsen sans URL/dataset doit échouer à
  la validation de réponse.

### D09 — Génération PDF refusée à cause de DOI non déclarés

- **Symptôme :** deux appels de génération ont été rejetés parce que le contenu
  contenait des DOI absents du manifeste.
- **Risque :** clôture impossible malgré une étude complète.
- **Correction attendue :** construire les références uniquement depuis le
  manifeste, sans laisser le modèle injecter des références libres dans le
  contenu ; rapporter précisément l'URL fautive en cas de rejet.
- **Test de régression :** manifeste à trois sources, contenu contenant seulement
  ces trois sources, puis cas négatif avec une quatrième URL.

### D10 — Le PDF perd des faits présents dans la conversation

- **Symptôme :** le premier PDF indiquait « couverture non communiquée » alors
  que 3 650 lignes, 3 650/3 650 et 100 % avaient été annoncés.
- **Risque :** journal final incomplet ou faux.
- **Correction attendue :** alimenter le PDF depuis un registre d'opérations
  structuré au moment des appels, pas depuis une reconstruction libre de la
  conversation.
- **Test de régression :** les valeurs d'export et de couverture enregistrées
  doivent apparaître à l'identique dans les méthodes et le journal.

### D11 — Phrase contradictoire persistante dans le PDF

- **Symptôme :** le PDF final affirme encore que les nombres bruts EcoTaxa ne
  sont pas documentés, tout en affichant 3 650 lignes et 145 colonnes.
- **Risque :** perte de confiance dans le livrable.
- **Correction attendue :** contrôle de cohérence factuel avant rendu (détection
  de « non communiqué/non documenté » lorsque la valeur existe dans le
  manifeste).
- **Test de régression :** snapshot texte du PDF sans contradictions sur les
  champs structurés.

### D12 — Axes partagés entre profondeur et abondance

- **Symptôme :** un `sharey=True` global a lié un axe de profondeur inversé aux
  trois axes d'abondance.
- **Risque :** graphiques mathématiquement ou visuellement trompeurs.
- **Correction attendue :** recettes de graphiques typées ; interdiction de
  partager un axe lorsque les variables ou unités diffèrent ; validation de
  métadonnées d'axes avant rendu.
- **Test de régression :** le profil seul doit être inversé et les panneaux
  environnementaux doivent garder une échelle indépendante.

### D13 — Demande cartographique exécutée partiellement

- **Symptôme :** la demande température + salinité n'a produit qu'une carte de
  température.
- **Autres défauts initiaux :** trop de panneaux, regroupement profond
  superposé, emprises variables, absence de légende de taille et zéros non
  distingués.
- **Correction attendue :** plan de figures structuré avec checklist de sortie ;
  vérifier que chaque figure demandée a un artefact et satisfait son contrat.
- **Test de régression :** une demande de deux figures doit retourner exactement
  deux artefacts ou un statut partiel explicite.

### D14 — Découpage géographique non fondé sur les données

- **Symptôme :** trois secteurs ont été proposés alors que la table complète de
  coordonnées n'était pas accessible au calcul.
- **Risque :** sélection spatiale inventée.
- **Correction attendue :** ne proposer un découpage qu'après calcul sur une
  table de coordonnées ; sinon signaler l'impossibilité et demander/charger les
  données nécessaires.
- **Test de régression :** absence de dataframe spatial → aucune limite chiffrée
  ni recommandation de secteur.

## P2 — Performance, UX et qualité éditoriale

### D15 — Résumé EcoTaxa massif pour une demande synthétique

- **Symptôme :** la présentation des samples a déclenché un résumé taxonomique
  détaillé de 62 samples.
- **Impact :** sortie tool très longue, contexte gonflé et latence inutile.
- **Correction attendue :** route « présenter » vers métadonnées/groupements ;
  réserver le résumé d'objets à une demande taxonomique explicite.

### D16 — Contexte très volumineux et erreur de quota 429

- **Symptôme :** le pilote précédent a rencontré une limite TPM ; la conversation
  manuelle a dépassé environ 80 000 tokens de prompt avant certaines réponses.
- **Correction attendue :** résultats de tools compacts et structurés, pagination,
  réutilisation des tables persistantes, résumé contrôlé des anciennes étapes et
  retry automatique du runner.

### D17 — Noms internes de tools visibles dans Open WebUI

- **Symptôme :** les blocs de détails exposent des noms tels que `run_pandas`,
  `run_graph` ou les noms d'enrichissement.
- **Risque :** violation de la règle produit qui interdit d'exposer les noms
  internes à l'utilisateur final.
- **Correction attendue :** libellés UI métier ou masquage des détails techniques
  en mode utilisateur, tout en les conservant dans les traces développeur.

### D18 — Sorties finales parfois trop pauvres

- **Symptôme :** certaines réponses de graphiques contenaient seulement l'image
  et une phrase en anglais, sans méthode, source métier ni limites détaillées.
- **Correction attendue :** gabarit clinique uniforme : Résultat / Source /
  Méthode / Limite / Prochaine action.

### D19 — Problèmes éditoriaux du PDF

- **Symptômes :** « Cadre de l'étude » dupliqué en première page, légendes de
  figures répétées, identifiant interne de dataframe affiché comme source.
- **Correction attendue :** dédoublonnage des sections, une seule légende par
  figure et affichage des sources métier plutôt que des variables internes.

### D20 — Les essais rejetés ne sont pas des artefacts structurés

- **Symptôme :** les erreurs et figures non retenues ont dû être reconstruites à
  partir de la conversation.
- **Correction attendue :** journal de scénario machine-readable avec statut
  `passed`, `failed`, `replaced` ou `partial`, causes et artefacts associés.

## Ordre d'implémentation recommandé

1. **Socle scientifique : D01–D06.** Construire et tester le masque taxonomique,
   la table canonique sample–profondeur et le calcul d'abondance.
2. **Enrichissements : D07–D08.** Résolution de schéma et provenance structurée.
3. **Analyses et graphes : D12–D13.** Faire consommer la table canonique par des
   recettes validées.
4. **Livrable : D09–D11 puis D19.** Générer le PDF depuis le registre structuré et
   ajouter un contrôle de cohérence texte/manifest.
5. **Robustesse E2E : D15–D18 et D20.** Réduire le contexte, automatiser la
   validation et conserver tous les statuts.

## Premier lot TDD proposé

Le premier lot devrait rester vertical et démontrable :

1. fixture de trois samples incluant un `Calanoida` ;
2. résolveur Copepoda hiérarchique ;
3. constructeur de table sample–profondeur sans doublon ;
4. calcul ind./L et ind./m³ incluant les bins nuls ;
5. assertion que RA18 garde le même compte dans la table, la corrélation et les
   données de graphique.

Ce lot ferme D01 à D05 et fournit une base stable pour les corrections aval.
