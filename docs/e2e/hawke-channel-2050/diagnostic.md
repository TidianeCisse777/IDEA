# Diagnostic des défauts — scénario Hawke Channel 2050

Date : 2026-07-15
Thread : `8d2a4a2b284a6566`
Run de jointure fautive : `019f6623-828a-7280-aed1-bab2807cfb03`
Run du fallback pandas : `019f6625-0238-7c40-93e3-8932e587ad8a`

## Verdict

Le scénario doit rester arrêté avant le calcul d'abondance. Les fichiers sont
compatibles et la jointure métier locale fonctionne, mais le trajet réellement
choisi par l'agent a contourné plusieurs contrats : mauvais argument de jointure,
fallback pandas interdit, persistance annoncée mais inexistante, audit fondé sur
une autre colonne de profondeur et contamination par un ancien projet.

Les tests unitaires des composants sont verts, mais aucun test ne verrouille
encore cette trajectoire multi-tour complète.

## D01 — Mauvais routage de la jointure locale

**Priorité : P0 — bloque le workflow scientifique.**

**Statut campagne : corrigé par C1 le 2026-07-15 ; validation curl et trace
réussie sur la conversation polluée d'origine.**

### Symptôme

Après chargement des deux fichiers locaux, l'agent appelle :

```text
join_ecotaxa_ecopart(project_id=1004)
```

Le tool répond que `query_ecopart(project_id=1004)` doit d'abord être exécuté,
alors que le fichier EcoPart local est déjà disponible sous l'alias `ecopart`.

### Reproduction minimale

Sur le même `SessionStore` :

```text
avec project_id=1004 → Données manquantes
sans argument         → Enrichissement terminé, 137128/137128 matchées
```

### Cause confirmée

Dans `_perform_enrichment`, un `project_id` explicite désactive la lecture de
l'alias `thread:ecopart` et cherche uniquement `df_ecopart_1004` ou l'ancienne
clé distante `thread:ecopart:1004`. Or `load_file` crée
`df_file_ecopart_hawkechannel_30jan` et l'alias `ecopart`, sans projet numérique.

Le prompt dit déjà d'omettre `project_id` pour le dernier fichier chargé, mais
le modèle a réutilisé l'ID 1004 visible dans l'historique.

### Correctif proposé

1. Étendre `join_ecotaxa_ecopart` avec des arguments explicites
   `ecotaxa_variable` et `ecopart_variable`.
2. Pour deux fichiers locaux, passer leurs variables exactes et interdire
   `project_id`.
3. Si `project_id` est fourni mais absent du registre, ne pas basculer
   silencieusement sur un fichier non identifié : retourner la liste concise des
   EcoPart présents et demander une résolution explicite.
4. Modifier le message de `load_file` EcoPart pour recommander
   `join_ecotaxa_ecopart()` sans argument lorsqu'un seul alias EcoPart existe.

### Tests requis

- Deux `load_file`, puis jointure sans argument : succès et persistance.
- Deux `load_file`, historique contenant `EcoPart 1004` : le trajet agent doit
  appeler la jointure sans `project_id`.
- Projet numérique explicitement chargé : sélection correcte de ce projet.
- Projet numérique absent : refus déterministe, sans demande trompeuse de
  téléchargement si un fichier local est présent.

## D02 — Fallback pandas interdit et divergence de binning

**Priorité : P0 — validité et traçabilité scientifiques.**

### Symptôme

Après le refus D01, l'agent reconstruit manuellement la jointure avec
`run_pandas`, malgré les règles explicites « never hand-roll the merge ».

Le tool métier utilise `object_depth_min`. Le fallback a d'abord utilisé
`object_depth_min`, puis a changé vers `object_depth_max` au second calcul. Le
verdict final a donc validé une règle différente de la jointure officielle.

### Cause confirmée

Le garde-fou existe seulement dans le prompt et le skill. Aucun contrat
exécutable n'empêche un `merge` EcoTaxa–EcoPart dans `run_pandas`, et aucun tool
d'audit ne permet au modèle de contrôler une jointure officielle sans la
réimplémenter.

### Correctif proposé

