# Scénario E2E — Audit de disponibilité des données

Exécution manuelle multi-tour réalisée le 15 juillet 2026 contre l'API locale de
l'agent (`thread_id: e2e-audit-20260715`).

## Intention

Cadrer **ce qui est disponible avant de lancer une étude** : qu'est-ce qui est
là, qu'est-ce qui ne l'est pas, est-ce exploitable, est-ce combinable. C'est une
intention NeoLab récurrente (professeur ou étudiant en phase de scoping). Aucun
export n'est lancé — tout se fait en lecture seule sur le cache et les tools
read-only. Couvre les use cases **UC-D** (exploration) + UC-I (zone nommée).

## Déroulé

| # | Question d'audit | UC | Résultat |
|---|---|---|---|
| 1 | Qu'est-ce qui est accessible ? (projets, campagnes, cache) | UC-D1/D5/D6/D7 | 6 projets indexés (2015 + 2024, arctique) ; projet 2331 hors cache signalé |
| 2 | Qu'est-ce qui n'est PAS là ? (Golfe du Saint-Laurent, hors 2015/2024) | UC-D2/I | 0 sample dans le GSL (démontré par requête) ; listing temporel global manquant |
| 3 | Peut-on combiner deux projets ? (schémas 42 vs 17498) | UC-D4 | 102 colonnes communes, 0 conflit, fusionnables au niveau schéma |
| 4 | Où sont les copépodes ? (Calanus, UVP6 2024) | UC-D3 | Seul 17498 expose du Calanus validé (1 624) ; 14844/14859 en prédit seulement |
| 5 | Audit de couverture classé (peu de samples, périodes, samples pauvres) | UC-D | Nouveau tool `audit_ecotaxa_availability` |
| 6 | Audit spatial par zone nommée (couverture + trous) | UC-D/I | Nouveau tool `audit_ecotaxa_spatial_coverage` |

## Artefacts

- [Conversation et validations](conversation.md)
- [Défauts observés](DEFECTS_AND_PRIORITIES.md)

## Enseignements

- L'agent audite correctement **sans jamais exporter** ni inventer de valeur, et
  signale explicitement les trous (projet hors cache, zone à 0 sample).
- Il reste au niveau factuel (schéma, comptages, statuts V/P/D) sans juger la
  pertinence scientifique d'un merge — conforme au périmètre « pas
  d'interprétation ».
- La distinction **validé vs prédit** est surfacée d'office, ce qui est
  déterminant pour savoir ce qui est réellement exploitable.

## Limites observées

- Pour une lacune (« ce qui n'est pas là »), l'agent répond d'abord « non
  vérifiable » au lieu de lancer la requête zone d'emblée ; il faut le relancer.
- Pas de listing temporel global : l'audit « hors 2015/2024 » n'est pas
  directement confirmable sans bbox.
