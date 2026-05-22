# methodes_calcul.md
# Méthodes de calcul utiles pour l'assistant scientifique copépodes
# Format RAG — chaque section délimitée par --- est un chunk autonome

---
# Comment calculer une concentration en ind m⁻³ depuis EcoTaxa et EcoPart ?

La concentration en individus par mètre cube se calcule en comptant les objets EcoTaxa correspondant au taxon ou au groupe cible, puis en divisant ce nombre par le volume échantillonné donné par EcoPart.

Formule :
```text
volume_m3 = Sampled volume [L] / 1000
concentration_ind_m3 = nombre_individus / volume_m3
```

Colonnes requises :
```text
EcoTaxa :
- object_id
- obj_orig_id ou profile_id
- txo_display_name ou object_annotation_category
- obj_depth_min / obj_depth_max ou object_depth_min / object_depth_max

EcoPart :
- Profile
- Depth [m]
- Sampled volume [L]
```

Unités :
```text
nombre_individus : ind
Sampled volume [L] : L
volume_m3 : m3
concentration_ind_m3 : ind m-3
```

Limites :
- EcoTaxa sert à compter les objets individuels.
- EcoPart fournit le volume échantillonné.
- La jointure doit se faire par `profile_id` puis par profondeur proche.
- Si plusieurs bins EcoPart correspondent, garder `depth_delta_m` pour documenter le match.

Feedback si le calcul n'est pas possible :
- Si `Sampled volume [L]` est absent, expliquer que le comptage EcoTaxa reste un nombre brut, pas une concentration.
- Si les objets EcoTaxa ne sont pas reliés à un `Profile` EcoPart, proposer de vérifier `obj_orig_id`, `profile_id` ou la table de liaison.
- Si la profondeur de l'objet est hors de la plage EcoPart disponible, retourner le nombre d'objets et signaler que la concentration n'est pas fiable pour cette profondeur.
- Si le taxon ou le groupe cible n'est pas défini, demander de préciser le groupe avant calcul.

---
# Pourquoi EcoTaxa seul ne suffit pas pour calculer une concentration ?

EcoTaxa décrit des objets individuels et leurs annotations. Il ne fournit pas toujours le volume d'eau échantillonné nécessaire pour transformer un comptage en concentration.

Formule :
```text
concentration = nombre_individus / volume_echantillonne
```

Colonnes requises :
```text
EcoTaxa :
- object_id
- taxon / annotation

EcoPart :
- Sampled volume [L]
```

Unités :
```text
nombre_individus : ind
volume_echantillonne : L ou m3
concentration : ind m-3
```

Limites :
- EcoTaxa permet de compter des objets, mais un nombre brut n'est pas une concentration.
- Le volume échantillonné dépend du profil, de la profondeur et de l'instrument.
- Pour UVP, EcoPart est la source attendue pour le volume échantillonné.

Feedback si le calcul n'est pas possible :
- Si seul EcoTaxa est disponible, fournir un comptage par taxon, profil ou profondeur, mais preciser que ce n'est pas une concentration.
- Si l'utilisateur demande une concentration sans volume, indiquer que la colonne attendue est `Sampled volume [L]` dans EcoPart.
- Si le volume vient d'un autre profil ou d'une autre profondeur non reliée, expliquer que la jointure doit être validée avant usage.

---
# Comment calculer une biomasse en mg C m⁻² ?

La biomasse integree en mg C m⁻² se calcule en deux etapes : obtenir une biomasse volumique par profondeur, puis sommer sur l'epaisseur des bins.

Formule :
```text
biomasse_mgC_m3 = concentration_ind_m3 * masse_carbone_mgC_ind
biomasse_mgC_m2 = somme(biomasse_mgC_m3 * epaisseur_bin_m)
```

Colonnes requises :
```text
- concentration_ind_m3
- masse_carbone_mgC_ind
- epaisseur_bin_m
```

Unités :
```text
concentration_ind_m3 : ind m-3
masse_carbone_mgC_ind : mg C ind-1
epaisseur_bin_m : m
biomasse_mgC_m3 : mg C m-3
biomasse_mgC_m2 : mg C m-2
```

Limites :
- La masse carbone individuelle doit venir d'une mesure directe ou d'une relation taille -> carbone validee.
- La biomasse integree depend du choix des bins de profondeur.
- La formule ne doit pas être appliquée à des taxons mélangés si la masse carbone diffère fortement entre groupes.

Feedback si le calcul n'est pas possible :
- Si `masse_carbone_mgC_ind` est absente, proposer de s'arrêter à la concentration ou au biovolume disponible.
- Si aucune relation taille -> carbone validee n'est fournie, expliquer que la biomasse carbone serait une hypothese non documentee.
- Si l'epaisseur des bins n'est pas connue, calculer seulement une biomasse volumique si les autres colonnes sont presentes.
- Si les unités ne peuvent pas être converties de façon fiable, lister les unités trouvées et demander une convention de conversion.

---
# Quelles colonnes sont nécessaires pour calculer une biomasse ?

