# Copepod Abundance and Biomass by Taxon and copepodid/nauplius stage (2010–2025)

Source : classeur « project_IDEA_taxonomy_samplesanalyses-data__metadata-20260526.xlsx », feuille « copepod abund&biomass-metadata » (texte copié tel quel).

## Description

Copepod Abundance and Biomass per-analysis, per-taxon dataset for net samplings collected between 2010 and 2025 (excluding analyses under contracts 'KEBABB' and 'DFO-D. Côté'). It combines sampling/deployment context (sample ID, station, deployment date/time, cast, gear/tow type, net mesh, net identifier(s), and min/max sampling depths) with copepod/nauplius stage metrics. For each taxon, it reports depth- and flowmeter-based filtered volumes and taxonomic classification (kingdom to family when available), then provides abundance (counts and ind./m3) and biomass (µg C/m3) broken out by copepodid stages C1–C5, adult male (M) and female (F), unspecified copepod stage (COP_NS), aggregated copepodids, nauplius stages N1–N6, unspecified nauplius stage (NAUP_NS), aggregated nauplii, and all-stages totals. Results are ordered by deployment date/time, net identifier(s), and taxon.

## Colonnes (feuille « copepod abund&biomass-metadata »)

**1. SAMPLE_ID** (is_computed : 0; type : int; domain_group : Sample metadata; units_or_scale : NA) : Unique identifier of the sample associated with the analysis context.

**2. ANALYSIS_ID** (is_computed : 0; type : int; domain_group : Analysis metadata; units_or_scale : NA) : Unique identifier of the analysis record.

**3. ANALYSIS_CONTRACT** (is_computed : 0; type : varchar; domain_group : Analysis metadata; units_or_scale : NA) : Contract under which the analysis was performed (filtered to exclude KEBABB and DFO-D. Côté).

**4. STATION_NAME** (is_computed : 0; type : varchar; domain_group : Sampling context; units_or_scale : NA) : Station identifier/name.

**5. DEPLOYMENT_DATE_START** (is_computed : 0; type : date; domain_group : Deployment identification & timing; units_or_scale : NA) : Deployment start date (filtered to years 2010–2025 inclusive).

**6. DEPLOYMENT_TIME_START** (is_computed : 0; type : time; domain_group : Deployment identification & timing; units_or_scale : NA) : Deployment start time.

**7. CAST_NUMBER** (is_computed : 0; type : varchar; domain_group : Deployment identification & timing; units_or_scale : NA) : Cast number/order for the gear at the station.

**8. GEAR** (is_computed : 0; type : varchar; domain_group : Deployment identification & method; units_or_scale : NA) : Gear identifier/name used for sampling.

**9. TOW_TYPE** (is_computed : 0; type : varchar; domain_group : Deployment identification & method; units_or_scale : NA) : Tow/deployment method category.

**10. NET_MESH_SIZE** (is_computed : 0; type : int; domain_group : Net sampling configuration; units_or_scale : um) : Net mesh size in micrometer (um).

**11. SAMPLING_NET_ID** (is_computed : 1; type : longtext; domain_group : Net sampling inventory; units_or_scale : NA) : Describes net(s) used/associated with the sample (sometimes an aggregated list rather than a single net_sampling_id).

**12. MIN_SAMPLE_DEPTH** (is_computed : 0; type : decimal; domain_group : Net sampling configuration; units_or_scale : m (depth)) : Minimum (shallowest) depth sampled.

**13. MAX_SAMPLE_DEPTH** (is_computed : 0; type : decimal; domain_group : Net sampling configuration; units_or_scale : m (depth)) : Maximum (deepest) depth sampled.

**14. DEPTH_CALC_NET_FILTERED_VOL** (is_computed : 0; type : decimal; domain_group : Volume metrics; units_or_scale : m3) : Depth-based estimate of net filtered/visited volume used for abundance/biomass normalization.

**15. FLOWMETER_CALC_VOL** (is_computed : 0; type : decimal; domain_group : Volume metrics; units_or_scale : m3) : Flowmeter-based estimate of net filtered volume used for abundance/biomass normalization.

**16. TAXON_ID** (is_computed : 0; type : varchar; domain_group : Taxonomy; units_or_scale : NA) : Taxon identifier for which copepod/nauplius stage metrics are reported.

**17. KINGDOM** (is_computed : 0; type : varchar; domain_group : Taxonomy; units_or_scale : NA) : Taxonomic kingdom.

