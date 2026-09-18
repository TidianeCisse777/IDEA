# Planification de la refonte d’IDEA

**Période proposée :** du 14 septembre au 30 novembre 2026

**Dernière mise à jour :** 18 septembre 2026

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
| 1. Cadrage | 14–25 sept. | Schéma V1 et périmètre validés | Revue d’équipe confirmant que les jeux EcoTaxa, EcoPart, CTD et FILET retenus peuvent être reliés | En cours — proposition de schéma rédigée, revue attendue |
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
- observabilité branchée sur le projet Langfuse US Cloud : diagnostic du rejet
  401 causé par l’hôte local et un caractère non ASCII dans la clé secrète,
  correction de la paire, hôte Compose rendu configurable, puis trace d’un
  appel `gpt-5.5` validée par l’API Cloud ;
- suivi utilisateur/session du mode Normal validé de bout en bout via
  Open WebUI/LangGraph/LiteLLM : la trace Cloud contient l’email comme
  `userId` et la conversation comme `sessionId` ; le mode Advanced reste hors
  de ce périmètre tant que son chemin `/v1/responses` ne conserve pas ces
  attributs avec la version LiteLLM épinglée ;
- traitement d’embeddings lancé par l’ancien chemin sur un CSV arrêté avant le
  déploiement du correctif.

### 14 septembre 2026 Rechargement de la clé OpenAI

- `OPENAI_API_KEY` est présente dans `.env` et valide par `curl` ;
- après libération de caches locaux et redémarrage de Docker Desktop, les
  services LangGraph/LiteLLM ont été recréés ;
- les empreintes de la variable dans les deux conteneurs correspondent à `.env`
  et `GET /health` de LangGraph répond correctement.

**Limite :** le test de santé ne remplace pas encore un échange conversationnel
complet avec appel d’outil depuis Open WebUI.

### 18 septembre 2026 Proposition de schéma warehouse

- Proposition documentée dans [docs/WAREHOUSE_PROPOSAL.md](docs/WAREHOUSE_PROPOSAL.md) :
  grains FILET/UVP/CTD, sources EcoTaxa/EcoPart/Amundsen, versions, appariements,
  vues SQL en lecture seule et journal d'exploration séparé.
- Documentation locale et pages officielles des fournisseurs consultées.
- Limites : archive absente au chemin prévu ; aucun export métier inspecté,
  aucune jointure exécutée, aucun test runtime ni validation scientifique.
- Phase 1 en cours, non validée. Prochaine étape : revue des exports et des
  règles d'appariement avec Cyril et l'équipe sur une campagne représentative.
- GitHub Project : aucun identifiant de projet trouvé dans les références
  locales consultées ; synchronisation non effectuée. Aucun push ni publication.

### 18 septembre 2026 Jointures et calculs confiés aux outils

- Cadrage corrigé sur demande : jointures scientifiques et calculs métier
  confiés à des outils déterministes ; exploration par l'agent de relations
  préparées. Appariement FILET/UVP ↔ CTD spatial et temporel, extraction
  verticale séparée.
- [Brouillon SQL pour revue](docs/warehouse_schema_proposal.sql) ajouté :
  données versionnées, unités FILET/UVP/CTD, observations, politiques,
  exécutions, correspondances, résultats et historique d'exploration.
- Limites : DDL non exécuté, outils non implémentés, droits et publication
  immuable à construire ; pas de validation scientifique ni de fin de phase.
  GitHub Project reste non synchronisé, faute d'identifiant identifié.

### 18 septembre 2026 Recentrage sur SQL vers DataFrame

- La correction utilisateur remplace le cadrage précédent : IDEA génère du
  SQL en lecture seule et charge les résultats dans son notebook. `work.*`
  retiré du brouillon ; relations connues et vues simples prioritaires.
- Code public EcoPart consulté au commit
  `4dcd5968bb299b42d2f38406b19b8ca8354503f8` : CTD importée par nom
  d'échantillon dans le projet, export EcoTaxa via projet lié et `orig_id`.
  Ces preuves ne confirment pas la version ni les exports NeoLab.
- Proposition et SQL révisés. Clés FILET et liens avec le catalogue CTD
  Amundsen encore à vérifier sur les données ; aucun appariement, DDL ou
  scénario notebook exécuté. Phase 1 toujours en cours. GitHub Project
  non synchronisé, identifiant toujours non disponible.