1. Ajouter un tool pur `audit_ecotaxa_ecopart_join` lisant la table persistée et
   rapportant clés, colonne de profondeur, duplications, volumes et couverture.
2. Centraliser le calcul du bin dans une fonction pure partagée par la jointure,
   l'audit et les tests ; aucune formule recopiée dans un prompt.
3. Ajouter un contrôle de trajectoire qui échoue si un appel `run_pandas`
   contient un merge entre variables EcoTaxa et EcoPart alors que le tool métier
   est disponible.
4. Le rapport d'audit doit exposer la colonne réellement utilisée depuis la
   provenance persistée, pas la redéduire.

### Tests requis

- Audit après jointure : `depth_col_used == object_depth_min`.
- Profondeurs min/max différentes : l'audit doit détecter toute divergence.
- Évaluation de trajectoire : aucun `run_pandas` entre deux fichiers locaux
  avant la jointure métier.

## D03 — Persistance annoncée mais inexistante

**Priorité : P0 — les tours suivants utilisent un état fantôme.**

### Symptôme

La réponse annonce `df_ecotaxa_ecopart`, mais l'appel suivant ne trouve pas cette
variable. La reconstruction pandas terminait par `result = joined`, qui est une
variable locale à l'appel.

### Cause confirmée

`run_pandas` isole chaque exécution. Il ne persiste automatiquement qu'une table
respectant le contrat complet `df_canonical_sample_depth`. Son résultat textuel
n'indique toutefois pas explicitement qu'un DataFrame non canonique est
éphémère. Le modèle a transformé « result » en promesse de persistance.

### Correctif proposé

1. Ajouter à toute sortie DataFrame non persistée :
   `Persistance : aucune — résultat éphémère à cet appel`.
2. Retourner une métadonnée structurée `persisted=false`, plutôt que laisser le
   modèle l'inférer depuis du texte.
3. Réserver `df_ecotaxa_ecopart` au seul tool de jointure métier.
4. Ajouter un registre structuré des datasets accessibles au prochain tour et
   l'injecter dans le contexte du modèle.

### Tests requis

- DataFrame arbitraire dans `run_pandas` : sortie `persisted=false`, variable
  absente au tour suivant.
- Table canonique complète : `persisted=true` et réutilisation possible.
- Réponse agent : interdiction d'affirmer « enregistrée » si le tool retourne
  `persisted=false`.

## D04 — Contamination de contexte et identifiant inventé

**Priorité : P0 — mauvaise source et mauvais dataset.**

### Symptôme

À la question sur le contexte du fichier Hawke Channel, l'agent charge le skill
de navigation EcoTaxa et appelle :

```text
summarize_ecotaxa_sample_deployment(sample_id=42000002)
```

Il répond Qikiqtarjuaq, 2015, projet 42, alors que le fichier actif contient 30
profils Hawke Channel en septembre 2024. L'ID 42000002 n'était présent ni dans la
question ni dans le fichier.

### Cause probable fortement étayée

- Le routage « contexte » favorise une source EcoTaxa distante même lorsqu'un
  fichier local vient d'être chargé.
- L'identité du dataset actif n'est pas injectée comme invariant structuré à
  chaque tour.
- Le trimming conserve un suffixe conversationnel, mais ne reconstruit pas un
  état compact et autoritatif des datasets actifs.
- Les règles anti-invention vivent dans le prompt ; aucun validateur ne relie
  l'argument `sample_id` à la question ou à une sélection visible.

### Correctif proposé

1. Injecter un « dataset state capsule » à chaque appel modèle : variables
   actives, source, dimensions, colonnes d'identité, projet éventuel.
2. Donner priorité absolue au fichier actif pour « ces données / ce fichier / la
   table chargée », sans source distante sauf demande explicite.
3. Ajouter un validateur d'arguments pour les outils EcoTaxa : un `sample_id`
   absent du message courant, d'une sélection persistée ou d'un résultat visible
   est refusé avant exécution.
4. Ajouter un test multi-tour où un ancien projet 42 précède le chargement Hawke
   Channel ; la question « contexte de ces données » doit rester locale.