Pour calculer une biomasse, il faut au minimum une abondance ou concentration, une masse carbone individuelle, et une information de profondeur si l'on veut integrer sur la colonne d'eau.

Formule :
```text
biomasse_mgC_m3 = concentration_ind_m3 * masse_carbone_mgC_ind
biomasse_mgC_m2 = somme(biomasse_mgC_m3 * epaisseur_bin_m)
```

Colonnes requises :
```text
Obligatoires :
- concentration_ind_m3
- masse_carbone_mgC_ind

Pour integration verticale :
- depth_min
- depth_max
ou
- Depth [m]
- epaisseur_bin_m
```

Unités :
```text
concentration_ind_m3 : ind m-3
masse_carbone_mgC_ind : mg C ind-1
depth / epaisseur_bin_m : m
```

Limites :
- EcoPart peut fournir des concentrations/biovolumes agregees, mais pas toujours une biomasse carbone par individu.
- EcoTaxa peut fournir des mesures image, mais pas directement une masse carbone.
- Une conversion taille -> carbone doit être documentée avant usage.

Feedback si le calcul n'est pas possible :
- Si la masse carbone individuelle est inconnue, produire une table des colonnes disponibles et indiquer la colonne manquante.
- Si la variable disponible est un biovolume sans conversion biovolume -> carbone, proposer de rapporter le biovolume au lieu de la biomasse carbone.
- Si la demande mélange des unités incompatibles, afficher les unités détectées et demander quelle conversion appliquer.

---
# Comment calculer le lipid fullness depuis une image ?

Le lipid fullness est un ratio entre la surface du sac lipidique et la surface du prosome. C'est un proxy de condition corporelle, pas une masse de lipides directe.

Formule :
```text
lipid_fullness = surface_lipide / surface_prosome
```

Colonnes requises :
```text
- surface_lipide
- surface_prosome
```

Unités :
```text
surface_lipide : pixel2 ou mm2
surface_prosome : pixel2 ou mm2
lipid_fullness : ratio sans unite
```

Limites :
- Les deux surfaces doivent venir de la meme image ou du meme individu.
- Les surfaces doivent être dans la même unité.
- Le lipid fullness est un proxy image ; il ne remplace pas une mesure biochimique de lipides totaux.

Feedback si le calcul n'est pas possible :
- Si `surface_lipide` est absente, expliquer que l'export ne contient pas encore la segmentation du sac lipidique.
- Si `surface_prosome` est absente, expliquer que le ratio ne peut pas être normalisé par la taille de l'individu.
- Si les surfaces ne correspondent pas au meme individu, demander ou chercher un identifiant commun.
- Si l'utilisateur demande une masse de lipides sans calibration, proposer de calculer seulement un indice relatif si les surfaces existent.

---
# Quelles colonnes sont nécessaires pour calculer le lipid fullness ?

Le calcul necessite une mesure de surface du lipide et une mesure de surface du prosome. Les colonnes exactes dependent du pipeline d'imagerie du labo.

Formule :
```text
lipid_fullness = surface_lipide / surface_prosome
```

Colonnes requises :
```text
Obligatoires :
- surface_lipide
- surface_prosome
- identifiant_individu

Optionnelles :
- species / taxon
- stage
- station
- date_time
- depth
```

Unités :
```text
surface_lipide : pixel2 ou mm2
surface_prosome : pixel2 ou mm2
lipid_fullness : ratio sans unite
```

Limites :
- Les exports EcoTaxa testés ne contiennent pas directement `surface_lipide` et `surface_prosome`.
- Les colonnes peuvent venir d'un fichier labo local, pas d'EcoTaxa public.
- Les noms réels des colonnes labo doivent être confirmés sur un fichier réel.

Feedback si le calcul n'est pas possible :
- Si les colonnes de surface ne sont pas présentes, dire que le fichier permet peut-être la taxonomie ou la morphométrie, mais pas le lipid fullness.
- Si le fichier ne permet pas d'identifier l'individu, demander une colonne d'identifiant stable.
- Si les surfaces sont déjà normalisées mais que leur définition est inconnue, demander la définition avant de comparer les valeurs.

---
# Comment calculer la longueur du prosome depuis fre_feret ?

`fre_feret` est une mesure morphométrique image. Pour l'interpréter comme longueur biologique, il faut convertir les pixels en millimètres avec la taille de pixel de l'acquisition.

Formule :
```text
longueur_mm = fre_feret * acq_pixel
```

Colonnes requises :
```text
EcoTaxa :
- fre_feret

Métadonnées acquisition :
- acq_pixel
```

Unités :
```text
fre_feret : pixel
acq_pixel : mm pixel-1
longueur_mm : mm
```

Limites :
- `fre_feret` est un proxy de longueur, pas toujours la longueur anatomique exacte du prosome.
- L'objet doit être correctement segmenté.
- La conversion depend de `acq_pixel`, qui peut varier selon l'instrument ou l'acquisition.

