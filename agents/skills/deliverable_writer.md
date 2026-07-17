---
name: deliverable_writer
version: 1.0.0
triggers:
  - User explicitly requests a report, scientific synthesis, or deliverable
forbidden_when:
  - User requests only an inline answer, table, or graph
requires:
  - "intent:deliverable"
next_tool: export_deliverable
max_tokens: 2000
description: Guides the agent to compile a scientific PDF report from the current session — figures with titles, data sources, methods, limitations, and APA citations. Use when the user asks for a livrable, rapport, synthèse, or document scientifique.
---

# Deliverable writer

You are about to produce a structured scientific report from this session.

**Tone:** Write in formal, impersonal scientific register. No conversational filler, no hedging phrases ("il semble que", "on pourrait dire"), no meta-commentary about the assistant or the tool. The document must read as if written by a researcher — sober, precise, third-person where appropriate. Every sentence must carry factual content.

---

## Usage rule

- After loading this skill, compile the full document and a `traceability_manifest` from the conversation history, then call `export_deliverable(content=..., filename=..., traceability_manifest=...)` in the same turn.
- Do NOT ask the user to provide the content — extract it yourself from the session.
- Write the document in the language of the conversation.
- The manifest is the source of truth. Include only facts visible in user messages,
  assistant messages, or tool results from the current conversation.
- Never add a source because a citation template exists below. A source and its
  citation are allowed only when that source was actually used in the session.

## Traceability manifest

Pass a dictionary with two lists:

```json
{
  "study_context": {
    "objective": "Scientific or analytical objective",
    "geographic_scope": "Exact zone, or 'Non applicable' when no geographic scope exists",
    "temporal_scope": "Exact period, or 'Non applicable' when no temporal scope exists",
    "taxonomic_scope": "Taxon or identification scope",
    "projects": ["Project identifiers actually used"],
    "samples": ["Sample identifiers actually retained"],
    "selection_criteria": "How projects, samples, dates, zones, and taxa were selected"
  },
  "sources": [
    {
      "name": "EcoTaxa — projet 17498",
      "url": "https://ecotaxa.obs-vlfr.fr/prj/17498",
      "citation": "APA citation for the source actually used"
    }
  ],
  "operations": [
    {
      "category": "exploration | export | enrichissement | analyse | graphique",
      "title": "Descriptive operation title",
      "status": "réussie | partielle | échouée | annulée | non confirmée",
      "source": "Exact source or session table",
      "input": "Input dataset/table and scope",
      "parameters": "Filters, variables, join keys, calculation",
      "result": "Observed result, including an error or zero match",
      "coverage": "Matched/total count when available",
      "limitations": "Limit explicitly observed during this operation"
    }
  ]
}
```

- Every `study_context` text field is required. Use `Non applicable` only when
  the dimension genuinely does not apply; never use it to hide missing context.
- Copy the geographic and temporal scope from the user's request and verified
  tool results. Never infer a zone or period from memory.
- List the exact project and sample identifiers retained by the workflow. Empty
  lists are allowed only when no project/sample was selected.
- Record every exploration, export, enrichment, analysis, and graph in chronological order.
- Keep failed, partial, cancelled, and unconfirmed operations. Never report only successes.
- For enrichment, always record coverage when the session provides it, including zero matches.
- Use descriptive user-facing operation titles; do not expose internal tool names.
- Every URL written in the References section must occur in `sources`. The exporter
  rebuilds the final bibliography exclusively from this list and rejects undeclared URLs.
- **DOIs.** Never invent a DOI, and never add one for a source you did not actually
  use. When an APA template below carries a DOI, that same DOI is allowed ONLY if
  the full citation (DOI included) is copied verbatim into that source's `citation`
  field — or the DOI is set in a `doi` field on the source. A DOI that is not
  attached to a declared, used source is an irrelevant link and will be rejected.

---

## Structure

Produce a markdown document with the following sections, in order:

```
# [Title — describe the scientific question in one line]

*Date : [today's date]*

## Cadre de l'étude

[Automatically inserted from `study_context`: objective, geographic scope,
temporal scope, taxonomic scope, projects, samples, and selection criteria.]

## 1. Contexte scientifique

[What question was explored. What hypothesis. What data.]

## 2. Données et sources

[Table: Source | Description | N lignes | Téléchargement]
[List every data search or file load performed, using user-facing source names.]

## 3. Méthodes

[Detailed chronological account of exports, enrichments, joins, filters,
calculations, and derived variables. State the input, parameters, result,
coverage, status, and limitation of each step.]

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

[List every limitation observed or explicitly mentioned:]
- Jointure temporelle ou spatiale non vérifiée
- Annotations non validées par un expert
- Couverture partielle (stations, périodes)
- Toute limite signalée par l'agent pendant la session

## 6. Références

[APA 7th edition. Use templates below for known sources.]
```

---

## Conditional APA citation templates

These templates are lookup aids, not a default bibliography. Use a template only
when its corresponding source appears in the current conversation and in
`traceability_manifest.sources`.

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
