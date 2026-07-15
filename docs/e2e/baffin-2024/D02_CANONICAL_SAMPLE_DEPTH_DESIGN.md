# D02–D03 — Table canonique sample–profondeur

## Objectif

Garantir qu'un même export EcoTaxa–EcoPart produit une seule représentation
stable des bins échantillonnés. Les tableaux, corrélations et graphiques doivent
réutiliser cette représentation afin qu'un compte comme celui de RA18 ne puisse
pas changer entre deux analyses.

## Composant

Ajouter dans `core/` un constructeur pandas pur. Il reçoit la table objet
EcoTaxa déjà enrichie avec EcoPart et retourne une table canonique, sans accès
réseau ni état de session. La sélection Copepoda appelle obligatoirement
`copepod_hierarchy_mask`.

La granularité de sortie est exactement une ligne par clé :

```text
(sample_id, depth_bin)
```

`depth_bin` est le centre stable du bin EcoPart de 5 m. Le volume, les
coordonnées et les variables environnementales sont des attributs du bin ; ils
ne font jamais partie de la clé.

## Contrat de données

Colonnes minimales d'entrée :

- `sample_id` ;
- `depth_bin` ;
- `object_annotation_hierarchy` ;
- une colonne de volume EcoPart en litres.

Colonnes minimales de sortie :

- `sample_id`, `depth_bin` ;
- `copepod_count` ;
- `sampled_volume_L` ;
- `abundance_ind_L`, `abundance_ind_m3` ;
- `canonical_method_version`.

Les colonnes stables de station, position, date et environnement sont conservées
si elles existent et si leur valeur est unique dans le bin.

## Règles déterministes

1. Le squelette des bins vient de toutes les lignes enrichies ayant une clé et
   un volume valides, pas uniquement des objets Copepoda.
2. Le compte est la somme du masque hiérarchique Copepoda par clé. Un bin
   échantillonné sans Copepoda reçoit explicitement `copepod_count = 0`.
3. Des lignes objet dupliquées ne créent jamais plusieurs lignes canoniques pour
   une même clé.
4. Des volumes flottants quasi identiques dans un bin sont considérés comme une
   même mesure selon une tolérance numérique explicite ; la valeur canonique est
   leur moyenne déterministe.
5. Plusieurs volumes réellement incompatibles dans un bin provoquent un
   `ValueError` qui nomme la clé. Aucun volume n'est choisi silencieusement.
6. Un volume nul, négatif ou absent est refusé pour le calcul d'abondance.
7. `abundance_ind_L = copepod_count / sampled_volume_L` et
   `abundance_ind_m3 = abundance_ind_L * 1000`.
8. Les métadonnées ou variables environnementales contradictoires ne sont pas
   agrégées arbitrairement : le constructeur refuse le bin et nomme la colonne.

## Intégration agent

Le skill UVP importe et appelle le constructeur au lieu de reconstruire les bins
avec un `groupby` libre incluant le volume. Le system prompt impose cette voie
pour les tableaux, corrélations et datasets graphiques fondés sur une table UVP
EcoTaxa–EcoPart. Aucun nouveau tool LLM n'est ajouté : le calcul reste accessible
par l'analyse pandas existante.

## Validation TDD et E2E

Les tests unitaires couvrent :

- RA18/Calanoida inclus via la hiérarchie ;
- un bin positif et un bin échantillonné nul ;
- deux volumes quasi identiques consolidés en une ligne ;
- volumes réellement contradictoires refusés ;
- métadonnées contradictoires refusées ;
- égalité des comptes entre deux vues aval dérivées de la même table canonique.

Après la suite complète, un nouveau chat lancé par `curl` charge une fixture
représentative, construit une fois la table canonique, puis demande deux analyses
successives. La preuve attendue est le même compte RA18 dans les deux résultats,
avec les bins nuls conservés et aucune clé dupliquée.

## Hors périmètre

La définition m5/m6 et les choix scientifiques surface/fond ne sont pas modifiés
ici. Ce lot verrouille la granularité, les comptes par bin et les abondances
élémentaires ; les métriques de profil seront traitées séparément.
