# Comparaison filet–UVP6 : protocole Calanus et variantes explicites

Mots-clés : filet, UVP6, Calanus, Hydrobios, EcoPart, comparaison, C4, C5,
adultes, taille, 3 mm, object_major, acq_pixel, ind/m3, ind/m2, profil

## Méthode par défaut

La comparaison Calanus UVP6–Hydrobios a deux grains complémentaires.

1. **Tranche de profondeur** : comparer seulement le même intervalle vertical,
   avec le même taxon et une densité en `ind./m³` de chaque côté.
2. **Profil** : intégrer chaque densité de tranche sur son épaisseur, puis
   sommer en `ind./m²`. Ne jamais faire la moyenne simple des strates.

Le filet conserve *Calanus* C4+C5+M+F, exclut `Calanus spp.` non résolu et
exclut C4 de *Calanus finmarchicus* pour le protocole Calanus par défaut.

L'UVP6 part de candidats Copepoda/Copepoda-lipidsac, retire les images qui ne
peuvent pas correspondre au groupe ciblé (antenne, œufs, mort, fragment,
Cyclopoida, Harpacticoida, Heterorhabdus, Paraeuchaeta, Metridia), puis garde
les images dont `object_major × acq_pixel / 1000 ≥ 3 mm`. Une segmentation
manuelle documentée est l'unique exception au seuil. Sans calibration image,
taille réelle non calculable : la comparaison est bloquée.

## Variantes demandées par l'utilisateur

Les paramètres peuvent être changés explicitement : taxon, stades filet,
seuil UVP, fenêtre verticale et niveau de sortie (strates ou profil). Ils ne
doivent jamais être devinés. Toute variante doit être enregistrée avec le
résultat : elle est une méthode déclarée, pas le protocole Calanus par défaut.

Pour un autre taxon, filtrer le même nom taxonomique dans le filet et dans les
annotations UVP, vérifier que l'identification UVP le permet, et conserver le
seuil de taille choisi. Ne pas appliquer l'exclusion `C. finmarchicus C4` ni
les exclusions Calanus spécifiques à un autre taxon.

## Limites et provenance

Un appariement EcoTaxa/EcoPart doit garder la certification CTD. Deux fichiers
locaux peuvent être comparés sur un identifiant de profil/cast commun explicite,
mais le résultat reste `exploratory` et non certifié CTD. Un nom de station
réutilisé seul n'est pas une clé de profil suffisante.

### Garde-fou : les trois rôles de fichiers locaux

Une comparaison locale calculable requiert une **table Filet** contenant la
mesure d'abondance et ses champs de profondeur/unité, une **table UVP/EcoPart**
contenant objets, volume et profondeur, puis éventuellement une **table de
correspondance** `net_sample_id → uvp_profile_id`.

La table de correspondance ne contient que des identifiants : ce n'est jamais
une table Filet et elle ne peut jamais fournir une abondance. Si la vraie table
Filet est absente, s'arrêter et demander ce fichier. Ne pas construire un proxy
à partir du nombre d'objets UVP, du nombre de `net_sample_id`, ni d'une classe
de taille EcoPart ; ne pas produire de graphique de comparaison dans ce cas.

Quand les trois rôles sont présents, utiliser l'outil de comparaison locale
pour le calcul. Il détecte une clé profil/cast exacte commune ou applique la
table de correspondance fournie; une station seule n'est jamais une clé. Si
plusieurs clés sont possibles, il bloque et les liste plutôt que de deviner.
`run_pandas` peut vérifier les colonnes, mais ne doit pas remplacer ce calcul
par une jointure ou une agrégation improvisée.

Un facteur empirique observé dans une campagne particulière ne devient jamais
une correction générale. Le RAG décrit le protocole ; le tool calcule et expose
les paramètres, unités, couverture verticale et exclusions effectives.
