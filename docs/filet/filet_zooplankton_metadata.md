# Zooplankton Abundance Normalized by Depth- and Flowmeter-Calculated Volumes (2010–2025)

Source : classeur « project_IDEA_taxonomy_samplesanalyses-data__metadata-20260526.xlsx », feuille « zooplankton abundances-metadata » (texte copié tel quel).

## Description

Taxonomic-abundance summary for zooplankton net samples analyzed between 2010 and 2025 (excluding analyses under the contracts 'KEBABB' and 'DFO-D. Côté'). Each output row corresponds to one analysis/taxon combination further split by life-development stage and size category, and is annotated with the sampling context (sample ID, station, deployment date/time, cast, gear/tow type, net mesh, net identifier(s), and min/max sampled depths) plus taxonomic classification (kingdom to family). For each row, it computes and reports taxon abundances normalized by: (1) depth-calculated filtered volume for vertically towed net sampling (V-Tow) when sampling depth boundaries are available, (2) flowmeter-calculated filtered volume for both vertically and oblique towed net sampling (V-Tow and O-Tow) when flowmeter measurements are available, separately for the “Large Fraction ($> 1\text{ mm}$)” and “Small Fraction ($< 1\text{ mm}$)” fractions and as their totals, alongside the underlying volume estimates (DEPTH_CALC_VOL and FLOWMETER_CALC_VOL).

## Colonnes (feuille « zooplankton abundances-metadata »)

**1. SAMPLE_ID** (is_aggregated : 0; is_computed : 0; type : int; domain_group : Sample metadata; units_or_scale : NA) : Unique identifier of the sample.

**2. ANALYSIS_ID** (is_aggregated : 0; is_computed : 0; type : int; domain_group : Analysis metadata; units_or_scale : NA) : Unique identifier of the analysis record for the sample.

**3. ANALYSIS_CONTRACT** (is_aggregated : 0; is_computed : 0; type : varchar; domain_group : Analysis metadata; units_or_scale : NA) : Contract name under which the analysis was performed (filtered to exclude KEBABB and DFO-D. Côté).

**4. STATION_NAME** (is_aggregated : 0; is_computed : 0; type : varchar; domain_group : Sampling context; units_or_scale : NA) : Station identifier/name for the deployment.

**5. DEPLOYMENT_DATE_START** (is_aggregated : 0; is_computed : 0; type : date; domain_group : Deployment identification & timing; units_or_scale : NA) : Deployment start date (filtered to years 2010–2025 inclusive).

**6. DEPLOYMENT_TIME_START** (is_aggregated : 0; is_computed : 0; type : time; domain_group : Deployment identification & timing; units_or_scale : NA) : Deployment start time.

**7. CAST_NUMBER** (is_aggregated : 0; is_computed : 0; type : varchar; domain_group : Deployment identification & timing; units_or_scale : NA) : Cast number/order for the gear at the station.

**8. GEAR** (is_aggregated : 0; is_computed : 0; type : varchar; domain_group : Deployment identification & method; units_or_scale : NA) : Gear identifier/name used for the deployment.

**9. TOW_TYPE** (is_aggregated : 0; is_computed : 0; type : varchar; domain_group : Deployment identification & method; units_or_scale : NA) : Tow/deployment method category.

**10. NET_MESH_SIZE** (is_aggregated : 0; is_computed : 0; type : int; domain_group : Net sampling configuration; units_or_scale : um) : Net mesh size in micrometer (um).

**11. SAMPLING_NET_ID** (is_aggregated : 0; is_computed : 1; type : longtext; domain_group : Net sampling configuration; units_or_scale : NA) : Represents the net(s) associated with the sample; sometimes an aggregated inventory/list rather than a single net_sampling_id.

**12. MIN_SAMPLE_DEPTH** (is_aggregated : 0; is_computed : 0; type : decimal; domain_group : Net sampling configuration; units_or_scale : m (depth)) : Minimum (shallowest) sampling depth for the net sampling.

**13. MAX_SAMPLE_DEPTH** (is_aggregated : 0; is_computed : 0; type : decimal; domain_group : Net sampling configuration; units_or_scale : m (depth)) : Maximum (deepest) sampling depth for the net sampling.

**14. ZOOPLANKTON_CATEGORY** (is_aggregated : 0; is_computed : 0; type : varchar; domain_group : Taxonomy; units_or_scale : NA) : Zooplankton category (copepod, non-copepod, fish, egg-like).

