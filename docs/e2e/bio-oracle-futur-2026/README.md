# Scénario E2E — Bio-ORACLE prospectif (priorisation d'expéditions)

Exécution multi-tour réalisée le 15 juillet 2026 contre l'API locale
(`thread_id: e2e-bo-file-20260715`).

## Intention

Anticiper l'évolution des conditions de surface (scénarios climatiques SSP) pour
**justifier où mener les futures expéditions copépodes** dans l'Arctique
canadien. Couvre UC-A (fichier local) + UC-G3 (Bio-ORACLE présent + futur) +
UC-B1 (carte).

## Données

- Fichier NeoLab `data/demo/neolabs_taxonomy_2014_2020.tsv` : 7 093 lignes,
  82 colonnes, 2014–2018, **125 stations**, 199 taxons.
- Bio-ORACLE température de surface : baseline vs SSP5-8.5, horizon 2050.

## Déroulé

| # | Étape | Résultat |
|---|---|---|
| 1 | Exploration Bio-ORACLE (variables, SSP, horizons) | SSP119→585, baseline→2100 |
| 2 | Chargement du fichier conséquent | 125 stations, coords 100 % |
| 3 | Agrégation spatiale (surface homogène) | 125 stations → 4 grappes (7,5 s) |
| 4 | Couplage baseline vs SSP5-8.5 2050 | Δ +1,10 à +1,23 °C par grappe (30 s) |
| 5 | Carte de priorisation (zones nommées) | `figures/58fdbc42c2ba.png` |
| 6 | **Correction** — abondance de l'agent fausse ; carte refaite (script déterministe) | `figures/carte_corrigee_copepodes_2050.png` |

## Résultat

D'ici 2050 (SSP5-8.5), les 4 grappes passent du négatif au voisinage / au-dessus
de 0 °C en surface. La grappe **(68,77 N / -80,84 W)** cumule la plus forte
abondance de copépodes (162 ind./m³) et le plus fort réchauffement projeté
(+1,23 °C) — priorité d'expédition la plus nette.

## Choix méthodologique clé

Bio-ORACLE est une grille grossière (~0,05°) : à la surface, le delta futur est
sensiblement homogène par zone. Agréger les 125 stations en quelques grappes
avant d'interroger Bio-ORACLE est **plus juste et bien plus rapide** que le point
par point (8–30 s/tour contre > 6 min).

## Outillage

`scripts/dev/e2e_turn.py` réécrit pour streamer chaque étape (appel d'outil,
résultat, timestamp) — progression visible pendant les tours lents.

## Limites

- Horizon 2100 indisponible ici (404 Bio-ORACLE) ; seul 2050 exploité.
- Corrélation abondance ↔ réchauffement descriptive, non causale, sans
  interprétation écologique.
- Réchauffement de surface seulement ; la profondeur n'est pas traitée.
