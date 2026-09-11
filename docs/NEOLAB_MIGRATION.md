# Plan NeoLab : socle Hawaii et intégration par use case

## Objectif

Obtenir un assistant prévisible sur les parcours importants de NeoLab en
partant d'IDEA Hawaii, puis en adaptant progressivement les capacités de notre
ancienne version. Une intégration est utile si elle améliore un use case
mesurable ; ajouter un outil ne constitue pas, à lui seul, une validation.

## Point de départ — 11 septembre 2026

- Socle : `https://github.com/uhsealevelcenter/IDEA`, branche `next-dev`,
  commit `5b1322dbe68fefd31fc1de29a076b1746a36c5d7`.
- Archive locale : `../IDEA-archive-20260911`, historique, données et modifications
  non commitées préservés. Elle n'est pas une dépendance runtime.
- Aucun composant métier NeoLab encore porté.
- Raccordement local validé sur macOS ARM64 avec OpenAI via LiteLLM, modèle
  `gpt-5.5`, runtime `langgraph` et sandbox Docker. Les secrets restent dans le
  `.env` local ignoré par Git.
- Services démarrés : PostgreSQL, Redis, LiteLLM, Langfuse, sandbox, LangGraph
  et Open WebUI. Le parcours conversationnel a appelé Python avec succès via
  l'API LangGraph. Le Pipe est enregistré et son authentification interne a été
  corrigée dans Open WebUI.

## Étapes et critères de sortie

| Étape | Travail | Preuve requise avant la suivante | État |
|---|---|---|---|
| 0. Préserver et repartir | Archiver NeoLab, cloner Hawaii | Archive intacte et clone identifié | Terminé |
| 1. Raccorder notre modèle | Configurer et démarrer le socle | Un échange réel, un appel Python et un résultat visible dans Open WebUI | En cours : modèle, agent, Python et Pipe UI raccordés ; fichiers et figure à valider |
| 2. Évaluer le socle | Exécuter les parcours locaux ci-dessous | Résultats de référence, traces et limites de reprise documentés | À faire |
| 3. Choisir le premier use case métier | Fixer demande, données, oracle et ambiguïtés | Fiche de scénario priorisée avec NeoLab | À faire |
| 4. Intégrer une capacité | Porter les seuls éléments nécessaires | Tests du contrat et scénario complet répété avec succès | À faire |
| 5. Consolider puis élargir | Rejouer les acquis et sélectionner le use case suivant | Absence de régression observée sur les scénarios concernés | À répéter |

## 1. Raccordement modèle et infrastructure

Suivre le démarrage upstream du README et `docs/Quick-Deploy.md`, après
vérification de la compatibilité du serveur et de la microVM. Documenter
l'environnement réellement retenu, l'image du noyau et les services actifs.
Ne pas appliquer aveuglément l'import des anciennes données Hawaii : notre
archive NeoLab n'est pas leur ancien dossier de données SEA.

Vérifier ensemble `example.env`, `litellm/litellm_config.yaml`, les fichiers
Compose, `langgraph/idea_config.py` et la configuration Open WebUI : changer
uniquement un nom de modèle ne garantit pas un raccordement fonctionnel.

- Résoudre le fournisseur, l'endpoint, le modèle/alias et l'accès aux credentials
  sans exposer leur valeur. Ne pas copier intégralement l'ancien `.env`.
- Configurer `IDEA_AGENT_MODEL` et la route LiteLLM correspondante, dont
  `OPENAI_BASE_URL`, `OPENAI_API_KEY` et la clé virtuelle `LITELLM_VIRTUAL_KEY`.
- Recenser séparément les modèles auxiliaires (`IDEA_TOOL_MODEL`, tâches Open
  WebUI, PaperQA et Codex si activés) ; consigner lesquels sont testés ou exclus.
- Choisir explicitement `IDEA_AGENT_RUNTIME=langgraph` pour évaluer le graphe
  checkpointé, puis vérifier que la configuration est réellement consommée.
- Vérifier appel d'outil, streaming, exécution Python, fichiers et affichage
  d'une figure. Enregistrer le modèle réellement appelé et les erreurs éventuelles.

### Preuves locales du 11 septembre 2026

- LiteLLM a retourné une réponse réelle du modèle `gpt-5.5` et a transmis ses
  traces à Langfuse sans erreur signalée.
- Le sandbox Docker a conservé un DataFrame dans le même noyau entre deux
  appels Python : somme `12`, puis moyenne `4.0` au tour suivant.
- Un run complet de l'agent via `/chat-runs` a produit `AGENT_OK` après un appel
  d'outil Python.
- Les 268 tests du dossier `tests/` et les 11 tests du service sandbox passent
  dans leurs images Docker locales.
- Open WebUI public `v0.11.3` a été utilisé comme image locale ARM64, car
  l'image Hawaii sur GHCR exige une authentification. Son endpoint `/health`
  répond avec HTTP 200 sur `http://localhost:3001`.

Ces preuves valident le démarrage du socle et le chemin modèle-agent-sandbox.
Le premier administrateur et `openwebui/functions/idea_pipe.py` sont configurés.
L'étape 1 restera en cours jusqu'à la validation, depuis Open WebUI, d'un appel
Python avec résultat visible, puis de la production d'un fichier et d'une
figure téléchargeables.