### 18 septembre 2026 Vérification des exports FILET réels

- CSV retrouvés sur le Bureau et inspectés en lecture seule : métadonnées
  6 105 lignes, abondances/biomasses 5 047 lignes, dictionnaire de 93 colonnes.
  Empreintes et preuves dans [docs/FILET_EXPORT_REVIEW.md](docs/FILET_EXPORT_REVIEW.md).
- Jointure pandas `many_to_one` sur SAMPLE_ID + ANALYSIS_ID : 4 941 appariés,
  106 non appariés (9 analyses de 2024 absentes des métadonnées), sans
  multiplication des lignes. Aucun écart sur six champs de contexte comparés.
- Schéma FILET corrigé : multiples analyses/filets, valeurs déjà calculées,
  deux volumes, biomasses et stades/agrégats distincts, LEFT JOIN explicite.
- Limites : aucun identifiant CTD/EcoTaxa explicite dans ces exports ; DDL
  non exécuté, scénario IDEA non testé. Phase 1 en cours ; GitHub Project
  non synchronisé, identifiant non disponible. Aucun fichier source modifié.

### 18 septembre 2026 Recherche de l'ancien schéma et exports UVP

- Ancien schéma SQLite non retrouvé ; le dossier `~/PROJET_INFO/IDEA` ne
  contient aucun fichier. Archive attendue toujours absente.
- Exports et script R retrouvés dans Downloads/UVP_metrics_for_MCA : 30 profils
  communs EcoTaxa/EcoPart, clé profil + profondeur EcoPart unique. Jointure
  reproduite en lecture seule : 137 128/137 128 objets appariés sans duplication.
- Preuves dans [docs/UVP_EXPORT_REVIEW.md](docs/UVP_EXPORT_REVIEW.md).
  Champ CTD présent mais partiellement vide ; lien Amundsen non vérifié.
  Aucun changement runtime/DDL, phase 1 non clôturée. GitHub Project reste
  non synchronisé faute de référence identifiée.

### 18 septembre 2026 Ancien schéma retrouvé dans Git

- Ancien code NeoLab retrouvé dans `origin/main` (`475af5d`) et les branches
  EcoPart/comparabilité. Inspection par `git show`, aucun checkout.
- DDL SQLite EcoTaxa et manifeste EcoPart, pont SQL/DataFrame, contrat de
  jointure EcoTaxa/EcoPart et matcher CTD par nom de fichier examinés.
  Références dans [docs/LEGACY_WAREHOUSE_REFERENCES.md](docs/LEGACY_WAREHOUSE_REFERENCES.md).
- La recherche antérieure concernait les fichiers sur disque : le code
  historique est disponible dans Git, les bases de données remplies ne sont
  pas retrouvées. Aucun test historique exécuté, phase 1 toujours en cours.
  GitHub Project non synchronisé faute de référence identifiée.

### 18 septembre 2026 Validation documentaire de la proposition V1

- Contrat V1 récapitulé : métadonnées EcoTaxa conservées, UVP dérivé
  EcoTaxa/EcoPart par bin, FILET importé avec ses abondances normalisées,
  CTD reliée au profil et surface SQL pour DataFrame.
- Diagramme ajouté dans [docs/WAREHOUSE_ARCHITECTURE.md](docs/WAREHOUSE_ARCHITECTURE.md).
- Neuf tests de contrat ajoutés dans `tests/test_warehouse_schema.py` : couches,
  grains, formule UVP, agrégation pondérée, conservation des valeurs FILET,
  liens CTD et conservation des non-appariés. Résultat : 9/9 réussis.
- Limites : DDL PostgreSQL non déployé et vue finale `filet_uvp_abundance`
  encore à implémenter après validation des colonnes CTD et du support vertical.
  Phase 1 reste en cours ; aucun use case conversationnel déclaré validé.

**Limites restantes :** aucun schéma warehouse V1 ni jeu de campagnes n’est
encore validé avec l’équipe. Aucun use case scientifique NeoLab n’est encore
déclaré validé sur ce socle. Cette politique globale empêche aussi l’indexation
de nouveaux fichiers dans Open WebUI Knowledge ; le flux PaperQA devra être
validé séparément avant sa réactivation.
