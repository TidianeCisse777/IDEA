# Scénario E2E — Exploration géo-temporelle EcoTaxa

Scénario d'exploration en langage naturel : l'utilisateur découvre la source
EcoTaxa, puis navigue les données par zone géographique, période et campagne
sans jamais mentionner de `project_id` ni de nom technique.

## Objectif

Mesurer la capacité de l'agent à :

1. Décrire la source EcoTaxa depuis ses connaissances (RAG / system prompt)
2. Répondre à des questions géographiques en résolvant les zones sémantiquement
   depuis le cache local
3. Naviguer par période temporelle
4. Comparer des legs/campagnes entre eux
5. Produire une carte synthétique de la couverture disponible

## Périmètre

- Source : EcoTaxa (cache local `ecotaxa_cache.sqlite`)
- Données disponibles au moment de l'exécution :
  - `uvp6_sn000006hf_2024_am` — 3 legs (14844, 14859, 17498), UVP6, juil–oct 2024
  - `LOKI_ArcticNet_2015` — proj 14622, Loki, avr 2015
  - `UVP5 GREEN EDGE Ice Camp 2015` — proj 42, UVP5SD, avr–juin 2015
  - `LOKI - copepod lipids` — proj 2331, Loki, août–sept 2013, sans coordonnées
- Zones couvertes : mer de Baffin, archipel arctique canadien, mer de Beaufort,
  mer du Labrador, baie d'Hudson
- Aucun fichier local chargé, aucune confirmation d'export attendue

## Tours

### Tour 1 — Description de la source

```
C'est quoi EcoTaxa ?
```

**Attendu** : réponse depuis le RAG ou le system prompt — définition de la
plateforme, type de données (images plancton, classification, taxonomie),
sans appel au cache ni à l'API. Aucun tool ne doit être appelé.

**Verdict** : FAIL si un tool source est appelé / si la réponse est inventée
sans provenance RAG.

---

### Tour 2 — Découverte globale

```
Qu'est-ce qu'on a comme données dans EcoTaxa ?
```

**Attendu** : `list_ecotaxa_campaigns` appelé, réponse structurée listant les
campagnes avec instruments, nombre de samples et plage temporelle. Aucun appel
API EcoTaxa live.

**Verdict** : FAIL si l'agent appelle `list_ecotaxa_projects` (API live) au
lieu du cache, ou s'il invente des campagnes.

---

### Tour 3 — Filtre géographique : mer de Baffin

```
Qu'est-ce qu'on a en mer de Baffin ?
```

**Attendu** : résolution sémantique de la zone → appel
`find_ecotaxa_samples_in_region` ou équivalent avec bbox/zone Baffin,
résultat depuis le cache. Samples et projets matchant la zone affichés.

**Verdict** : FAIL si la zone n'est pas résolue / si l'agent répond sans
requêter le cache / si des samples hors zone sont inclus.

---

### Tour 4 — Filtre géographique : Arctique canadien

```
Et dans l'Arctique canadien ?
```

**Attendu** : nouvelle requête spatiale sur une zone distincte (archipel
arctique, Beaufort), résultat différent de Baffin. L'agent ne doit pas
répéter la même zone.

**Verdict** : FAIL si même bbox que tour 3 / si résultats identiques sans
explication.

---

### Tour 5 — Filtre temporel

```
Y'a quoi en 2015 ?
```

**Attendu** : filtre `date_range=["2015-01-01", "2015-12-31"]` appliqué sur
le cache, retourne LOKI_ArcticNet_2015 (proj 14622) et UVP5 GREEN EDGE
(proj 42). Le projet 2331 (2013) et les UVP6 2024 sont absents du résultat.

**Verdict** : FAIL si des projets hors 2015 apparaissent / si le filtre
temporel n'est pas appliqué.

---

### Tour 6 — Drill dans une campagne

```
La campagne LOKI 2015, elle couvre quelle zone exactement ?
```

**Attendu** : `preview_ecotaxa_project` ou `summarize_ecotaxa_project(s)`
sur proj 14622, réponse avec bbox (lat/lon min/max), plage de dates exacte
et nombre de samples. Pas d'appel à une autre campagne.

**Verdict** : FAIL si les coordonnées sont inventées / si un mauvais projet
est ciblé.

---

### Tour 7 — Comparaison entre legs

```
Compare les trois legs UVP6 2024 — lequel couvre la plus grande zone ?
```

**Attendu** : les trois projets (14844, 14859, 17498) sont récupérés depuis
le cache, leurs bbox comparées, le leg avec la plus grande étendue
géographique est identifié avec les coordonnées à l'appui. Pas de valeur
inventée.

**Verdict** : FAIL si un seul leg est analysé / si la comparaison est faite
sans données / si le résultat n'est pas justifié par des coordonnées.

---

### Tour 8 — Carte de couverture globale

```
Fais une carte de tout ce qu'on a dans EcoTaxa
```

**Attendu** : `run_graph` avec tous les samples géolocalisés du cache
(projets avec coords), carte Arctique/Labrador, légende par campagne ou
instrument. Le projet 2331 (sans coords) est absent de la carte ou signalé.

**Verdict** : FAIL si la carte est vide / si des points fictifs sont ajoutés /
si le projet sans coords génère une erreur bloquante.

---

### Tour 9 — Filtre temporel sur la carte

```
Maintenant montre seulement les données après 2020
```

**Attendu** : nouvelle carte sur le même périmètre géographique mais filtrée
sur `date_min >= 2020-01-01`, seuls les UVP6 2024 apparaissent. L'agent
réutilise le contexte de session sans redemander les données.

**Verdict** : FAIL si le filtre temporel n'est pas appliqué / si les données
2015 et 2013 restent sur la carte.

---

## Fiche de contrôle par tour

| Tour | Intention | Tools appelés | Source réelle | Verdict |
|---:|---|---|---|---|
| 1 | Décrire EcoTaxa | aucun | RAG / system prompt | |
| 2 | Lister les campagnes | list_ecotaxa_campaigns | cache | |
| 3 | Mer de Baffin | find_ecotaxa_samples_in_region | cache | |
| 4 | Arctique canadien | find_ecotaxa_samples_in_region | cache | |
| 5 | Filtre 2015 | find_ecotaxa_samples_in_region | cache | |
| 6 | Drill LOKI 2015 | summarize / preview proj 14622 | cache + API | |
| 7 | Comparer legs UVP6 | summarize_ecotaxa_projects | cache | |
| 8 | Carte globale | run_graph | cache | |
| 9 | Carte post-2020 | run_graph | cache | |

## Critères de succès globaux

- Aucun `project_id` ni nom de tool n'est mentionné dans les prompts
- Toutes les résolutions géographiques passent par le cache (pas d'API live)
- Les filtres temporels retournent exactement les projets attendus
- La carte tour 8 contient des points pour tous les projets avec coords
- La carte tour 9 ne contient que les UVP6 2024
- Zéro valeur scientifique inventée

## Artefacts attendus

- `conversation.md` — transcription tour par tour avec verdict
- `figures/` — cartes générées aux tours 8 et 9
- `DEFECTS_AND_PRIORITIES.md` — défauts observés si verdict FAIL
