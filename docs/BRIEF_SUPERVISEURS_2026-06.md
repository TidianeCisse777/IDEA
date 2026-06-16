---
title: "Assistant graphique copépodes — Brief d'avancement"
author: "Tidiane Cissé"
date: "2026-06-12"
public: "Superviseurs NeoLab — Université Laval"
lang: fr
---

# Assistant graphique copépodes — Brief d'avancement

| | |
|---|---|
| **Auteur** | Tidiane Cissé |
| **Public** | Superviseurs NeoLab |
| **Date** | 2026-06-12 |
| **Statut** | V1 fonctionnelle en local |

---

## 1. Architecture

```mermaid
flowchart TB
    subgraph U[Chercheur NeoLab]
        H[Conversation en langage naturel]
    end

    subgraph F[Frontend]
        OW[Open WebUI<br/>port 3000<br/>upload fichiers, chat, historique]
    end

    subgraph B[Backend agent]
        S[serve.py — FastAPI<br/>port 8000<br/>API OpenAI-compatible, SSE streaming]
        A[agent.py — LangGraph ReAct<br/>boucle Réflexion → Outil → Observation<br/>checkpoints SQLite]
    end

    subgraph T[Outils et savoirs]
        OR[OpenRouter<br/>proxy LLM multi-fournisseur<br/>GPT / Claude / Llama]
        TOOLS[23 outils Python<br/>chargement fichier, requêtes EcoTaxa/<br/>EcoPart/Amundsen/Bio-ORACLE,<br/>calculs pandas, graphiques matplotlib,<br/>workspace SQL lecture seule,<br/>livrables PDF]
        SKILLS[11 skills<br/>graph_planner, graph_writer,<br/>ecotaxa_query, deliverable_writer…<br/>chargés à la demande]
        RAG[Corpus RAG<br/>9 documents NeoLab<br/>colonnes, méthodes, taxonomie,<br/>jointures, biais arctiques]
    end

    subgraph D[Données et observabilité]
        DATA[(Données utilisateur<br/>EcoTaxa / EcoPart / Amundsen /<br/>Bio-ORACLE / fichiers labo)]
        SQLDB[(Bases SQL externes<br/>SQLite / PostgreSQL / MySQL / MariaDB<br/>lecture seule)]
        LS[LangSmith<br/>traces des conversations<br/>+ hub system prompt et skills]
        MEM[(PostgreSQL<br/>mémoire longue terme par utilisateur<br/>+ métadonnées sessions)]
    end

    H --> OW
    OW <--> S
    S <--> A
    A <--> OR
    A --> TOOLS
    A --> SKILLS
    A --> RAG
    TOOLS <--> DATA
    TOOLS -.DATABASE_URL<br/>read-only.-> SQLDB
    A --> LS
    A <--> MEM
    SKILLS -.versionnés.-> LS
```

---

## 2. Sources de données accessibles en ligne

```mermaid
flowchart TB
    subgraph TOP[" "]
        direction LR
        ET[EcoTaxa<br/>taxonomie annotée<br/>objets individuels<br/>morphométrie]
        EP[EcoPart<br/>profils UVP<br/>volumes échantillonnés<br/>CTD associée]
        AM[Amundsen Science<br/>CTD via ERDDAP<br/>T, S, O₂, fluorescence]
    end

    AG(((Agent copépodes)))

    subgraph BOTTOM[" "]
        direction LR
        BO[Bio-ORACLE<br/>variables marines<br/>actuelles et futures]
        OG[OGSL<br/>profils golfe<br/>Saint-Laurent]
        DB[(SQL externe<br/>SQLite / PostgreSQL<br/>MySQL / MariaDB<br/>lecture seule)]
    end

    ET <-->|list_ecotaxa_projects<br/>preview_ecotaxa_project<br/>query_ecotaxa<br/>+ MCP EcoTaxa en dev| AG
    EP <-->|list_ecopart_samples<br/>preview_ecopart_sample<br/>query_ecopart| AG
    AM <-->|list_amundsen_datasets<br/>preview_amundsen_profile<br/>query_amundsen_ctd| AG
    AG <-->|list_bio_oracle_datasets<br/>preview_bio_oracle_point<br/>query_bio_oracle| BO
    AG <-->|query_ogsl| OG
    AG <-->|list_sql_tables<br/>preview_sql_table<br/>copy_sql_query_to_workspace| DB

    style TOP fill:none,stroke:none
    style BOTTOM fill:none,stroke:none
    style AG fill:#e8f4fd,stroke:#2874a6,stroke-width:3px
```

---

## 3. Ce que l'agent sait faire, partiellement faire, ou ne fait pas