**15. TAXON_ID** (is_aggregated : 0; is_computed : 0; type : varchar; domain_group : Taxonomy; units_or_scale : NA) : Taxonomic reference identifier for the counted/derived organism.

**16. KINGDOM** (is_aggregated : 0; is_computed : 0; type : varchar; domain_group : Taxonomy; units_or_scale : NA) : Taxonomic kingdom.

**17. PHYLUM** (is_aggregated : 0; is_computed : 0; type : varchar; domain_group : Taxonomy; units_or_scale : NA) : Taxonomic phylum.

**18. CLASS** (is_aggregated : 0; is_computed : 0; type : varchar; domain_group : Taxonomy; units_or_scale : NA) : Taxonomic class.

**19. ORDER** (is_aggregated : 0; is_computed : 0; type : varchar; domain_group : Taxonomy; units_or_scale : NA) : Taxonomic order.

**20. FAMILY** (is_aggregated : 0; is_computed : 0; type : varchar; domain_group : Taxonomy; units_or_scale : NA) : Taxonomic family.

**21. TAXON_LIFE_DEVELOPMENT_STAGE** (is_aggregated : 0; is_computed : 0; type : varchar; domain_group : Taxonomy; units_or_scale : NA) : Life development stage descriptor (e.g., copepodid/nauplius stages, adult sex classes, etc., depending on naming conventions).

**22. TAXON_SIZE_CATEGORY** (is_aggregated : 0; is_computed : 0; type : varchar; domain_group : Taxonomy; units_or_scale : NA) : Optional size category for the taxon (may be NULL/blank depending on records).

**23. Large Fract (ind./m3 depth vol)** (is_aggregated : 1; is_computed : 1; type : double; domain_group : Abundance & volume metrics; units_or_scale : ind./m3 (depth-calculated volume)) : Sum of depth-volume-normalized abundance for taxon restricted to fraction type 'Large Fraction (>1mm)' within the GROUP BY grain (analysis_id + taxon + stage + size_category).

**24. Small Fract (ind./m3 depth vol)** (is_aggregated : 1; is_computed : 1; type : double; domain_group : Abundance & volume metrics; units_or_scale : ind./m3 (depth-calculated volume)) : Sum of depth-volume-normalized abundance for taxon restricted to fraction type 'Small Fraction (<1mm)' within the GROUP BY grain (analysis_id + taxon + stage + size_category).

**25. Total abundance (ind./m3 depth vol)** (is_aggregated : 1; is_computed : 1; type : double; domain_group : Abundance & volume metrics; units_or_scale : ind./m3 (depth-calculated volume)) : Total depth-volume-normalized abundance across the two targeted fraction types (large + small) for the grouped taxon/stage/size in the analysis.

**26. DEPTH_CALC_VOL** (is_aggregated : 0; is_computed : 1; type : decimal; domain_group : Abundance & volume metrics; units_or_scale : m3) : Depth-based estimate of net filtered/visited volume.

**27. Large Fract (ind./m3 flowmeter vol)** (is_aggregated : 1; is_computed : 1; type : double; domain_group : Abundance & volume metrics; units_or_scale : ind./m3 (flowmeter-calculated volume)) : Sum of flowmeter-volume-normalized abundance for taxon restricted to 'Large Fraction (>1mm)' within the GROUP BY grain (analysis_id + taxon + stage + size_category).

**28. Small Fract (ind./m3 flowmeter vol)** (is_aggregated : 1; is_computed : 1; type : double; domain_group : Abundance & volume metrics; units_or_scale : ind./m3 (flowmeter-calculated volume)) : Sum of flowmeter-volume-normalized abundance for taxon restricted to 'Small Fraction (<1mm)' within the GROUP BY grain (analysis_id + taxon + stage + size_category).

**29. Total abundance (ind./m3 flowmeter vol)** (is_aggregated : 1; is_computed : 1; type : double; domain_group : Abundance & volume metrics; units_or_scale : ind./m3 (flowmeter-calculated volume)) : Total flowmeter-volume-normalized abundance across targeted fraction types (large + small) for the grouped taxon/stage/size in the analysis.

**30. FLOWMETER_CALC_VOL** (is_aggregated : 0; is_computed : 0; type : decimal; domain_group : Abundance & volume metrics; units_or_scale : m3) : Flowmeter-based estimate of filtered volume.
