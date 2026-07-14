# EcoPart Confirmation Gate Design

## Objectif

Garantir que `enrich_ecotaxa_with_ecopart_remote(..., confirmed=False)` reste
une planification sans effet de bord, conformément à CT-AG-06. Aucun export,
aucun téléchargement et aucune mutation du store de session ne doivent se
produire avant une confirmation explicite.

Ce refactoring concerne uniquement le workflow d'enrichissement EcoTaxa vers
EcoPart. La jointure canonique `(sample_id, depth_bin)`, ses métriques de
couverture, les autres sources et les règles de routage du system prompt restent
inchangées.

## Défaut actuel

Quand aucun EcoTaxa n'est chargé mais que `ecotaxa_project_id` est fourni, le
tool appelle `_ensure_ecotaxa_project_loaded` avant d'examiner `confirmed`.
Cette fonction démarre un export EcoTaxa, attend sa fin, télécharge le TSV et
écrit le DataFrame dans la session. Un appel de planification peut donc exécuter
une opération distante coûteuse et muter l'état, puis annoncer qu'aucune donnée
n'a été téléchargée.

La confirmation est actuellement une convention de contrôle de flux placée
trop tard. Elle doit devenir un invariant du module d'opération lourde.

## Architecture retenue

Le workflow conserve son interface LangChain actuelle, mais son implémentation
est organisée en deux phases ordonnées.

### Phase de planification

Avec `confirmed=False`, le workflow utilise uniquement les informations déjà
présentes en session et les résolutions légères existantes. Il peut :

- lire l'EcoTaxa déjà chargé ;
- réutiliser un `project_id` présent dans les métadonnées ;
- effectuer les recherches légères déjà nécessaires pour identifier un projet
  EcoPart candidat ;
- retourner un plan décrivant les téléchargements et la jointure qui seront
  effectués après confirmation.

Il ne peut pas appeler l'adapter d'export EcoTaxa, télécharger un TSV EcoTaxa ou
EcoPart, ni écrire dans le store de session. Si le DataFrame EcoTaxa nécessaire
n'existe pas encore, le plan indique que son export sera réalisé pendant la
phase confirmée. Il ne prétend pas que les données ont déjà été chargées.

### Phase d'exécution

Avec `confirmed=True`, le workflow peut, dans cet ordre :

1. auto-charger le projet EcoTaxa demandé si aucune table correspondante n'est
   en session ;
2. résoudre le projet EcoPart à partir de la table EcoTaxa ;
3. télécharger EcoPart ;
4. effectuer la jointure canonique `(sample_id, depth_bin)` ;
5. stocker les datasets et rendre le rapport de couverture existant.

L'auto-chargement EcoTaxa reste une capacité interne du workflow confirmé. Il
ne constitue pas une seconde interface publique.

## Flux d'erreur

- Sans EcoTaxa en session, sans `ecotaxa_project_id` et sans métadonnée de
  projet réutilisable, le workflow retourne l'erreur explicite existante.
- Si un `ecotaxa_project_id` est fourni pendant un dry-run, le workflow retourne
  un plan conditionnel indiquant que ce projet EcoTaxa sera exporté après
  confirmation.
- Une erreur d'export EcoTaxa ou EcoPart n'écrit aucun résultat de jointure et
  conserve les messages d'erreur actuels.
- Une jointure sans correspondance conserve le diagnostic et ne doit pas être
  présentée comme un enrichissement réussi.

## Tests TDD

Le premier test reproduit la régression avec `confirmed=False`, aucune table
EcoTaxa en session et un `ecotaxa_project_id` explicite. Il vérifie :

- zéro appel à `start_export`, `wait_for_job` et `download_tsv` ;
- zéro appel au téléchargement EcoPart ;
- aucune nouvelle clé de session ni modification de la table active ;
- une réponse décrivant une exécution future, sans affirmation de téléchargement
  déjà effectué.

Les tests suivants vérifient que `confirmed=True` conserve l'auto-chargement,
le téléchargement EcoPart, la jointure et le stockage actuels. Les tests déjà
présents pour un EcoTaxa chargé et pour la couverture de jointure restent verts.

## Critères d'acceptation

- `confirmed=False` est sans effet de bord dans toutes les branches du workflow.
- `confirmed=True` conserve les trois workflows EcoTaxa–EcoPart documentés.
- Aucune modification du system prompt n'est nécessaire.
- Les docstrings restent assez explicites pour que le LLM demande confirmation.
- Les tests ciblés EcoPart et les tests d'intégration d'enrichissement passent.

## Hors périmètre

- Gestion du contexte LangGraph et plafond de tokens.
- Catalogue global des tools.
- Refonte du client EcoTaxa ou du client EcoPart.
- Modification des clés de jointure ou des métriques d'abondance.
- Généralisation immédiate du mécanisme à tous les tools coûteux.
