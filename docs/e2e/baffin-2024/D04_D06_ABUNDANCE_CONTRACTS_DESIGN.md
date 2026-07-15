# D04–D06 — Contrats d'abondance et de corrélation

## Objectif

Empêcher trois dérives observées dans le scénario baie de Baffin : modifier la
formule d'abondance entre deux analyses, exclure implicitement les bins à zéro et
produire m5/m6 sans demande explicite.

## Abondance élémentaire

La table `df_canonical_sample_depth` reste l'unique source des abondances UVP
élémentaires par bin :

```text
abundance_ind_L  = copepod_count / sampled_volume_L
abundance_ind_m3 = abundance_ind_L × 1000
```

Les deux colonnes portent explicitement leur unité. Aucun alias ambigu comme
`abundance`, `density` ou `cop_dens` ne doit être créé dans le contrat canonique.
Le numérateur compte les lignes objets sélectionnées par la hiérarchie Copepoda ;
le dénominateur est l'unique volume EcoPart validé du bin. Les validations de
volume et les bins nuls restent celles du constructeur canonique D02–D03.

## Préparateur de corrélations

Ajouter dans `core/` une fonction pandas pure :

```python
prepare_environment_correlation(
    canonical: pd.DataFrame,
    environmental_columns: tuple[str, ...],
    *,
    abundance_column: str = "abundance_ind_L",
    presence_only: bool = False,
) -> pd.DataFrame
```

Règles :

1. La table doit porter `canonical_method_version == "copepod-sample-depth-v1"`.
2. `abundance_column` accepte uniquement `abundance_ind_L` ou
   `abundance_ind_m3`.
3. Par défaut, tous les bins échantillonnés sont conservés, y compris ceux où
   l'abondance vaut exactement zéro.
4. Seules les lignes dont une variable environnementale demandée est absente ou
   non numérique sont retirées ; le résultat expose le nombre initial, le nombre
   retenu et le nombre retiré pour environnement manquant dans ses attributs
   pandas.
5. `presence_only=True` autorise le filtre `abundance > 0`, mais cette option ne
   peut être utilisée par l'agent que si l'utilisateur demande explicitement une
   analyse de présence, de bins positifs ou de valeurs non nulles.
6. Une abondance négative, non numérique ou non finie provoque un refus.
7. Le préparateur ne calcule ni coefficient ni p-value : il produit le dataset
   déterministe que l'analyse statistique consommera.

## Routage agent

Pour toute relation ou corrélation entre abondance UVP et environnement, le skill
et le system prompt imposent le préparateur partagé. L'agent doit annoncer `n`
et le nombre de bins nuls utilisés. Il ne doit jamais écrire spontanément un
filtre `abundance > 0`.

Une demande générique « abondance », « densité », « profil d'abondance » ou
« relation avec la température » utilise les colonnes élémentaires de la table
canonique. Elle ne produit jamais m5/m6.

m5/m6 ne sont autorisés que lorsque :

- l'utilisateur écrit explicitement `m5` ou `m6` ; ou
- l'utilisateur demande clairement la métrique surface + fond / premiers et
  derniers 50 m.

Dans ce cas seulement, le skill peut appliquer la recette référencée et doit
nommer la métrique et sa méthode dans la réponse. Une demande ambiguë ne doit pas
être interprétée comme m5/m6.

## Tests et validation E2E

Les tests unitaires couvrent :

- conservation de bins positifs et nuls par défaut ;
- filtre présence seulement lorsque l'option est vraie ;
- retrait documenté des environnements manquants ;
- refus d'une table non canonique, d'une unité inconnue et d'une abondance
  invalide ;
- absence de routage m5/m6 pour une demande générique ;
- autorisation m5/m6 uniquement pour une intention explicite.

La validation curl utilise un nouveau chat multi-tour : création de la table
canonique, préparation d'une corrélation température–abondance incluant le bin
RA18 à zéro, puis demande générique d'abondance. Un second chat demande m5
explicitement afin de vérifier que cette voie reste disponible et documentée.

## Hors périmètre

Ce lot ne choisit pas automatiquement Pearson ou Spearman, ne fournit aucune
interprétation biologique et ne modifie pas la recette mathématique référencée de
m5/m6. Les contrats graphiques seront traités dans le lot dédié.
