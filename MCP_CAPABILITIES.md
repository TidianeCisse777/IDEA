# MCP EcoTaxa Capabilities

MCP EcoTaxa is the assistant's read-only exploration layer for EcoTaxa. This
layer is in development.

Its purpose is simple: explore before exporting. It helps the assistant find
which EcoTaxa projects are accessible, where and when samples exist, which taxa
are attested, which columns are available, and whether projects can be combined.

It does not modify EcoTaxa.

Current status: useful for project/sample discovery and schema checks, but the
agent routing around EcoTaxa exploration and sample export is still being
tested.

## What It Can Do

### Explore Accessible Projects

Example requests:

- "Which EcoTaxa projects are accessible?"
- "Find accessible UVP6 projects."
- "Search EcoTaxa projects related to Amundsen."
- "Preview project 14622."

Supported operations:

- search projects by title or instrument
- retrieve project metadata
- list projects visible to the configured EcoTaxa account

Access depends on the configured EcoTaxa credentials.

### Search by Region and Time

MCP EcoTaxa uses a local sample cache indexed by project, latitude, longitude,
date, and instrument.

Example requests:

- "Which EcoTaxa projects cover Baffin Bay in 2024?"
- "Which samples exist above 75N between 2015 and 2024?"
- "Which accessible projects cover Baffin Bay between 2015 and 2024?"

Typical flow:

```text
named region
-> get_zone_info
-> find_ecotaxa_projects_in_region
```

### Find Taxon Observations

Example requests:

- "Where is Calanus glacialis found in accessible EcoTaxa projects?"
- "Where is validated Calanus glacialis in Baffin Bay between 2015 and 2024?"
- "Is Calanus finmarchicus present in project 42?"
- "How many validated Calanus finmarchicus records are in project 42?"

Supported operations:

- find observations by taxon
- filter by region, date range, and instrument when available
- count V/P/D status by project
- resolve taxonomic names

V1 limitation: observation search is project-filtered. It finds samples from
projects where the taxon is attested. For precise counts, follow with taxon
count tools.

### Inspect Project Schema

Before exporting a large project, MCP can check whether required fields exist.

Example requests:

- "Before exporting project 14622, check latitude, longitude, date, depth, and validated taxon."
- "What columns are available in project 42?"
- "Is there a depth column?"
- "Are there useful morphometric fields?"

Schema levels:

- `sample`: deployment, station, date, latitude/longitude, sample free fields
- `acquisition`: instrument acquisition metadata
- `object`: object/image, classification, morphometry, depth when available

### Inspect Column Distributions

Example requests:

- "What is the depth range in project 42?"
- "What values occur in classif_qual?"
- "Inspect orig_id in project 42."
- "What is the distribution of area?"

Output can include:

- numeric min, max, mean, median, quartiles, count
- frequent text values
- distinct counts
- ambiguity errors when the same column name exists at multiple levels

### Compare Projects Before Combining

Example requests:

- "Compare projects 14844, 14853, 14859, and 17498 before a combined export."
- "Which columns are common across these projects?"
- "Are there blocking type conflicts?"

The comparison reports:

- common columns
- project-specific columns
- type conflicts
- level conflicts
- conflict severity

### Navigate the EcoTaxa Catalogue

MCP exposes project -> sample -> acquisition -> object navigation.

Example requests:

- "List samples from project 42."
- "Show metadata for sample 42000002."
- "List acquisitions for project 42."
- "List a few objects from this sample."
- "Give the full context for this object."

## What It Does Not Do

MCP EcoTaxa V1 does not:

- export full TSV/CSV object tables
- download EcoTaxa images or vault content
- annotate or modify projects
- classify objects
- calculate final abundance or biomass
- support EcoPart
- manage separate user-level EcoTaxa permissions beyond the configured account

For full object export, the assistant still uses:

```text
query_ecotaxa(project_id=..., taxon=..., status="V")
query_ecotaxa(project_id=..., sample_ids=[...], status="V")
query_ecotaxa_sample(sample_id=..., status="V")
```

Use MCP tools for exploration. Use `query_ecotaxa` only when the user explicitly
asks to load, export, download, or retrieve full data.
