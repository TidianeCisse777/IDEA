# Skill: bio_oracle_query

You just called `query_bio_oracle` or `couple_zooplankton_bio_oracle`.
Bio-ORACLE data is now extracted or coupled in the session.

---

## Routing rule

- To see available datasets or variables, call `list_bio_oracle_datasets`.
- For a quick point preview, call `preview_bio_oracle_point`.
- To load, export, download or compare Bio-ORACLE scenarios, call `query_bio_oracle`.
- To couple zooplankton rows with Bio-ORACLE, call `couple_zooplankton_bio_oracle`.

---

## Key parameters

| Parameter | Role |
|---|---|
| `latitude` | Point latitude |
| `longitude` | Point longitude |
| `variable` | Requested Bio-ORACLE variable |
| `scenario` | SSP scenario or `baseline` |
| `depth_layer` | Layer chosen explicitly by the user |

---

## After loading

1. Include the download link returned by the tool in your response.
2. Present results as a comparison table, not as an ecological interpretation.
3. If the user did not provide `scenario` or `depth_layer`, ask for clarification.

---

## Limits

- Bio-ORACLE is an environmental source, not a taxonomic source.
- The depth layer must be chosen explicitly by the user.
- Interpretation belongs to the researcher — you can only provide data and comparisons.
