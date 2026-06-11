---
name: deliverable_writer
description: Guides the agent to compile a scientific PDF report from the current session — figures with titles, data sources, methods, limitations, and APA citations. Use when the user asks for a livrable, rapport, synthèse, or document scientifique.
---

# Deliverable writer

You are about to produce a structured scientific report from this session.

**Tone:** Write in formal, impersonal scientific register. No conversational filler, no hedging phrases ("il semble que", "on pourrait dire"), no meta-commentary about the assistant or the tool. The document must read as if written by a researcher — sober, precise, third-person where appropriate. Every sentence must carry factual content.

---

## Usage rule

- After loading this skill, compile the full document from the conversation history, then call `export_deliverable(content=..., filename=...)` in the same turn.
- Do NOT ask the user to provide the content — extract it yourself from the session.
- Write the document in the language of the conversation.

---

## Structure

Produce a markdown document with the following sections, in order:

```
# [Title — describe the scientific question in one line]

*Date : [today's date]*

## 1. Contexte scientifique

[What question was explored. What hypothesis. What data.]

## 2. Données et sources

[Table: Source | Description | N lignes | Téléchargement]
[List every query_ecotaxa / query_amundsen_ctd / query_bio_oracle / load_file call.]

## 3. Méthodes

[Summarize the analytical steps: joins performed, pandas operations, derived variables.]

## 4. Résultats

[For each figure produced in this session:]

### Figure N — [Descriptive title]

![Figure N — title](URL_of_graph)

**Source :** [data source used]
**Méthode :** [how it was computed]
**Interprétation :** [factual description only — no ecological interpretation]

[For each table result:]

### Tableau N — [Title]

[markdown table]

## 5. Limites

[List every limitation mentioned or implied:]
- Jointure temporelle ou spatiale non vérifiée
- Annotations non validées par un expert
- Couverture partielle (stations, périodes)
- Toute limite signalée par l'agent pendant la session

## 6. Références

[APA 7th edition. Use templates below for known sources.]
```

---

## APA citation templates

**EcoTaxa:**
> Picheral, M., Colin, S., & Irisson, J.-O. (2017). *EcoTaxa, a tool for the taxonomic classification of images*. SEANOE. https://doi.org/10.17882/55741

**Amundsen CTD (CIOOS):**
> Amundsen Science Data Collection. (2023). *CTD-Rosette vertical profiles* [Dataset]. Canadian Integrated Ocean Observing System (CIOOS). https://catalogue.cioos.ca/dataset/ca-cioos_ccin-12713

**Bio-ORACLE:**
> Assis, J., Fernández Bejarano, S. J., Salazar, V. W., et al. (2024). *Bio-ORACLE v3: pushing marine data layers to the turbulent ocean*. Global Ecology and Biogeography. https://doi.org/10.1111/geb.13813

**EcoPart:**
> Picheral, M., et al. (2022). *EcoPart: a tool for the analysis of particle size spectra*. SEANOE. https://doi.org/10.17882/84529

---

## Figure extraction rules

- Include EVERY figure produced via `run_graph` in this session.
- Use the graph URL exactly as it appeared in the assistant response (e.g. `http://localhost:8000/graphs/abc123.png`).
- Title must describe what the figure shows: species, variable, axis, period, zone.
- Never write "Figure 1 — graphique" — always be descriptive.

---

## Forbidden

- Do not invent data, citations, DOIs, or results not present in the session.
- Do not interpret results ecologically — describe only.
- Do not omit limitations.
- Do not call `export_deliverable` without a complete document.
