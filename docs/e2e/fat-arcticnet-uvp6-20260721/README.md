# E2E — Exploration UVP6 Arctique canadien (fat cache)

## Session

- Date : 2026-07-21
- `USER_ID` : `e2e-fat-arcticnet-uvp6`
- `CHAT_ID` : `e2e-fat-arcticnet-uvp6-20260721`
- Cache : `data/ecotaxa_cache_fat.sqlite` (2694 samples, 18 projets)
- Source : EcoTaxa cache local uniquement — aucun fichier local chargé

## Contexte scientifique

Un chercheur de NeoLab veut préparer une étude comparative de la couverture
zooplankton UVP6 dans l'Arctique canadien (Baie de Baffin, Mer de Beaufort,
Mer du Labrador) pour planifier une prochaine campagne ArcticNet. Il explore
par langage naturel, sans connaître les `project_id` ni les noms techniques
des tools.

Le fat cache contient :
- 6 projets réels (Loki 2013–2024, UVP5SD 2015, UVP6 2024)
- 12 campagnes synthétiques ArcticNet/GreenEdge/Amundsen (2016–2023, UVP6/Loki/UVP5SD)

## Tours

### Tour 1 — Découverte globale

```
Qu'est-ce qu'on a comme données zooplankton dans EcoTaxa ?
```

**Attendu** : liste des campagnes du cache (instrument, années, nb samples).
Aucun appel API live. UVP6 et Loki distingués.

---

### Tour 2 — Focus Baie de Baffin

```
Qu'est-ce qu'on a en Baie de Baffin ?
```

**Attendu** : résolution géographique → samples filtrés sur la zone Baffin.
Projets 80001 (ArcticNet-2017-UVP6-Baffin) et 80010 (GreenEdge-2016) présents.
Résultat depuis le cache, pas de valeur inventée.

---

### Tour 3 — Filtre instrument UVP6

```
Garde uniquement les données UVP6
```

**Attendu** : filtre instrument=UVP6 appliqué sur la sélection Baffin.
GreenEdge (UVP5SD) exclu. Projet 80001 uniquement.

---

### Tour 4 — Distribution temporelle

```
Montre-moi la distribution de ces échantillons par année
```

**Attendu** : `group_ecotaxa_samples_by_year` ou équivalent, tableau ou
graphique avec les années des samples UVP6 Baffin. Aucune année inventée.

---

### Tour 5 — Comparaison Mer de Beaufort

```
Fais la même chose pour la Mer de Beaufort
```

**Attendu** : nouvelle requête spatiale Beaufort, filtre UVP6 appliqué,
projets 80030 (ArcticNet-2020) et 80070 (MultiZone-2023). Distribution
temporelle comparée à Baffin.

---

### Tour 6 — Carte comparative

```
Fais une carte qui montre les stations UVP6 de Baffin et Beaufort ensemble,
avec une couleur par zone
```

**Attendu** : `run_graph` avec les samples des deux zones, couleur par zone
ou par projet. Points géolocalisés corrects (pas de points fictifs).

---

### Tour 7 — Profondeur maximale

```
Quel projet a les échantillons les plus profonds ?
```

**Attendu** : comparaison `depth_max` entre projets UVP6 des deux zones.
Valeur chiffrée tirée du cache, pas inventée. Projet identifié par nom de
campagne.

---

### Tour 8 — Comparaison Labrador

```
Et en Mer du Labrador, qu'est-ce qu'on a en UVP6 ?
```

**Attendu** : requête Labrador → projet 80020 (Amundsen-2019-leg1-Labrador,
27 samples UVP6). Résultat cohérent avec les tours précédents.

---

### Tour 9 — Synthèse exportable

```
Donne-moi un tableau récapitulatif des trois zones : nombre de samples UVP6,
années couvertes, profondeur moyenne
```

**Attendu** : tableau Baffin / Beaufort / Labrador avec les métriques
demandées. Chaque valeur provient du cache (run_pandas ou SQL). Aucune
métrique inventée.

---

## Fiche de contrôle

| Tour | Intention | Tool(s) attendus | Verdict |
|---:|---|---|---|
| 1 | Découverte globale | list_ecotaxa_campaigns | |
| 2 | Baffin — tous instruments | find_ecotaxa_samples_in_region | |
| 3 | Filtre UVP6 | find_ecotaxa_samples_in_region(instrument=UVP6) | |
| 4 | Distribution temporelle | group_ecotaxa_samples_by_year | |
| 5 | Beaufort UVP6 | find_ecotaxa_samples_in_region + year | |
| 6 | Carte comparative | run_graph | |
| 7 | Profondeur max | query_ecotaxa_cache ou run_pandas | |
| 8 | Labrador UVP6 | find_ecotaxa_samples_in_region | |
| 9 | Synthèse 3 zones | run_pandas ou query_ecotaxa_cache | |

## Critères de succès globaux

- Aucun `project_id` ni nom de tool dans les prompts
- Toutes les valeurs numériques proviennent du cache
- Les filtres instrument=UVP6 excluent correctement Loki et UVP5SD
- La carte contient des points réels géolocalisés
- Aucune zone ne retourne des samples de l'autre zone

## Artefacts attendus

- `conversation.md` — transcription tour par tour avec verdict
- `figures/` — carte(s) générée(s) au tour 6
- `DEFECTS.md` — défauts observés si verdict FAIL