**18. PHYLUM** (is_computed : 0; type : varchar; domain_group : Taxonomy; units_or_scale : NA) : Taxonomic phylum.

**19. CLASS** (is_computed : 0; type : varchar; domain_group : Taxonomy; units_or_scale : NA) : Taxonomic class.

**20. ORDER** (is_computed : 0; type : varchar; domain_group : Taxonomy; units_or_scale : NA) : Taxonomic order.

**21. FAMILY** (is_computed : 0; type : varchar; domain_group : Taxonomy; units_or_scale : NA) : Taxonomic family.

**22. C1_SAMPLE_ABUND (nbr of ind.)** (is_computed : 1; type : double; domain_group : Abundance (counts); units_or_scale : individuals) : C1 (copepodid stage 1) abundance as number of individuals attributed to the sample (not volume-normalized).

**23. C1_ABUND (ind./m3 depth vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : C1 abundance normalized by depth-calculated filtered volume.

**24. C1_ABUND (ind./m3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : C1 abundance normalized by flowmeter-calculated filtered volume.

**25. C1_BIOMASS (µg C m-3 depth vol.)** (is_computed : 1; type : double; domain_group : Biomass (normalized); units_or_scale : µg C/m3) : C1 biomass (carbon) normalized by depth-calculated filtered volume.

**26. C1_BIOMASS (µg C m-3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Biomass (normalized); units_or_scale : µg C/m3) : C1 biomass (carbon) normalized by flowmeter-calculated filtered volume.

**27. C2_SAMPLE_ABUND (nbr of ind.)** (is_computed : 1; type : double; domain_group : Abundance (counts); units_or_scale : individuals) : C2 (copepodid stage 2) abundance as number of individuals attributed to the sample.

**28. C2_ABUND (ind./m3 depth vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : C2 abundance normalized by depth-calculated filtered volume.

**29. C2_ABUND (ind./m3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : C2 abundance normalized by flowmeter-calculated filtered volume.

**30. C2_BIOMASS (µg C m-3 depth vol.)** (is_computed : 1; type : double; domain_group : Biomass (normalized); units_or_scale : µg C/m3) : C2 biomass (carbon) normalized by depth-calculated filtered volume.

**31. C2_BIOMASS (µg C m-3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Biomass (normalized); units_or_scale : µg C/m3) : C2 biomass (carbon) normalized by flowmeter-calculated filtered volume.

**32. C3_SAMPLE_ABUND (nbr of ind.)** (is_computed : 1; type : double; domain_group : Abundance (counts); units_or_scale : individuals) : C3 (copepodid stage 3) abundance as number of individuals attributed to the sample.

**33. C3_ABUND (ind./m3 depth vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : C3 abundance normalized by depth-calculated filtered volume.

**34. C3_ABUND (ind./m3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : C3 abundance normalized by flowmeter-calculated filtered volume.

**35. C3_BIOMASS (µg C m-3 depth vol.)** (is_computed : 1; type : double; domain_group : Biomass (normalized); units_or_scale : µg C/m3) : C3 biomass (carbon) normalized by depth-calculated filtered volume.

**36. C3_BIOMASS (µg C m-3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Biomass (normalized); units_or_scale : µg C/m3) : C3 biomass (carbon) normalized by flowmeter-calculated filtered volume.

**37. C4_SAMPLE_ABUND (nbr of ind.)** (is_computed : 1; type : double; domain_group : Abundance (counts); units_or_scale : individuals) : C4 (copepodid stage 4) abundance as number of individuals attributed to the sample.

**38. C4_ABUND (ind./m3 depth vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : C4 abundance normalized by depth-calculated filtered volume.

**39. C4_ABUND (ind./m3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : C4 abundance normalized by flowmeter-calculated filtered volume.

**40. C4_BIOMASS (µg C m-3 depth vol.)** (is_computed : 1; type : double; domain_group : Biomass (normalized); units_or_scale : µg C/m3) : C4 biomass (carbon) normalized by depth-calculated filtered volume.

**41. C4_BIOMASS (µg C m-3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Biomass (normalized); units_or_scale : µg C/m3) : C4 biomass (carbon) normalized by flowmeter-calculated filtered volume.

**42. C5_SAMPLE_ABUND (nbr of ind.)** (is_computed : 1; type : double; domain_group : Abundance (counts); units_or_scale : individuals) : C5 (copepodid stage 5) abundance as number of individuals attributed to the sample.

**43. C5_ABUND (ind./m3 depth vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : C5 abundance normalized by depth-calculated filtered volume.

**44. C5_ABUND (ind./m3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : C5 abundance normalized by flowmeter-calculated filtered volume.

**45. C5_BIOMASS (µg C m-3 depth vol.)** (is_computed : 1; type : double; domain_group : Biomass (normalized); units_or_scale : µg C/m3) : C5 biomass (carbon) normalized by depth-calculated filtered volume.

**46. C5_BIOMASS (µg C m-3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Biomass (normalized); units_or_scale : µg C/m3) : C5 biomass (carbon) normalized by flowmeter-calculated filtered volume.

**47. M_SAMPLE_ABUND (nbr of ind.)** (is_computed : 1; type : double; domain_group : Abundance (counts); units_or_scale : individuals) : Adult male abundance as number of individuals attributed to the sample.

**48. M_ABUND (ind./m3 depth vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : Adult male abundance normalized by depth-calculated filtered volume.

**49. M_ABUND (ind./m3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : Adult male abundance normalized by flowmeter-calculated filtered volume.

**50. M_BIOMASS (µg C m-3 depth vol.)** (is_computed : 1; type : double; domain_group : Biomass (normalized); units_or_scale : µg C/m3) : Adult male biomass (carbon) normalized by depth-calculated filtered volume.

**51. M_BIOMASS (µg C m-3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Biomass (normalized); units_or_scale : µg C/m3) : Adult male biomass (carbon) normalized by flowmeter-calculated filtered volume.

**52. F_SAMPLE_ABUND (nbr of ind.)** (is_computed : 1; type : double; domain_group : Abundance (counts); units_or_scale : individuals) : Adult female abundance as number of individuals attributed to the sample.

**53. F_ABUND (ind./m3 depth vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : Adult female abundance normalized by depth-calculated filtered volume.

**54. F_ABUND (ind./m3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : Adult female abundance normalized by flowmeter-calculated filtered volume.

**55. F_BIOMASS (µg C m-3 depth vol.)** (is_computed : 1; type : double; domain_group : Biomass (normalized); units_or_scale : µg C/m3) : Adult female biomass (carbon) normalized by depth-calculated filtered volume.

**56. F_BIOMASS (µg C m-3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Biomass (normalized); units_or_scale : µg C/m3) : Adult female biomass (carbon) normalized by flowmeter-calculated filtered volume.

**57. COP_NS_SAMPLE_ABUND (nbr of ind.)** (is_computed : 1; type : double; domain_group : Abundance (counts); units_or_scale : individuals) : Copepod not specified stage (Cop_NS) abundance as number of individuals attributed to the sample.

**58. COP_NS_ABUND (ind./m3 depth vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : Cop_NS abundance normalized by depth-calculated filtered volume.

**59. COP_NS_ABUND (ind./m3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : Cop_NS abundance normalized by flowmeter-calculated filtered volume.

**60. COP_NS_BIOMASS (µg C m-3 depth vol.)** (is_computed : 1; type : double; domain_group : Biomass (normalized); units_or_scale : µg C/m3) : Cop_NS biomass (carbon) normalized by depth-calculated filtered volume.

**61. COP_NS_BIOMASS (µg C m-3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Biomass (normalized); units_or_scale : µg C/m3) : Cop_NS biomass (carbon) normalized by flowmeter-calculated filtered volume.

**62. COPEPODID_SAMPLE_ABUND (nbr of ind.)** (is_computed : 1; type : double; domain_group : Abundance (counts); units_or_scale : individuals) : Copepodid aggregate abundance (all copepodid stages combined) as number of individuals attributed to the sample.

**63. COPEPODID_ABUND (ind./m3 depth vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : Copepodid aggregate abundance normalized by depth-calculated filtered volume.

**64. COPEPODID_ABUND (ind./m3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : Copepodid aggregate abundance normalized by flowmeter-calculated filtered volume.

**65. COPEPODID_BIOMASS (µg C m-3 depth vol.)** (is_computed : 1; type : double; domain_group : Biomass (normalized); units_or_scale : µg C/m3) : Copepodid aggregate biomass (carbon) normalized by depth-calculated filtered volume.

**66. COPEPODID_BIOMASS (µg C m-3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Biomass (normalized); units_or_scale : µg C/m3) : Copepodid aggregate biomass (carbon) normalized by flowmeter-calculated filtered volume.

**67. N1_SAMPLE_ABUND (nbr of ind.)** (is_computed : 1; type : double; domain_group : Abundance (counts); units_or_scale : individuals) : N1 (nauplius stage 1) abundance as number of individuals attributed to the sample.

**68. N1_ABUND (ind./m3 depth vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : N1 abundance normalized by depth-calculated filtered volume.

**69. N1_ABUND (ind./m3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : N1 abundance normalized by flowmeter-calculated filtered volume.

**70. N2_SAMPLE_ABUND (nbr of ind.)** (is_computed : 1; type : double; domain_group : Abundance (counts); units_or_scale : individuals) : N2 (nauplius stage 2) abundance as number of individuals attributed to the sample.

**71. N2_ABUND (ind./m3 depth vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : N2 abundance normalized by depth-calculated filtered volume.

**72. N2_ABUND (ind./m3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : N2 abundance normalized by flowmeter-calculated filtered volume.

**73. N3_SAMPLE_ABUND (nbr of ind.)** (is_computed : 1; type : double; domain_group : Abundance (counts); units_or_scale : individuals) : N3 (nauplius stage 3) abundance as number of individuals attributed to the sample.

**74. N3_ABUND (ind./m3 depth vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : N3 abundance normalized by depth-calculated filtered volume.

**75. N3_ABUND (ind./m3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : N3 abundance normalized by flowmeter-calculated filtered volume.

**76. N4_SAMPLE_ABUND (nbr of ind.)** (is_computed : 1; type : double; domain_group : Abundance (counts); units_or_scale : individuals) : N4 (nauplius stage 4) abundance as number of individuals attributed to the sample.

**77. N4_ABUND (ind./m3 depth vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : N4 abundance normalized by depth-calculated filtered volume.

**78. N4_ABUND (ind./m3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : N4 abundance normalized by flowmeter-calculated filtered volume.

**79. N5_SAMPLE_ABUND (nbr of ind.)** (is_computed : 1; type : double; domain_group : Abundance (counts); units_or_scale : individuals) : N5 (nauplius stage 5) abundance as number of individuals attributed to the sample.

**80. N5_ABUND (ind./m3 depth vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : N5 abundance normalized by depth-calculated filtered volume.

**81. N5_ABUND (ind./m3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : N5 abundance normalized by flowmeter-calculated filtered volume.

**82. N6_SAMPLE_ABUND (nbr of ind.)** (is_computed : 1; type : double; domain_group : Abundance (counts); units_or_scale : individuals) : N6 (nauplius stage 6) abundance as number of individuals attributed to the sample.

**83. N6_ABUND (ind./m3 depth vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : N6 abundance normalized by depth-calculated filtered volume.

**84. N6_ABUND (ind./m3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : N6 abundance normalized by flowmeter-calculated filtered volume.

**85. NAUP_NS_SAMPLE_ABUND (nbr of ind.)** (is_computed : 1; type : double; domain_group : Abundance (counts); units_or_scale : individuals) : Nauplius not specified stage (Naup_NS) abundance as number of individuals attributed to the sample.

**86. NAUP_NS_ABUND (ind./m3 depth vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : Naup_NS abundance normalized by depth-calculated filtered volume.

**87. NAUP_NS_ABUND (ind./m3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : Naup_NS abundance normalized by flowmeter-calculated filtered volume.

**88. NAUPLIUS_SAMPLE_ABUND (nbr of ind.)** (is_computed : 1; type : double; domain_group : Abundance (counts); units_or_scale : individuals) : Nauplius aggregate abundance (all nauplius stages combined) as number of individuals attributed to the sample.

**89. NAUPLIUS_ABUND (ind./m3 depth vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : Nauplius aggregate abundance normalized by depth-calculated filtered volume.

**90. NAUPLIUS_ABUND (ind./m3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : Nauplius aggregate abundance normalized by flowmeter-calculated filtered volume.

**91. ALL_STAGES_SAMPLE_ABUND (nbr of ind.)** (is_computed : 1; type : double; domain_group : Abundance (counts); units_or_scale : individuals) : All stages combined abundance as number of individuals attributed to the sample.

**92. ALL_STAGES_ABUND (ind./m3 depth vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : All stages combined abundance normalized by depth-calculated filtered volume.

**93. ALL_STAGES_ABUND (ind./m3 flowmeter vol.)** (is_computed : 1; type : double; domain_group : Abundance (normalized); units_or_scale : ind./m3) : All stages combined abundance normalized by flowmeter-calculated filtered volume.
