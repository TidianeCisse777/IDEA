# SEQUENCES.md — Diagrammes de séquence · IDEA

> Flux détaillés d'un message utilisateur jusqu'au résultat, par use case.
> Contexte : [`ARCHITECTURE.md`](ARCHITECTURE.md) (composants), [`SPEC.md`](SPEC.md)
> (use cases UC-*), [`PARTAGE.md`](PARTAGE.md) (déploiement).

Acteurs communs :
- **U** : Utilisateur (Open WebUI)
- **OW** : Open WebUI (:3000)
- **API** : `serve.py` FastAPI (:8000)
- **AG** : `agent.py` LangGraph ReAct
- **LLM** : API LLM
- **T** : Tools Python
- **MCP** : cache EcoTaxa
- **EXT** : sources externes (EcoTaxa/EcoPart/ERDDAP)

---

## S0 · Flux transport générique (tout message)

```mermaid
sequenceDiagram
    actor U
    participant OW
    participant API as serve.py :8000
    participant AG as agent.py (ReAct)
    participant LLM

    U->>OW: message (+ upload éventuel)
    OW->>API: POST /v1/chat/completions (stream=true)
    API->>AG: invoke(thread_id, messages)
    Note over AG: pre_model_hook<br/>truncate + trim + memory
    loop Boucle ReAct
        AG->>LLM: prompt système + historique + tools
        LLM-->>AG: réponse ou tool_call
        alt tool_call
            AG->>AG: exécute le tool (voir S1..S8)
            AG-->>LLM: observation
        end
    end
    AG-->>API: réponse finale (+ liens graphes/downloads)
    API-->>OW: SSE (tokens + progression)
    OW-->>U: réponse rendue
```

Toutes les séquences suivantes se déroulent **à l'intérieur de la boucle ReAct**
de S0. Seuls les appels de tools spécifiques sont montrés.

---

## S1 · UC-A/B · Charger un fichier et tracer un graphique

```mermaid
sequenceDiagram
    participant AG as agent.py
    participant LLM
    participant T as Tools
    participant API as serve.py

    Note over AG,LLM: « charge ce TSV et trace le profil vertical »
    AG->>T: load_file(path)
    T-->>AG: colonnes, types, (hint UVP éventuel)
    Note over AG: I2 — séquence graphique obligatoire
    AG->>T: load_skill("graph_planner")
    T-->>AG: règles de planification
    AG->>T: load_skill("graph_writer")
    T-->>AG: template matplotlib
    alt planner = visual
        AG->>T: run_graph(code matplotlib)
        T->>API: héberge PNG → /graphs/{file}
        T-->>AG: markdown image + URL
    else planner = table
        AG->>T: run_pandas(code)
        T-->>AG: table markdown
    end
    Note over AG: réponse = image (I10 stamp confiance)<br/>ou tableau, 1 phrase neutre max
```

---

## S2 · UC-C · Question de savoir (RAG) et taxonomie

```mermaid
sequenceDiagram
    participant AG as agent.py
    participant T as Tools

    Note over AG: I3 — verbe de savoir (« qu'est-ce que », « explique »)
    alt Question de définition/méthode/géographie
        AG->>T: query_copepod_knowledge_base(question)
        T-->>AG: passages RAG (ChromaDB)
        Note over AG: si vide → « pas trouvé dans la base »
    else Question sur un taxon (nom, AphiaID, statut)
        AG->>T: lookup_marine_taxonomy(nom)
        Note over T: RAG local → WoRMS → Wikipedia (fallback)
        T-->>AG: rang, AphiaID, statut, source verbatim
    end
    Note over AG: réponse fondée sur la source, jamais de mémoire
```

---

## S3 · UC-D · Exploration EcoTaxa par zone + période (read-only)

```mermaid
sequenceDiagram
    participant AG as agent.py
    participant T as Tools
    participant MCP as cache EcoTaxa

    Note over AG: « samples EcoTaxa en Baie de Baffin 2024 »
    AG->>T: load_skill("ecotaxa_navigation")
    T-->>AG: routage read-only
    AG->>T: get_zone_info("Baie de Baffin")
    T-->>AG: bbox + polygone IHO/NeoLab
    AG->>T: find_ecotaxa_samples_in_region(bbox, date_range)
    T->>MCP: lecture cache read-only
    alt cache prêt
        MCP-->>T: samples (sample_id, project_id, lat/lon, dates)
    else CACHE_EMPTY
        MCP-->>T: CACHE_EMPTY
        Note over AG: informer l'utilisateur : resync MCP requis<br/>(l'agent ne peut pas le déclencher)
    end
    T-->>AG: table + Sources: ecotaxa.obs-vlfr.fr/prj/{id} (I5)
```

---

## S4 · UC-E · Export EcoTaxa (opération confirmée)

```mermaid
sequenceDiagram
    actor U
    participant AG as agent.py
    participant T as Tools
    participant EXT as EcoTaxa

    Note over AG: « exporte le projet 14853 »
    Note over AG,U: I6 / CT-AG-06 — confirmation obligatoire
    AG-->>U: « Export du projet 14853, ~N objets. Confirme ? »
    U->>AG: « oui / go / lance »
    AG->>T: query_ecotaxa(project_id=14853, [sample_ids], [filters])
    T->>EXT: création tâche d'export serveur
    alt succès
        EXT-->>T: données objets
        T-->>AG: df_ecotaxa en session + lien download
        AG->>T: load_skill("ecotaxa_query")
        T-->>AG: guides d'interprétation
    else EXPORT_FAILED (droits manquants)
        EXT-->>T: EXPORT_FAILED + message serveur
        Note over AG: citer le message verbatim,<br/>proposer preview/list — pas de fallback silencieux
    end
```