Feedback si le calcul n'est pas possible :
- Si `fre_feret` est absent, lister les autres mesures morphométriques disponibles.
- Si `acq_pixel` est absent, garder `fre_feret` en pixels et signaler que la taille biologique en mm n'est pas calculable.
- Si l'objet est un artefact, un detritus ou une classe non biologique, exclure l'objet du calcul et expliquer pourquoi.
- Si l'utilisateur demande une identification espèce basée uniquement sur la longueur, rappeler que la taxonomie doit venir de l'annotation ou d'une validation experte.

---
# Pourquoi convertir fre_feret avant d'interpréter une taille biologique ?

`fre_feret` est mesure dans l'espace image. Sans conversion par `acq_pixel`, la valeur n'est pas une taille biologique comparable entre instruments, acquisitions ou projets.

Formule :
```text
longueur_mm = fre_feret * acq_pixel
```

Colonnes requises :
```text
- fre_feret
- acq_pixel
- acq_instrument ou métadonnées instrument
```

Unités :
```text
fre_feret : pixel
acq_pixel : mm pixel-1
longueur_mm : mm
```

Limites :
- Deux images avec le même `fre_feret` peuvent correspondre à deux tailles réelles différentes si `acq_pixel` diffère.
- Les mesures image ne corrigent pas toutes les erreurs de posture, orientation ou segmentation.
- Pour distinguer certaines espèces proches, la taille seule peut être insuffisante.

Feedback si le calcul n'est pas possible :
- Si `acq_pixel` est manquant, autoriser seulement une comparaison interne en pixels dans le meme export, avec avertissement.
- Si la calibration pixel n'est pas connue entre instruments, separer les resultats par instrument au lieu de les fusionner.
- Si l'utilisateur veut une identification taxonomique fine avec `fre_feret` seul, repondre que la taille peut aider au filtrage mais ne suffit pas comme preuve taxonomique.

---
# Comment associer une variable CTD à un objet EcoTaxa ?

Pour associer une variable CTD à un objet EcoTaxa, il faut relier l'objet à son profil, puis choisir la ligne CTD la plus proche en profondeur.

Formule :
```text
profile_id = extraire depuis obj_orig_id
object_depth = (obj_depth_min + obj_depth_max) / 2
match = meme profile_id + profondeur CTD la plus proche
depth_delta_m = abs(object_depth - ctd_depth)
```

Colonnes requises :
```text
EcoTaxa :
- obj_orig_id
- obj_depth_min
- obj_depth_max

EcoPart :
- Profile
- Depth [m]
- temperature [degc]
- practical salinity [psu]
- oxygen [umol kg-1] ou oxygen [ml l-1]
- chloro fluo [mg chl m-3]
- nitrate [umol l-1]

Amundsen optionnel :
- cast_number
- station
- time
- latitude / longitude
- depth
- TE90 / PSAL / OXYM / FLOR / NTRA
```

Unités :
```text
depth_delta_m : m
temperature : degC
salinity : PSU/psu
oxygen : selon source
fluorescence : selon source
nitrate : selon source
```

Limites :
- EcoPart est la source la plus directe pour associer CTD/particules aux objets UVP.
- Amundsen est la CTD officielle ; elle se joint par proximite date/heure + lat/lon + profondeur.
- Il faut conserver `depth_delta_m` pour documenter la qualite de la jointure.

Feedback si le calcul n'est pas possible :
- Si `profile_id` ne peut pas être extrait ou associé, proposer une vérification par date/heure, station et position.
- Si aucune profondeur n'est disponible, expliquer que la CTD ne peut pas être associée à l'échelle individuelle.
- Si le delta de profondeur est trop grand pour l'analyse demandee, retourner le meilleur match avec `depth_delta_m` et signaler la faible fiabilite.
- Si la source CTD n'est pas citee, demander de choisir entre EcoPart et Amundsen officiel.

---
# Comment répondre quand un calcul scientifique n'est pas fiable ?

L'assistant doit éviter d'inventer un résultat. Quand les données sont incomplètes, il doit expliquer ce qui manque et proposer le niveau d'analyse encore possible.

Formule :
```text
niveau_reponse = calcul_fiable
              ou calcul_exploratoire_avec_avertissement
              ou feedback_colonnes_manquantes
```

Colonnes requises :
```text
Pour chaque calcul :
- variables sources
- unités
- identifiants de jointure
- methode validee
- source des données
```

Unités :
```text
Les unités doivent être explicites ou convertibles.
```

Limites :
- Une réponse partielle doit expliquer ce qui manque.
- Un graphique exploratoire peut être produit si ses limites sont explicites.
- Une hypothèse scientifique doit être séparée d'un résultat calculé.

Feedback si le calcul n'est pas possible :
- Si les colonnes requises sont absentes, lister les colonnes manquantes et les colonnes disponibles proches.
- Si les unités sont inconnues ou incompatibles, demander la définition ou proposer une inspection du dictionnaire de données.
- Si la jointure entre sources n'est pas validee, produire d'abord un rapport de jointure avec deltas temps/position/profondeur.
- Si le calcul demande une relation biologique non fournie, signaler que la relation doit venir de la litterature, du labo ou d'une specification.
- Si l'utilisateur demande une conclusion taxonomique ou physiologique non supportée, reformuler en analyse exploratoire ou en vérification de données.
