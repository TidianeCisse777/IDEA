# Défauts — S1 Géographie sur fichier local

## E2E-S1-001 — Les métriques du filtre géographique sont nommées à l’envers

- Scénario / tour : S1 / tour 2
- Session (`CHAT_ID`, `THREAD_ID`) : `e2e-s1-20260716-143529`, `c864fb7e77342838`
- Prompt exact : `Affiche toutes les stations présentes dans la mer du Labrador sur une carte.`
- Attendu : exposer clairement le nombre de lignes source, conservées et rejetées; appeler le tool de graphique uniquement si le sous-ensemble n’est pas vide.
- Observé : réponse `Aucune station dans la mer du Labrador : 0 ligne retenue sur 7093.` Aucun graphique n’est produit. Le `0` est reproductible et cohérent avec le polygone IHO actuel : aucun point du TSV ne tombe dans sa bbox Labrador.
- Tools exposés : `load_file`, `load_skill`, `query_copepod_knowledge_base`, `run_pandas`, `filter_dataframe_by_zone`, `get_zone_info`.
- Tools appelés et arguments : `filter_dataframe_by_zone(zone_name="Mer du Labrador", lat_col="latitude", lon_col="longitude", source_variable="df_file_neolabs_taxonomy_2014_2020")`.
- Résultat tool : `rows_in=0`, `rows_out=7093`, variable `df_in_mer_du_labrador_data_demo_neolabs_taxonomy_2014_2020`.
- Skills chargés et provenance : `neolabs_abundance_analysis`, fichier local.
- Tokens / troncatures : aucune troncature; usage provider cumulatif absent.
- Source et dataset réellement utilisés : source `file`; dataset source `df_file_neolabs_taxonomy_2014_2020`.
- Première décision incorrecte : contrat de métriques ambigu/inversé; il rend la trace trompeuse. Le filtrage lui-même n’est pas inversé dans cette session et l’absence de carte est la conséquence d’un sous-ensemble réellement vide.
- Artefacts : fichiers SSE et trace JSON du tour 2.
- Sévérité : majeur
