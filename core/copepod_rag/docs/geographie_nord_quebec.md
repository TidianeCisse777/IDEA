# Géographie du Nord québécois — contexte scientifique NeoLab

Mots-clés : Nunavik, Arctique québécois, baie d'Ungava, détroit d'Hudson, baie de James, mer du Labrador, Hawke Channel, Inuit, communautés nordiques, rivières nordiques, masses d'eau, courant du Labrador, glace de mer, zooplancton arctique

---

## Vue d'ensemble

Le nord du Québec désigne la région au-delà du 55e parallèle, dominée par le territoire du Nunavik (Inuit) et encadrée par trois masses d'eau principales : la baie d'Hudson à l'ouest, la baie d'Ungava au nord-est et le détroit d'Hudson au nord. Cette région est au cœur des campagnes océanographiques de NeoLab (croisières Amundsen, Hawke Channel 2024).

---

## 1. Masses d'eau et mers

> **Filtrage spatial** : pour obtenir la bbox ou le polygone d'une de ces zones, appeler `get_zone_info(zone_name=...)`. Le tool renvoie le polygone IHO/NeoLab précis et la bbox dérivée — ne pas coder en dur des bornes lat/lon.

### Baie d'Hudson
- Mer intérieure peu profonde (profondeur moyenne ~150 m), entourée du Nunavik (est), de l'Ontario et du Manitoba (sud-ouest), du Nunavut (nord).
- Couverture de glace saisonnière : novembre à juillet dans le nord.
- Fort apport d'eau douce des rivières québécoises (Grande Baleine, Nastapoka, Rupert, Eastmain).
- Stratification verticale marquée en été due au dégel des glaces.
- Espèces dominantes : *Calanus hyperboreus*, *C. glacialis*, *Pseudocalanus* spp.

### Baie de James (Baie James)
- Extension sud de la baie d'Hudson, séparée par la ligne Cap Henrietta Maria → Pointe Louis-XIV. Peu profonde (~50 m), dessalinisation importante par les rivières Rupert, Broadback, Nottaway, Eastmain.
- Zone estuarienne à faible salinité (< 20 PSU en été).
- Territoire des Cris (Eeyou Istchee) sur la rive est.

### Détroit d'Hudson
- Passage entre la baie d'Hudson et la mer du Labrador. Largeur ~200 km, profondeur jusqu'à 900 m dans le chenal central.
- Courants de marée très forts. Échange bidirectionnel : eau atlantique (est → ouest en profondeur), eau de la baie d'Hudson (ouest → est en surface).
- Zone de forte turbulence et productivité biologique.
- Hawke Channel est localisé dans la partie orientale du détroit d'Hudson.

### Baie d'Ungava
- Mer semi-fermée au nord-est du Nunavik, séparée du Détroit d'Hudson par la ligne Cap Hopes Advance → Cape Chidley. Marées parmi les plus importantes au monde (jusqu'à 12 m).
- Apport d'eau douce : rivières George, Leaf (aux Feuilles), Arnaud (Payne).
- Zone d'alimentation pour baleines bélugas et ours polaires.
- Faible couverture de glace comparée à la baie d'Hudson.

### Mer du Labrador
- Mer ouverte entre le Québec-Labrador (ouest) et le Groenland (est).
- Zone de formation d'eau profonde (convection hivernale profonde, NADW).
- Courant du Labrador : courant froid (~0-4°C, salinité ~33 PSU) qui coule vers le sud le long de la côte.
- Forte productivité printanière liée à la fonte des glaces (bloom phytoplancton).
- Zone de diversité élevée de copépodes (*C. finmarchicus*, *C. hyperboreus*, *C. glacialis*).

