# Taxonomy Samples (2010–2025): Deployment/Net Context, Sample Lineage, and Linked Analyses

Source : classeur « project_IDEA_taxonomy_samplesanalyses-data__metadata-20260526.xlsx », feuille « taxonomy samples-metadata » (texte copié tel quel).

## Description

Inventory of Taxonomy samples with deployments dated between 2010 and 2025. For each sample, it combines: (1) deployment metadata (deployment ID, platform, station, start/end datetimes, gear/tow type/cast, bottom depth, coordinates, and deployment comments), (2) net sampling characteristics and volume estimates (mesh size, mouth aperture, min/max sample depths, depth-calculated and flowmeter-calculated filtered volumes, net comments, number of nets, and net lists/identifiers), (3) sample lineage fields (sample ID, net sampling IDs and subsampling quantities/unit plus sample comments), and (4) any linked analysis records when present (analysis ID/type/contract/datetime/protocol/comments via the left join to sample_analyses).

## Colonnes (feuille « taxonomy samples-metadata »)

**1. sampling_year** (is_computed : 1; type : int; domain_group : Deployment identification & timing; units_or_scale : year) : Calendar year extracted from deployment_date_start.

**2. deployment_id** (is_computed : 0; type : int; domain_group : Deployment identification; units_or_scale : NA) : Unique identifier of the deployment.

**3. sampling_platform** (is_computed : 0; type : varchar; domain_group : Sampling context; units_or_scale : NA) : Sampling platform name used for the deployment.

**4. station_name** (is_computed : 0; type : varchar; domain_group : Sampling context; units_or_scale : NA) : Station identifier/name for the deployment.

**5. deployment_datetime_start** (is_computed : 0; type : datetime; domain_group : Deployment identification & timing; units_or_scale : NA) : Datetime when the deployment started.

**6. deployment_datetime_end** (is_computed : 0; type : datetime; domain_group : Deployment identification & timing; units_or_scale : NA) : Datetime when the deployment ended.

**7. gear** (is_computed : 0; type : varchar; domain_group : Deployment identification & method; units_or_scale : NA) : Gear identifier/name used for the deployment.

**8. tow_type** (is_computed : 0; type : varchar; domain_group : Deployment identification & method; units_or_scale : NA) : Tow/deployment method category.

**9. cast_number** (is_computed : 0; type : int; domain_group : Deployment identification & timing; units_or_scale : NA) : Cast number/order for the gear at the station.

**10. bottom_depth** (is_computed : 0; type : int; domain_group : Deployment environment & geospatial; units_or_scale : m (depth)) : Bottom (seafloor) depth for the deployment.

**11. latitude** (is_computed : 0; type : decimal; domain_group : Deployment environment & geospatial; units_or_scale : decimal degrees) : Latitude in decimal degrees.

**12. longitude** (is_computed : 0; type : decimal; domain_group : Deployment environment & geospatial; units_or_scale : decimal degrees) : Longitude in decimal degrees.

**13. deployment_comments** (is_computed : 0; type : varchar; domain_group : Deployment notes; units_or_scale : NA) : Free-text comments about the deployment.

**14. net_mesh_size** (is_computed : 0; type : int; domain_group : Net sampling configuration; units_or_scale : um) : Net mesh size in micrometer (um).

**15. net_mouth_aperture** (is_computed : 0; type : decimal; domain_group : Net sampling configuration; units_or_scale : m2) : Net mouth aperture area.

**16. max_sample_depth** (is_computed : 0; type : decimal; domain_group : Net sampling configuration; units_or_scale : m (depth)) : Maximum (deepest) sample depth achieved during net sampling.

**17. min_sample_depth** (is_computed : 0; type : decimal; domain_group : Net sampling configuration; units_or_scale : m (depth)) : Minimum (shallowest) sample depth achieved during net sampling.

**18. depth_calc_net_filtered_vol** (is_computed : 0; type : decimal; domain_group : Volume metrics; units_or_scale : m3) : Net filtered/visited volume computed from depth-based method.

**19. flowmeter_calc_vol** (is_computed : 0; type : decimal; domain_group : Volume metrics; units_or_scale : m3) : Net filtered volume computed from flowmeter readings.

**20. NET_COMMENTS** (is_computed : 0; type : varchar; domain_group : Net sampling configuration; units_or_scale : NA) : Comments about the net sampling and/or net characteristics.

**21. number_of_nets** (is_computed : 0; type : bigint; domain_group : Net sampling inventory; units_or_scale : count) : Number of nets from which the sample originate from. Generally originate from a single net, but pooled net's sampling can occur

**22. sample_nets** (is_computed : 0; type : mediumtext; domain_group : Net sampling inventory; units_or_scale : NA) : list of nets identifiers involved in the sample (potentially aggregated identifiers).

**23. sample_id** (is_computed : 0; type : int; domain_group : Sample metadata; units_or_scale : NA) : Unique sample identifier.

**24. net_sampling_ids** (is_computed : 0; type : mediumtext; domain_group : Sample lineage; units_or_scale : NA) : List of net_sampling_ids (identifier of a net tow/sample within a deployment event) associated with the sample lineage.

**29. subsampling_quantity** (is_computed : 0; type : double; domain_group : Sample metadata; units_or_scale : NA) : Subsampling quantity for the sample in terms of original net sampling/catch.

**30. subsampling_unit** (is_computed : 0; type : varchar; domain_group : Sample metadata; units_or_scale : NA) : Unit associated with subsampling quantity.

**31. sample_comments** (is_computed : 0; type : varchar; domain_group : Sample metadata; units_or_scale : NA) : Comments/notes about the sample.

**32. analysis_id** (is_computed : 0; type : int; domain_group : Analysis metadata; units_or_scale : NA) : Analysis identifier from sample_analyses for this sample (NA if no analysis).

**33. analysis_type** (is_computed : 0; type : varchar; domain_group : Analysis metadata; units_or_scale : NA) : Type of analysis (NA if no analysis).

**34. analysis_contract** (is_computed : 0; type : varchar; domain_group : Analysis metadata; units_or_scale : NA) : Contract under which analysis performed (NA if no analysis).

**35. analysis_datetime** (is_computed : 0; type : datetime; domain_group : Analysis metadata; units_or_scale : NA) : Datetime when analysis started (NA if no analysis).

**36. analysis_protocol_id** (is_computed : 0; type : varchar; domain_group : Analysis metadata; units_or_scale : NA) : Protocol identifier for the analysis (NA if no analysis).

**37. analysis_comments** (is_computed : 0; type : text; domain_group : Analysis metadata; units_or_scale : NA) : Free-text comments about the analysis (NA if no analysis).
