# Skill: amundsen_ctd_query

You just called `query_amundsen_ctd`.
The Amundsen vertical CTD profile is now loaded or exported in the session.

---

## Routing rule

- To see available datasets, call `list_amundsen_datasets`.
- For a quick profile preview, call `preview_amundsen_profile`.
- To load, export, download or analyse the full vertical profile, call `query_amundsen_ctd`.

---

## What Amundsen CTD contains

- `amundsen12713` is the main vertical CTD dataset.
- Raw columns must remain unchanged.
- Join aliases added to the output are helpers for joining with zooplankton data — do not replace the original columns with them.

---

## After loading

1. Include the download link returned by the tool in your response.
2. Use depth, station, cast and time columns as join keys.
3. Do not interpret the profiles biologically — provide data and comparisons only.

---

## Limits

- The profile must stay raw and traceable.
- Aliases are helpers, not a substitute for the original columns.