| Capacité | Statut | Détail |
|---|---|---|
| **Charger** un fichier local | ✅ fait | CSV, TSV, Excel, JSON, Parquet, exports UVP, fichiers labo — détection auto du format |
| **Analyser** une table chargée | ✅ fait | Inspection des colonnes, types, plages de valeurs, distributions |
| **Auditer** une table chargée | ✅ fait | Détection des valeurs manquantes, doublons, incohérences, lacunes temporelles ou spatiales |
| **Calculer** sur les données | ✅ fait | Filtrage, agrégations, jointures, variables dérivées via `run_pandas` sandboxé |
| **Calculer des métriques d'abondance** | ✅ fait | Densités (ind/m³), biomasses, indices par taxon, par station, par strate de profondeur — normalisation par volume échantillonné UVP |
| **Produire des graphiques** variés | ✅ fait | Distribution verticale, spatio-temporel, taxonomie, profils CTD, variables dérivées — palette d'incertitude appliquée |
| **Cartes géographiques** | ✅ fait | Stations échantillonnées, abondances spatiales, cartes de lacunes — projections adaptées aux hautes latitudes |
| **Connaissance des lieux et mers arctiques** | ✅ fait | Toponymie de la mer de Beaufort, baie de Baffin, détroits canadiens, mer du Labrador, golfe du Saint-Laurent ; biais arctiques documentés dans le RAG NeoLab |
| **Lister les projets EcoTaxa** disponibles | ✅ fait | `list_ecotaxa_projects` puis preview et export ciblé d'un projet donné |
| **Lister les échantillons EcoPart** disponibles | ✅ fait | `list_ecopart_samples` puis preview et export d'un échantillon UVP donné |
| **Récupérer les données Bio-ORACLE** selon scénario | ✅ fait | Variables marines actuelles **et futures** (scénarios climatiques SSP), sélection par zone et profondeur |
| **Récupérer les données OGSL** à des endroits précis | ✅ fait | Profils CTD du golfe du Saint-Laurent, recherche par station / fenêtre temporelle / profondeur, enrichissement d'une table existante |
| **Récupérer les CTD Amundsen Science** | ✅ fait | Accès ERDDAP : température, salinité, O₂, fluorescence par campagne et station |
| **Jointures biologique ↔ environnemental** | ✅ fait | `join_ecotaxa_ecopart`, `couple_zooplankton_bio_oracle` |
| **Brancher une base SQL externe** (lecture seule) | ✅ fait | SQLite, PostgreSQL, MySQL, MariaDB — découverte tables/PK/FK, preview filtré, copie TSV |
| **Livrables PDF** avec citations vérifiées | ✅ fait | `export_deliverable` via WeasyPrint |
| **Rapport de synthèse de la session** | ✅ fait | Récapitulatif des données chargées, calculs effectués, graphiques produits et sources mobilisées, exportable en PDF |
| **Recherche dans le corpus métier** (9 documents NeoLab) | ✅ fait | `query_copepod_knowledge_base` (ChromaDB) |
| **Mémoire courte terme** (reprise après redémarrage) | ✅ fait | Checkpoints SQLite par conversation |
| **Mémoire longue terme** entre conversations | ✅ fait | LangMem + PostgreSQL, isolée par utilisateur |
| Gestion entière du contexte conversationnel | 🟡 partiel | Mémoire courte + longue terme en place, mais pas de gestion fine du contexte sur les sessions très longues (compression, résumé automatique, oubli sélectif) |
| Validation bout-en-bout des use cases | 🟡 partiel | Les 23 tools sont implémentés et chacun a été testé individuellement (42 tests unitaires verts), mais plusieurs use cases complets (de la question initiale au livrable final) n'ont pas encore été éprouvés en profondeur |
| Graphiques interactifs (HTML/Plotly) | 🟡 partiel | Sortie PNG uniquement aujourd'hui — reporté V2 |
| Exploration libre du catalogue EcoTaxa depuis l'agent | ❌ pas fait | L'agent interroge un projet une fois son ID connu, mais ne propose pas encore de parcours interactif du catalogue (filtrage par campagne, région, taxon, période) |
| Génération de code en R | ❌ pas fait | Python/matplotlib uniquement — reporté V2 |
| Multi-utilisateurs (sessions isolées, authentification, quotas par chercheur) | ❌ pas fait | Aujourd'hui un seul chercheur à la fois sur la machine de dev |
| Déploiement sur serveur ULaval | ❌ pas fait | Prochaine étape — voir besoins IT |
| Indépendance vis-à-vis de l'API OpenAI | ❌ pas fait | L'agent dépend encore d'OpenAI via OpenRouter ; pas de modèle hébergé en local — bascule envisageable après les tests utilisateurs |

---

## 4. Déploiement

```mermaid
flowchart LR
    subgraph READY[✅ Prêt — conteneurisé Docker Compose]
        direction TB
        OW[Open WebUI]
        AG[Agent FastAPI]
        PG[(PostgreSQL)]
        CH[(ChromaDB RAG)]
        OW --- AG
        AG --- PG
        AG --- CH
    end

    subgraph MISSING[❌ Manquant côté ULaval]
        direction TB
        SRV[Serveur Linux<br/>4 vCPU · 16 Go RAM · 100 Go SSD<br/>Internet sortant HTTPS]
        DNS[Nom de domaine<br/>ex. copepodes.ulaval.ca<br/>+ certificat TLS]
    end

    READY -->|docker compose up| SRV
    SRV --- DNS

    style READY fill:#d5f5e3,stroke:#27ae60,stroke-width:2px
    style MISSING fill:#fadbd8,stroke:#c0392b,stroke-width:2px,stroke-dasharray: 5 5
```