## D05 — HTTP 429 exposé comme HTTP 500

**Priorité : P1 — fiabilité E2E et reprise automatique.**

### Symptôme

Trois retries fournisseur échouent sur la limite TPM. `RateLimitError` traverse
`agent.ainvoke`, et FastAPI retourne `500 Internal Server Error`.

### Cause confirmée

La route non-streaming appelle directement `await agent.ainvoke(...)` sans
traduction des exceptions fournisseur. Aucun gestionnaire global ne transforme
`openai.RateLimitError` en réponse 429.

### Correctif proposé

1. Capturer `RateLimitError` autour des chemins streaming et non-streaming.
2. Retourner HTTP 429 avec un corps stable, un `Retry-After` borné et un code
   machine-readable `provider_rate_limit`.
3. Ne pas enregistrer ce tour comme réponse assistant réussie.
4. Permettre au runner E2E de rejouer exactement le même tour, avec backoff et
   idempotence.

### Tests requis

- Agent mocké levant `RateLimitError` : HTTP 429, jamais 500.
- Présence de `Retry-After` et du code stable.
- Variante SSE : événement d'erreur structuré puis fermeture propre.

## D06 — Provenance et sources non garanties

**Priorité : P1 — confiance dans le rapport scientifique.**

### Symptôme

La réponse fautive ajoute des URLs EcoTaxa projet 42 et EcoPart 1004 alors que
la donnée analysée venait de deux fichiers locaux. Le projet 42 est faux ; le
projet 1004 n'est pas encodé dans les métadonnées du fichier local.

### Cause

La réponse finale compose encore certaines sources depuis l'historique et les
arguments du modèle. La provenance structurée du registre n'est pas l'unique
autorité de citation.

### Correctif proposé

- Générer le bloc Source depuis les métadonnées persistées, côté code.
- Pour un fichier local : chemin, empreinte, encodage, date de chargement.
- Ajouter une URL de projet seulement si son identifiant est prouvé par la
  provenance du dataset ou une résolution enregistrée.
- Interdire au modèle d'ajouter une URL numérique absente du registre.

## D07 — Budget de contexte incomplet

**Priorité : P1 — dérive de routage et 429.**

### Symptôme

Les requêtes observées montent de 52k à 69k tokens malgré un budget historique
configuré à 40k. Le trimming limite les messages, mais le total inclut aussi le
system prompt, les définitions des tools, les skills et la mémoire.

### Correctif proposé

- Budgéter l'entrée totale : système + tools + capsule d'état + historique.
- Remplacer les anciens gros résultats par des références au registre de
  datasets et aux artefacts.
- Déclencher une compaction avant le seuil TPM, pas seulement selon la longueur
  de l'historique.
- Journaliser séparément chaque composante du budget.

## D08 — Instrumentation temporaire laissée en production

**Priorité : P2 — confidentialité et bruit opérationnel.**

`serve.py` contient encore `[DEBUG-f1a2]` et journalise le début du dernier
message utilisateur ainsi que des métadonnées de requête. Cette instrumentation
doit être supprimée ou placée derrière une option désactivée par défaut avec
redaction stricte.

## Ordre de correction recommandé

1. D01 : rendre la jointure locale non ambiguë et testée au niveau trajectoire.
2. D02 : créer l'audit métier et interdire le fallback pandas de jointure.
3. D03 : rendre la persistance explicite et machine-readable.
4. D04 : capsule d'état + validation des identifiants + test de contamination.
5. D05 : convertir proprement les limites fournisseur en HTTP 429.
6. D06 : générer les sources uniquement depuis la provenance.
7. D07 : budget d'entrée total et compaction structurée.
8. D08 : retirer l'instrumentation temporaire.

## Boucles de validation E2E

Chaque correction doit être validée par :

1. un test unitaire au seam causal ;
2. un test de trajectoire agent sans réseau lorsque possible ;
3. le même `curl` Hawke Channel rejoué dans une nouvelle conversation ;
4. l'audit LangSmith des noms de tools et arguments ;
5. une assertion sur les variables réellement présentes dans le registre après
   le tour.