### Hawke Channel
- Chenal sous-marin sur le plateau labradorien, à l'est de la Mer du Labrador (NB : la formulation historique « partie orientale du détroit d'Hudson » est imprécise — Hawke Channel est sur la côte du Labrador, pas dans le Détroit d'Hudson).
- Zone d'étude principale de la campagne NeoLab 2024 (stations HC-02 à HC-32).
- Profondeurs variables : de ~100 m sur les plateaux à >500 m dans le chenal central.
- Influence du courant du Labrador (eaux froides et denses).
- 31 stations d'échantillonnage disposées en grille régulière (~1° de résolution).
- Le polygone NeoLab actuel est une bbox approximative — `get_zone_info("Hawke Channel")` renvoie un carré 52–56°N × 53–57°W (TODO : remplacer par convex hull des stations HC-* + buffer 25 km).

**Stations HC (Hawke Channel 2024) :**

| Station | Lat approx. | Lon approx. |
|---|---|---|
| HC-02 | 54.2°N | 55.8°W |
| HC-03 | 54.5°N | 55.1°W |
| HC-05 | 54.3°N | 54.8°W |
| HC-09 | 54.4°N | 54.1°W |
| HC-11 | 54.4°N | 53.5°W |
| HC-15 | 54.2°N | 53.4°W |
| HC-17 | 53.9°N | 54.9°W |
| HC-19 | 53.7°N | 55.7°W |
| HC-22 | 53.7°N | 54.3°W |
| HC-25 | 53.4°N | 54.5°W |
| HC-29 | 53.2°N | 53.3°W |
| HC-32 | 53.1°N | 54.4°W |

