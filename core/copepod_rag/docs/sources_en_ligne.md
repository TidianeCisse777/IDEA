# sources_en_ligne.md

---

# Quelle source utiliser pour quelle question ?

| Question du chercheur | Source à utiliser |
|---|---|
| "Je veux les annotations taxonomiques de ma campagne" | EcoTaxa |
| "Je veux les profils UVP avec CTD et volume échantillonné" | EcoPart |
| "Je veux la CTD officielle du navire Amundsen" | Amundsen ERDDAP |
| "Je veux mes données de comptage filet ou lipides" | Données labo (fichier local) |
| "Est-ce que cette espèce a été observée dans cette zone par d'autres groupes ?" | OBIS |
| "Quelles espèces sont attendues dans cette zone mais absentes de mes données ?" | OBIS |
| "Qu'est-ce que mes données ne couvrent pas par rapport à ce qui existe mondialement ?" | OBIS |
| "Je veux la température / glace de mer / salinité pour contextualiser" | CMEMS |

**Règle générale :**

- Données du labo → EcoTaxa, EcoPart, Amundsen, fichiers locaux
- Contexte mondial pour analyse de lacunes → OBIS
- Comparaison taxonomique (espèces attendues vs observées) → OBIS + corpus RAG copépodes
- Contexte environnemental → CMEMS

---

# Comment accéder à EcoTaxa ?

**Ce que ça contient :** annotations taxonomiques, morphométrie image, stades — au niveau objet individuel.

**Accès :** compte requis — credentials dans `.env` (ne jamais committer).

**Limite :** pas de poids, lipides ou biomasse dans les exports TSV.

---

# Comment accéder à EcoPart ?

**Ce que ça contient :** profils UVP agrégés par bin de profondeur — CTD, volume échantillonné, particules. Indispensable pour calculer des concentrations.

**Accès :** compte requis — mêmes credentials que EcoTaxa.

**Dataset labo Maps :** `105` — uvp5_sn008_ips_amundsen_2018, lié au projet EcoTaxa `1165`.

**Limite :** ne décrit pas les objets individuellement — toujours joindre avec EcoTaxa.

---

# Comment accéder à la CTD officielle Amundsen ?

**Ce que ça contient :** température, salinité, oxygène, fluorescence, nitrate — mesures officielles du navire par cast CTD.

**Accès :** public, aucun compte requis — via ERDDAP.

**URL :** `https://erddap.amundsenscience.com/erddap/tabledap/amundsen12713`

**Paramètres de requête :** fenêtre temporelle, lat/lon, variables (`TE90`, `PSAL`, `OXYM`, `FLOR`, `NTRA`).

**Limite :** Event Log (`ca-cioos_ccin-13248`) non disponible via ERDDAP — formulaire requis.

---

# Comment accéder aux données internes du labo Maps ?

**Ce que ça contient :** comptages filet, mesures lipides, stades manuels — fichiers CSV produits par le labo.

**Accès :** fichiers locaux — pas d'API. Structure à confirmer lors de la réception d'un fichier réel.

**Règle :** ne pas supposer les colonnes avant d'avoir vu le fichier.

---

# Comment chercher des occurrences d'espèces dans OBIS ?

**Ce que ça contient :** occurrences biologiques marines mondiales géolocalisées — qui a observé quelle espèce, où, quand.

**Accès :** public, aucun compte requis.

**URL API :** `https://api.obis.org/v3/occurrence`

**Paramètres clés :**

- `taxonid` — AphiaID WoRMS de l'espèce (ex. `104464` pour _C. hyperboreus_)
- `geometry` — zone en WKT
- `startdate` / `enddate` — période

**Package R :** `robis`

**Quand l'utiliser :**

- Analyse de lacunes (UC-SL-14, AG-V1-10) : comparer la couverture locale avec ce qui existe mondialement pour une zone et une période données. Argument pour demandes de financement.
- Absences taxonomiques (UC-SL-12 ext. 3b, AG-V1-11) : récupérer la liste des espèces documentées dans OBIS pour la zone géographique du contexte, puis comparer avec les taxons observés dans les données locales pour identifier les absences.

**Procédure comparaison taxonomique (UC-SL-12 ext. 3b) :**
1. Extraire les taxons observés dans les données locales (colonne taxon, statut validé).
2. Interroger OBIS pour la même zone et période : `GET /v3/occurrence?geometry=<WKT>&startdate=<>`.
3. Lister les espèces présentes dans OBIS mais absentes des données locales.
4. Signaler explicitement les espèces pour lesquelles l'absence peut être un biais d'observation (ex : stades hivernaux, profondeurs non échantillonnées).

**Limite :** biais spatial (peu de données hivernales arctiques) ; identification incertaine _C. glacialis_ vs _C. finmarchicus_ dans les données historiques OBIS — toujours signaler ce biais lors d'une comparaison taxonomique.

---

# Comment accéder aux données environnementales via CMEMS ?

**Ce que ça contient :** température, salinité, glace de mer, courants — données grillées globales et régionales Arctique.

**Accès :** compte gratuit requis sur `marine.copernicus.eu`. Un seul compte pour toute l'équipe Maps.

**Package Python :** `copernicusmarine` — `pip install copernicusmarine`

**Paramètres clés :** `dataset_id`, variables, fenêtre spatiale (lon/lat), fenêtre temporelle, profondeur.

**Datasets utiles labo Maps :**

- Arctique physique : `cmems_mod_arc_phy_anfc_6km_detided_P1D-m`
- Glace de mer Arctique : `cmems_obs-si_arc_physic_nrt_l4-obs_P1D`
- Global (Saint-Laurent) : `cmems_mod_glo_phy_anfc_0.083deg_P1D-m`

**Format retour :** NetCDF / Zarr — lire avec `xarray`.

**Limite :** compte obligatoire à configurer avant premier usage.

_Dernière mise à jour : mai 2026_