---

## S5 · UC-F · Join EcoTaxa ↔ EcoPart

```mermaid
sequenceDiagram
    actor U
    participant AG as agent.py
    participant T as Tools
    participant EXT as EcoPart

    alt Workflow 1 — les deux df en session
        Note over AG: df_ecotaxa ET df_ecopart chargés
        AG->>T: join_ecotaxa_ecopart()
        Note over T: join (sample_id, depth_bin 5m)<br/>préfixe ecopart_*, stocke df_ecotaxa_ecopart
        T-->>AG: table jointe + couverture de match
    else Workflow 2/3 — EcoPart absent (fetch distant, confirmé)
        AG-->>U: « Enrichir EcoTaxa avec EcoPart ? » (CT-AG-06)
        U->>AG: « oui »
        AG->>T: enrich_ecotaxa_with_ecopart_remote()
        T->>EXT: recherche bbox + export EcoPart
        EXT-->>T: profils EcoPart
        T-->>AG: table enrichie + df_ecotaxa_ecopart
    end
    Note over AG: I — REQUIS : reporter la couverture de match ;<br/>avertir si 0/faible (campagne ≠ ou hors plage de profondeur)
```

---

## S6 · UC-G · Enrichissement environnemental (Amundsen / OGSL / Bio-ORACLE)

```mermaid
sequenceDiagram
    participant AG as agent.py
    participant T as Tools
    participant EXT as ERDDAP

    Note over AG: « enrichis ce fichier avec Amundsen CTD » (lat/lon/temps)
    alt Enrichissement scopé zone/date
        AG->>T: enrich_with_amundsen_ctd(zone_name, date_range)
        Note over T: filtre interne déterministe (1 seul appel)
    else Enrichissement direct
        AG->>T: enrich_with_amundsen_ctd()
    end
    Note over T: auto-détecte lat/lon/temps/depth,<br/>dédup points, batch ERDDAP par mois + grille 5°
    T->>EXT: requêtes bbox+time+PRES
    EXT-->>T: profils CTD
    T-->>AG: colonnes amundsen_* + amundsen_match_status
    Note over AG: chaînage → passer source_variable =<br/>variable exacte de l'étape précédente
```

Même patron pour `enrich_with_ogsl` (OGSL ISMER) et `enrich_with_bio_oracle`
(variables actuelles + scénarios SSP ; > 10 lignes multi-var → confirmation).

---

## S7 · UC-H · Workspace SQL read-only

```mermaid
sequenceDiagram
    participant AG as agent.py
    participant T as Tools
    participant DB as SQL (read-only)

    Note over AG: « joins les tables stations et casts »
    AG->>T: list_sql_tables()
    T->>DB: introspection (tables, PK/FK, cardinalité)
    DB-->>T: schémas
    T-->>AG: overview
    opt schéma incertain
        AG->>T: preview_sql_table(table)
        T->>DB: SELECT ... LIMIT (read-only)
        DB-->>T: échantillon
    end
    AG->>T: copy_sql_query_to_workspace(SELECT ... JOIN ... LIMIT N)
    Note over T: LIMIT obligatoire + row cap
    T->>DB: exécution read-only
    DB-->>T: résultat
    T-->>AG: TSV en workspace (analysable comme un fichier)
```

---

## S8 · UC-J · Livrable PDF

```mermaid
sequenceDiagram
    actor U
    participant AG as agent.py
    participant T as Tools
    participant API as serve.py

    Note over AG: « fais un rapport PDF de cette session »
    AG->>T: load_skill("deliverable_writer")
    T-->>AG: structure + templates de citation
    Note over AG: compile le markdown depuis l'historique de session
    Note over AG,U: I6 / CT-AG-06 — export_deliverable = confirmé
    AG->>T: export_deliverable(content, filename)
    Note over T: WeasyPrint → PDF (fallback HTML si libs natives absentes)
    T->>API: héberge → /downloads/{file}
    T-->>AG: lien de téléchargement
    AG-->>U: lien PDF (sources + méthodes + limites inclus)
```

---

## S9 · Cycle de mise à jour continue (déploiement)

```mermaid
sequenceDiagram
    actor Dev
    participant GH as GitHub main
    participant GHA as GitHub Actions
    participant GHCR as ghcr.io
    participant WT as Watchtower
    participant VM as VM prod
    actor Test as Testeurs

    Dev->>GH: push
    GH->>GHA: déclenche build
    GHA->>GHCR: push image multi-arch (amd64/arm64)
    loop poll 5 min
        WT->>GHCR: check digest
    end
    GHCR-->>WT: nouveau digest
    WT->>VM: pull + restart copepod-agent / mcp-ecotaxa
    Note over VM: postgres + open-webui NON auto-updatés
    Test->>VM: rafraîchit https://$PROD_DOMAIN
```
