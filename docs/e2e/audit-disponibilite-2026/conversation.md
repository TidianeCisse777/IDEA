# Conversation E2E — Audit de disponibilité des données

Scénario aligné sur une intention réelle NeoLab : **cadrer ce qui est disponible
avant de lancer une étude** — qu'est-ce qui est là, qu'est-ce qui ne l'est pas —
sans lancer aucun export. Couvre UC-D (exploration read-only). Exécution
multi-tour contre l'API locale (`thread_id: e2e-audit-20260715`).

## 1. Vue d'ensemble : projets, campagnes, cache

**Input**

> Je veux auditer les données disponibles avant de lancer une étude sur les copépodes. Sans lancer aucun export : quels projets et campagnes sont accessibles, quelle couverture géographique et temporelle, et quel est l'état du cache local ?

**Output**

- 6 projets indexés au cache : 42 (GREEN EDGE UVP5, 2015), 14622 (LOKI, 2015),
  14844 / 14859 / 17498 (UVP6, 2024, legs 2/3/4). Projet 2331 (LOKI lipids)
  visible comme campagne mais **absent du cache**.
- Deux fenêtres temporelles seulement : 2015 et 2024. Couverture géographique
  arctique (67–82 °N).
- Cache local : 97 samples, 6 projets, 7 schémas, dernier sync 2026-07-11, aucun
  sync en cours.

**Statut : validé.** Le trou (projet 2331 non indexé) est correctement signalé.

## 2. Ce qui n'est PAS là (lacunes)

**Input**

> A-t-on des données hors Arctique (Golfe du Saint-Laurent) ou hors 2015/2024 ? Sans rien inventer.

**Output — première passe (trop prudente)**

L'agent répond « non vérifiable » sans interroger la zone. Correct sur la
non-invention, mais peu utile.

**Input (relance)**

> Interroge réellement le cache : recherche par zone pour le Golfe du Saint-Laurent et confirme le compte.

**Output**

- Golfe du Saint-Laurent : **0 sample** (absence démontrée par requête réelle).
- Hors 2015/2024 : non confirmé — pas d'outil de listing temporel global sans
  bbox.

**Statut : validé après relance.** Défaut mineur : pour une lacune, l'agent
devrait lancer la requête zone d'emblée plutôt que répondre « non vérifiable ».
Limite d'outillage : pas de listing temporel global.

## 3. Peut-on combiner deux projets ? (comparaison de schémas)

**Input**

> Compare les schémas des projets 42 (UVP5 2015) et 17498 (UVP6 2024) : colonnes communes, propres à chacun, fusionnables ou non ?

**Output**

- **102 colonnes communes**, 0 conflit de type, 0 conflit de niveau.
- Colonnes propres au 42 (UVP5) : morphométrie spécifique (`esd`, `centroids`,
  `compm1..3`, `xmg5`…). Propres au 17498 : `argoid`, `sampledatetime`,
  `sampletype`, `vig_*`…
- Verdict : fusionnables au niveau schéma, pas d'incompatibilité bloquante.

**Statut : validé.** L'agent reste au niveau schéma, sans juger la pertinence
scientifique d'un merge UVP5 × UVP6 (hors périmètre d'interprétation).

## 4. Disponibilité taxonomique (Calanus)

**Input**

> Comptages d'objets validés pour le genre Calanus dans les projets UVP6 2024 (14844, 14859, 17498) ; présence/absence par projet.

**Output**

| project_id | validés | prédits | total | présence |
|---:|---:|---:|---:|---|
| 14844 | 0 | 89 | 89 | absent en validés |
| 14859 | 0 | 6 267 | 6 267 | absent en validés |
| 17498 | 1 624 | 942 | 2 566 | présent (validé) |

**Statut : validé.** La distinction validé / prédit est explicite : seul 17498
expose du Calanus **validé** exploitable ; les deux autres n'ont que du prédit.
