# Planification de la refonte d’IDEA

**Période proposée :** du 14 septembre au 30 novembre 2026

**Dernière mise à jour :** 11 septembre 2026

## Objectif

Centraliser les données NeoLab dans un warehouse SQL mis à jour avec les
nouvelles données et directement interrogeable par IDEA. La V1 doit permettre à
IDEA de sélectionner les données en lecture seule par SQL, puis de réaliser les
analyses et graphiques en Python avec un chemin plus simple et reproductible.

Le périmètre V1 couvre quelques campagnes représentatives et les données
EcoTaxa, EcoPart, CTD, FILET ainsi que leurs métadonnées communes. L’intégration
complète des données historiques du laboratoire reste hors périmètre.

## Résultat attendu au 30 novembre

- warehouse V1 déployé et documenté ;
- accès SQL stable et strictement en lecture seule pour IDEA ;
- campagnes, clés, relations, unités et provenance documentées ;
- scénarios de référence validés de bout en bout ;
- flux et outils devenus inutiles identifiés.

## Règle de suivi

Ce fichier est la source de vérité du calendrier, de l’avancement et des
critères de sortie. Toute intervention doit commencer par identifier la phase et
le résultat attendu auxquels elle contribue. Après chaque travail réellement
exécuté, l’agent met à jour le statut et le journal ci-dessous avec les tests,
scénarios ou limites observés. Une phase passe à **Terminée** uniquement lorsque
son critère de réussite est vérifié. Une modification de code ou un test
unitaire isolé ne suffit pas à valider un scénario conversationnel.

Le suivi opérationnel peut être reproduit dans GitHub Project, mais les statuts
doivent rester synchronisés avec ce fichier versionné.

## Vue d’ensemble

| Phase | Période | Livrable | Critère de réussite | État |
|---|---|---|---|---|
| 1. Cadrage | 14–25 sept. | Schéma V1 et périmètre validés | Revue d’équipe confirmant que les jeux EcoTaxa, EcoPart, CTD et FILET retenus peuvent être reliés | En préparation |
| 2. Construction du warehouse V1 | 28 sept.–9 oct. | Warehouse échantillon utilisable en local | Données attendues retrouvées par SQL et jointures de référence cohérentes | À faire |
| 3. Validation des données | 12–23 oct. | Jeu de tests et anomalies documentées | Cas de référence conformes aux sources originales | À faire |
| 4. Déploiement | 26 oct.–6 nov. | Warehouse V1 accessible sur le VPS | Connexion stable, restauration testée et aucune écriture possible depuis IDEA | À faire |
| 5. Intégration IDEA | 9–20 nov. | IDEA travaille directement sur le warehouse | Plusieurs scénarios exécutés sans export ni enrichissement externe intermédiaire | À faire |
| 6. Simplification et validation finale | 23–30 nov. | Architecture V1 validée et documentée | Scénarios retenus réussis de bout en bout avec un flux plus simple et reproductible | À faire |

## Phase 1 Cadrage

**Sous-étapes**

- partir du projet IDEA Hawaii et l’adapter use case par use case prioritaire ;
- choisir les campagnes et jeux de données de la V1 ;
- revoir le schéma existant avec Cyril ;
- définir les relations et identifiants communs.

**Validation attendue :** revue avec l’équipe confirmant que les données
EcoTaxa, EcoPart, CTD et FILET sont reliables pour les cas retenus.

## Phase 2 Construction du warehouse V1

**Sous-étapes**

- créer la base SQL ;
- importer EcoTaxa et EcoPart ;
- importer CTD et FILET ;
- documenter les tables, unités, clés et sources.

**Validation attendue :** les données prévues sont retrouvées par SQL et les
jointures de référence produisent les résultats attendus.

## Phase 3 Validation des données

**Sous-étapes**

- comparer les données aux sources originales ;
- vérifier les profils, dates, profondeurs et la taxonomie ;
- tester plusieurs jointures connues ;
- consigner les écarts et leur résolution.

**Validation attendue :** les cas de référence donnent les mêmes informations
que les sources originales, dans les tolérances documentées.

## Phase 4 Déploiement

**Sous-étapes**

- déployer PostgreSQL sur le VPS ;
- configurer les accès, sauvegardes et mesures de sécurité ;
- tester une restauration ;
- donner à IDEA un accès en lecture seule.

**Validation attendue :** la connexion est stable, la restauration est testée
et l’identité utilisée par IDEA ne peut effectuer aucune écriture.

## Phase 5 Intégration IDEA

**Sous-étapes**

- connecter IDEA au warehouse SQL ;
- tester la compréhension du schéma ;
- sauvegarder les sous-ensembles utiles dans le workspace ;
- exécuter les analyses Python et produire les graphiques.

**Validation attendue :** plusieurs scénarios sont exécutés de bout en bout sans
export ni enrichissement externe intermédiaire.

## Phase 6 Simplification et validation finale

**Sous-étapes**

- comparer le nouveau flux au flux actuel ;
- identifier les outils devenus inutiles ;
- tester la non-régression ;
- documenter la V1 et la suite.

**Validation attendue :** les scénarios retenus fonctionnent de bout en bout
avec un flux plus simple, vérifiable et reproductible.

## Journal d’avancement

### 11 septembre 2026 Préparation du socle

- dépôt initialisé depuis IDEA Hawaii `next-dev` au commit
  `5b1322dbe68fefd31fc1de29a076b1746a36c5d7` ;
- ancienne version NeoLab préservée dans l’archive locale
  `../IDEA-archive-20260911` ;
- stack locale macOS ARM64 démarrée avec Open WebUI, LangGraph, LiteLLM,
  Langfuse, PostgreSQL, Redis et sandbox Docker ;
- modèle local configuré sur `gpt-5.5` et Pipe IDEA rendu disponible dans Open
  WebUI ;
- 268 tests de la suite principale et 11 tests du sandbox réussis ;
- exécution Python réelle et persistance d’un DataFrame dans un noyau actif
  vérifiées.
- RAG natif Open WebUI désactivé globalement pour les nouveaux téléversements
  locaux : le client demande `process=false` et le serveur impose ce choix même
  lorsqu’un ancien client demande `process=true` ; test HTTP réussi avec
  réponse `data: {}`, journal serveur `process=False`, sans suivi de traitement
  ni génération d’embeddings ;
- 24 tests ciblés réussis pour la politique sans RAG et le déploiement des
  assistants Open WebUI ;
- traitement d’embeddings lancé par l’ancien chemin sur un CSV arrêté avant le
  déploiement du correctif.

**Limites restantes :** aucun schéma warehouse V1 ni jeu de campagnes n’est
encore validé avec l’équipe. Aucun use case scientifique NeoLab n’est encore
déclaré validé sur ce socle. Cette politique globale empêche aussi l’indexation
de nouveaux fichiers dans Open WebUI Knowledge ; le flux PaperQA devra être
validé séparément avant sa réactivation.
