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

## 5. Nouvel outil d'audit : couverture classée (correctif D-AU1/D-AU2)

Les tours 1–4 ont montré que l'agent savait répondre au cas par cas mais pas à la
**famille** de questions d'audit (« classe les projets avec peu de samples »,
« quelles périodes », « les samples avec le moins d'objets »). Ajout du tool
`audit_ecotaxa_availability` (lecture seule du cache) + règles de routage.

**Input**

> Fais-moi l'audit des projets avec le moins de samples, indique quelles années sont couvertes, et donne les samples avec le moins d'objets. Sans lancer d'export.

**Output**

- Projets classés du plus pauvre au plus riche : 14622 (2), 14859 (3), 14853 (4),
  14844 (5), 42 (19) — dont 14853, absent de la vue manuelle du §1.
- Années couvertes : 2015 (21 samples, 2 projets), 2024 (76 samples, 4 projets).
- Samples les plus pauvres : `am_leg4_RA27_2` et `am_leg4_RA41_1` (7 objets), …

**Statut : validé.** L'audit de couverture est désormais un tool direct. Pour le
classement validé/prédit par taxon, l'agent route vers `count_ecotaxa_taxa`
(règle de system prompt). D-AU1 et D-AU2 adressés.

## 6. Audit spatial par zone nommée (nouveau tool)

Axe jugé crucial : cartographier la couverture sur les zones nommées et
identifier les trous géographiques. Ajout du tool `audit_ecotaxa_spatial_coverage`
(cœur `core.geo.audit_zone_coverage`) : point-in-polygon des samples du cache sur
les 65 zones du registre (IHO / MEOW / composites NeoLab).

**Input**

> Fais-moi un audit spatial de la couverture par zone nommée : quelles zones sont couvertes et combien de samples, et où sont les trous géographiques ?

**Output**

Zones couvertes (classées) : Baie de Baffin (62), MEOW Baffin Bay–Davis Strait
(40), Détroit de Davis (26), MEOW North Greenland (24), MEOW High Arctic
Archipelago (22), MEOW Lancaster Sound (9), MEOW West Greenland Shelf (2).

Trous (zones voisines sans sample) : Hudson Complex, Northern Labrador, Mer de
Lincoln, Mer des Tchouktches, Beaufort, Chukchi, Arctique (composite). 97 samples
géolocalisés, 0 hors zone.

**Statut : validé.** L'audit spatial répond directement à « quelles zones sont
couvertes / où sont les trous ». Défaut D-AU5 (audit spatial manquant) corrigé.