*(Coordonnées approximatives — utiliser les données brutes pour l'analyse)*

---

## 2. Nunavik — territoire Inuit du Nord québécois

### Définition et statut
- Territoire au nord du 55e parallèle au Québec.
- Superficie : ~507 000 km² (un tiers du territoire québécois).
- Population : ~13 000 habitants (2021), majoritairement Inuit.
- Administration : **Kativik Regional Government (KRG)** / Administration régionale Kativik (ARK).
- Convention de la Baie James et du Nord québécois (CBJNQ, 1975) : fondement juridique des droits Inuit.

### Communautés Inuit du Nunavik (14 villages)

| Communauté | Nom Inuit | Lat | Lon | Côte |
|---|---|---|---|---|
| Kuujjuaq | Kuujjuaq | 58.1°N | 68.4°W | Baie d'Ungava |
| Kuujjuaraapik | Whapmagoostui | 55.3°N | 77.8°W | Baie d'Hudson |
| Umiujaq | Umiujaq | 56.5°N | 76.5°W | Baie d'Hudson |
| Inukjuak | Inukjuak | 58.5°N | 78.1°W | Baie d'Hudson |
| Puvirnituq | Puvirnituq | 60.0°N | 77.3°W | Baie d'Hudson |
| Akulivik | Akulivik | 60.8°N | 78.2°W | Baie d'Hudson |
| Ivujivik | Ivujivik | 62.4°N | 77.9°W | Détroit d'Hudson |
| Salluit | Salluit | 62.2°N | 75.6°W | Détroit d'Hudson |
| Kangiqsujuaq | Kangiqsujuaq | 61.6°N | 71.9°W | Détroit d'Hudson |
| Quaqtaq | Quaqtaq | 61.1°N | 69.6°W | Détroit d'Hudson |
| Kangirsuk | Kangirsuk | 60.0°N | 70.0°W | Baie d'Ungava |
| Aupaluk | Aupaluk | 59.3°N | 69.6°W | Baie d'Ungava |
| Tasiujaq | Tasiujaq | 58.7°N | 69.9°W | Baie d'Ungava |
| Kangiqsualujjuaq | Kangiqsualujjuaq | 58.7°N | 65.9°W | Baie d'Ungava |

### Contexte pour la recherche NeoLab
- Les campagnes d'échantillonnage en eaux nordiques québécoises se déroulent dans ou à proximité du territoire Nunavik.
- Les savoirs écologiques traditionnels inuit (IQ/TEK) sur la glace, les migrations et les espèces marines sont des sources complémentaires reconnues.
- La recherche en eaux nordiques doit tenir compte des engagements CBJNQ et des protocoles de consultation KRG.

---

## 3. Principaux cours d'eau nordiques québécois

| Rivière | Embouchure approx. | Débit moyen | Se jette dans |
|---|---|---|---|
| Grande Rivière de la Baleine | 55.3°N, 77.8°W | ~800 m³/s | Baie d'Hudson |
| Petite Rivière de la Baleine | 55.3°N, 77.6°W | ~200 m³/s | Baie d'Hudson |
| Rivière Nastapoka | 56.9°N, 76.5°W | ~350 m³/s | Baie d'Hudson |
| Rivière aux Feuilles (Leaf) | 58.7°N, 72.0°W | ~600 m³/s | Baie d'Ungava |
| Rivière George | 58.5°N, 65.5°W | ~1 700 m³/s | Baie d'Ungava |
| Rivière Arnaud (Payne) | 60.0°N | ~400 m³/s | Baie d'Ungava |
| Rivière Caniapiscau | via Koksoak → Kuujjuaq | ~1 200 m³/s | Baie d'Ungava |
| Grande rivière Eastmain | 52.2°N, 78.5°W | ~500 m³/s | Baie de James |
| Rivière Rupert | 51.5°N, 78.7°W | ~900 m³/s | Baie de James |

**Impact sur les données océanographiques :**
Les apports fluviaux nordiques créent une lentille d'eau douce en surface qui stratifie la colonne d'eau, réduit la salinité de surface (<28 PSU en été) et influence la distribution verticale du zooplancton. Dans les analyses, vérifier la variable `salinity` ou `psal` pour distinguer les masses d'eau d'origine fluviale des eaux marines.

---

## 4. Masses d'eau et courants régionaux

| Masse d'eau | Caractéristiques | Zone |
|---|---|---|
| Courant du Labrador | Froid (0–4°C), salinité 33 PSU, flux vers le sud | Mer du Labrador, côte Labrador |
| Eau de la baie d'Hudson | Froide, dessalinisée (<32 PSU), flux est via détroit d'Hudson | Détroit d'Hudson, Hawke Channel |
| Eau atlantique subsurface | Chaude (4–6°C), salinité 34.5 PSU, en profondeur | Baie de Baffin, mer du Labrador |
| Eau de fonte saisonnière | Très froide (< 0°C), salinité variable, en surface printemps | Toutes les zones nordiques |

---

## 5. Saisonnalité et glace de mer

| Saison | Phénomène | Impact sur l'échantillonnage |
|---|---|---|
| Nov – Fév | Formation de la glace, couverture maximale | Campagnes impossibles sans brise-glace |
| Mar – Avr | Glace maximale, début du bloom sous la glace | Amundsen en opération |
| Mai – Juin | Débâcle, bloom printanier intense | Période de productivité maximale |
| Juil – Sep | Eaux libres, stratification maximale | Campagnes estivales (Hawke Channel 2024) |
| Oct | Recongélation progressive | Fin de saison |

---

## 6. Noms géographiques — correspondances français / inuktitut / anglais

| Français | Inuktitut / local | Anglais |
|---|---|---|
| Baie d'Ungava | Ungava | Ungava Bay |
| Baie d'Hudson | — | Hudson Bay |
| Détroit d'Hudson | — | Hudson Strait |
| Baie de James | Eeyou Istchee (Cri) | James Bay |
| Mer du Labrador | — | Labrador Sea |
| Grande Rivière de la Baleine | Kuujjuaraapik | Great Whale River |
| Rivière George | Kangiqsualujjuaq (région) | George River |
| Rivière aux Feuilles | — | Leaf River |
| Nunavik | Nunavik | Nunavik |
| Kuujjuaq | Kuujjuaq | Fort Chimo (historique) |