## 2. Parcours de référence avant migration métier

Ces identifiants sont propres à la migration ; ils ne remplacent pas les UC
des anciennes spécifications. Préparer de petites fixtures contrôlées avec
résultats attendus calculés indépendamment de l'agent.

| ID | Parcours | Vérifications |
|---|---|---|
| BASE-01 | Charger un fichier et décrire son contenu | Colonnes, types, lignes et valeurs manquantes exacts |
| BASE-02 | Filtrer et calculer une agrégation | Valeur, dénominateur, unités et périmètre conformes à l'oracle |
| BASE-03 | Tracer puis modifier la figure au tour suivant | Données correctes, modification demandée, image visible et fichier accessible |
| BASE-04 | Passer entre deux tables puis élargir un filtre | Bonne table et retour aux données nécessaires, sans réutiliser un sous-ensemble incomplet |
| BASE-05 | Demande avec deux colonnes sémantiquement plausibles | Clarification avant un calcul dont le sens dépend du choix |
| BASE-06 | Interrompre un calcul puis poursuivre | Arrêt effectif et reprise cohérente sans duplication incontrôlée |
| BASE-07 | Perdre le noyau puis reprendre | Perte des variables reconnue, rechargement/recalcul depuis les fichiers disponibles, aucun résultat inventé |
| BASE-08 | Reprendre une conversation et ouvrir une autre | Checkpoint repris ; isolation des variables conforme au périmètre du noyau |

Le workspace upstream est partagé à l'échelle utilisateur ; le noyau est par
défaut scoped utilisateur/conversation/assistant. BASE-08 doit distinguer
partage des fichiers et isolation des variables, sans promettre une isolation
des fichiers par conversation qui n'existe pas dans ce socle.

## 3. Portage depuis l'archive

L'ordre métier précis reste à prioriser avec NeoLab. Candidats :

| Capacité | Éléments à examiner dans l'archive | Contrats à vérifier |
|---|---|---|
| Fichiers NeoLab | Documentation, jeux sample/abundance, tests | Grain, unités, clés SAMPLE_ID + ANALYSIS_ID |
| EcoTaxa | Clients/cache, exports et tests associés | Métadonnées versus objets, sélection exacte, confirmation, provenance |
| EcoPart | Client et jointure EcoTaxa/EcoPart | Correspondances, profondeurs, couverture et non-appariés |
| Amundsen | Client CTD et appariement | Temps/position/profondeur, statut de correspondance |
| Bio-ORACLE | Catalogue, client et enrichissement | Choix des variables/scénarios/couches/statistiques, conservation du grain |
| Autres besoins | OGSL, RAG, livrables, etc. | À sélectionner uniquement pour un use case prioritaire |

Consulter les anciennes spécifications et tests pour les règles métier, mais
vérifier leur validité et adapter leurs attentes au nouveau runtime. Éviter de
réintroduire l'ancien agent, SessionStore ou WorkingSet comme prérequis global.
Pour chaque capacité, documenter la représentation des données dans le nouveau
workspace, les références retournées, la provenance et la récupération après
redémarrage avant de choisir les composants à porter.

## Protocole de validation

Pour chaque scénario, consigner :

- ID, priorité confirmée, demande exacte et messages de suivi ;
- fichiers/versions/empreintes, périmètre distant éventuel, résultats attendus
  et tolérances justifiées ;
- commit, modèle, paramètres, runtime et état initial du noyau/conversation ;
- appels d'outils, code, résultats numériques, artefacts et observation UI ;
- réussite/échec par critère, erreurs, coût/latence si disponibles et limites.

Minimum initial proposé : trois exécutions en conversations neuves, puis un
parcours multi-tour pour chaque scénario. Rapporter le nombre de réussites sur
le nombre d'essais, jamais seulement le meilleur essai. Trois réussites ne
prouvent pas une fiabilité générale : elles constituent le seuil initial de
progression, à renforcer selon la criticité et les échecs observés.

Un use case est validé uniquement si les résultats et invariants attendus
sont satisfaits, le livrable est accessible dans l'interface et les suivis
requis réussissent. Une limite bloquante reste un échec ou un blocage explicite.
Les tests simulés ne remplacent pas les essais avec le modèle cible.

Les opérations métier critiques nécessitent des tests déterministes. Après un
changement, rejouer les tests concernés et les scénarios conversationnels déjà
validés qui pourraient être affectés. Ne pas changer simultanément modèle,
prompt, outils et contexte pour corriger un échec : isoler la cause et mesurer
l'effet de la correction.

## Journal de progression

| Date | Changement | Preuve / résultat | Prochaine action |
|---|---|---|---|
| 2026-09-11 | Archive NeoLab et clone Hawaii | Empreintes des modifications préservées ; clone au commit initial | Raccorder le modèle et démarrer |
| 2026-09-11 | Documentation de migration | README, AGENTS.md et présent plan ; aucun test runtime effectué | Identifier la configuration modèle et l'environnement cible |

Ajouter ici les références vers les comptes rendus d'essai expurgés des secrets.
Ne pas enregistrer de credentials, de données privées ni de liens publics vers
les traces sans autorisation.
