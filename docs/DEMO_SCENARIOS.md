# Démonstration IDEA — quatre études de cas visuelles

## Objectif

La démonstration est préparée à l'avance sous la forme de quatre conversations
OpenWebUI. Elle montre comment un professeur ou un chercheur peut partir d'une
question concrète, explorer les données disponibles, cadrer une campagne, une
zone, des stations et une période, puis produire des cartes, des graphiques et
des profils verticaux.

Les conversations doivent rester naturelles : les prompts ne nomment pas les
outils internes et ne donnent pas à l'agent une procédure informatique. Ils
décrivent la question scientifique, le périmètre et le résultat attendu.

Les fichiers locaux utilisés sont :

- `data/neolabs/neolabs_abundance.csv`
- `data/neolabs/neolabs_sample.csv`

Les sources distantes montrées sont EcoTaxa, EcoPart, Amundsen CTD et
Bio-ORACLE.

## Les quatre conversations

| Scénario | Question principale | Visuels attendus |
|---|---|---|
| 1. Campagne NeoLabs 2018 | Comment l'échantillonnage et l'abondance varient-ils entre stations et profondeurs ? | Carte, couverture, taxons, profil vertical |
| 2. Station 24 et environnement | Dans quelles conditions océaniques le profil biologique a-t-il été observé ? | Profils CTD, relations biologiques, carte Bio-ORACLE |
| 3. Filet et UVP en 2024 | Quelles tranches de profondeur sont réellement comparables entre les deux méthodes ? | Carte des paires, comparaison normalisée, ratios, profil si la couverture le permet |
| 4. Explorer EcoTaxa en baie de Baffin | Quelles données UVP sont disponibles dans cette zone et que peut-on exporter ? | Carte, couverture, taxons, distribution verticale |

---

## Scénario 1 — Explorer une campagne NeoLabs de 2018

### Question

Comment la couverture d'échantillonnage et l'abondance des copépodes varient-elles
entre les stations et les profondeurs de la campagne 2018 ?

L'année 2018 est retenue parce qu'elle possède plusieurs stations et des traits
multistrates calculables. La station 24 fournit notamment une séquence de
tranches entre 0 et 160 m, adaptée à un profil vertical.

### Conversation OpenWebUI — 9 tours

1. « Charge les deux fichiers NeoLabs. Pour commencer, montre-moi clairement ce
   qu'ils contiennent et comment ils peuvent être reliés. »
2. « Concentre l'analyse sur la campagne 2018. Montre la couverture par station
   et par profondeur, avec les valeurs calculables et les valeurs manquantes. »
3. « Fais une carte des stations échantillonnées en 2018. La taille des points
   représente le nombre d'échantillons et la couleur leur profondeur maximale. »
4. « Ajoute un graphique qui compare l'effort d'échantillonnage entre les
   stations et les grandes classes de profondeur. »
5. « Quelles stations offrent les profils verticaux les plus complets ? Garde
   les quatre meilleures pour la suite. »
6. « Pour ces quatre stations, compare les cinq taxons de copépodes les plus
   abondants avec un graphique facile à lire. »
7. « Zoome maintenant sur la station 24 et trace le profil vertical de la
   densité totale de copépodes. Montre les limites des tranches de profondeur. »
8. « À côté du profil, montre la composition des principaux taxons selon la
   profondeur à cette station. »
9. « Termine par une synthèse visuelle de la campagne : stations couvertes,
   tranches calculables, valeurs manquantes et principales limites. »

### Visuels à conserver

- Carte de toutes les stations 2018.
- Matrice ou barres de couverture station × profondeur.
- Comparaison des taxons dominants entre quatre stations.
- Profil vertical de densité à la station 24.
- Composition taxonomique selon la profondeur.

### Message clé

L'agent passe du grain taxon au grain échantillon sans confondre les deux,
préserve les lignes non appariées et rend visibles les valeurs manquantes avant
toute comparaison.

---

## Scénario 2 — Relier le profil de la station 24 à l'environnement

### Question

Dans quelles conditions de température, salinité et oxygène le profil de
copépodes observé à la station 24 le 12 juin 2018 a-t-il été échantillonné, et
comment ce contexte se compare-t-il aux données climatiques disponibles ?

Ce scénario reprend une station découverte dans le premier parcours. Il montre
qu'une exploration peut devenir une analyse ciblée avec une station, une date
et des profondeurs précises.

### Conversation OpenWebUI — 10 tours

1. « Reprends uniquement la station 24 du 12 juin 2018 et garde toutes les
   tranches de profondeur disponibles. Montre-moi la sélection sur une petite
   carte. »
2. « Je veux ajouter les observations CTD du même déploiement. Quelles variables
   environnementales sont disponibles ? »
3. « Utilise la température, la salinité et l'oxygène. Montre d'abord la
   couverture obtenue et les profondeurs sans mesure. »
4. « Trace les profils verticaux complets de température et de salinité sur la
   même figure, avec la profondeur orientée vers le bas. »
5. « Ajoute le profil vertical d'oxygène et indique clairement quelles valeurs
   sont mesurées et lesquelles sont absentes. »
6. « Mets maintenant le profil de densité des copépodes à côté des trois profils
   environnementaux pour faciliter la comparaison visuelle. »
7. « Fais deux graphiques simples : densité des copépodes selon la température,
   puis selon la salinité. Garde la profondeur visible par la couleur. »
8. « Ajoute le contexte Bio-ORACLE pour cette position : température et salinité
   historiques, puis le scénario SSP5-8.5 en 2050. »
9. « Montre sur une carte le delta de température entre SSP5-8.5 et
   l'historique, en distinguant les lignes calculables des valeurs manquantes. »
10. « Résume ce que les observations CTD et les scénarios Bio-ORACLE permettent
    de comparer, sans tirer de conclusion biologique automatique. »

Si Bio-ORACLE demande une confirmation avant le calcul, ajouter un tour court :
« Oui, lance cet enrichissement. »

### Visuels à conserver

- Carte localisée de la station et du déploiement.
- Profils verticaux de température, salinité et oxygène.
- Figure biologique et environnementale alignée par profondeur.
- Relations densité–température et densité–salinité.
- Carte du delta Bio-ORACLE avec les valeurs absentes visibles.

### Message clé

Amundsen apporte des observations mesurées et Bio-ORACLE un contexte climatique.
L'agent les distingue, aligne correctement les profondeurs et ne calcule un
delta que lorsque les deux valeurs nécessaires existent.

---

## Scénario 3 — Comparer le filet et l'imagerie UVP en 2024

### Question

Pour les déploiements NeoLabs de 2024, quelles observations UVP sont réellement
comparables au filet, et comment les deux méthodes décrivent-elles la structure
verticale des copépodes ?

L'année 2024 est utilisée parce que l'audit réel a déjà confirmé des
correspondances de station, de temps, de position et de fichier CTD Amundsen.
La conversation doit toutefois recalculer et afficher sa propre sélection.

La correspondance UVP–filet et la disponibilité d'une abondance filet sont
deux couvertures distinctes. Pour le jeu de démonstration actuel, 395
prélèvements ont une correspondance UVP certifiée dans `neolabs_sample`, mais
seuls 2 de ces identifiants ont une abondance exploitable dans
`neolabs_abundance`. Les graphiques finaux sont donc descriptifs sur 2 paires,
et non une conclusion sur la campagne complète.

### Conversation OpenWebUI — 10 tours

1. « Prépare les données NeoLabs de 2024 pour une comparaison entre le filet et
   l'imagerie UVP. Montre d'abord les déploiements sur une carte. »
2. « Cherche les profils UVP correspondant à ces déploiements et vérifie les
   stations, les dates, les positions et les fichiers CTD communs. »
3. « Montre les paires certifiées sur une carte et indique combien de
   prélèvements filet disposent aussi d'une abondance comparable. »
4. « Prépare l'export EcoTaxa des profils certifiés avec les annotations
   validées. »
5. « Oui, lance cet export EcoTaxa. »
6. « Enrichis maintenant cette sélection avec EcoPart pour obtenir les volumes
   échantillonnés et les classes de profondeur. »
7. « Oui, lance l'enrichissement EcoPart. »
8. « Relie maintenant les abondances filet et UVP seulement dans les mêmes
   tranches de profondeur. Donne le nombre de paires disponibles et explique
   clairement si certaines métadonnées filet n'ont pas d'abondance associée. »
9. « Fais un visuel en deux panneaux : abondance normalisée filet contre UVP
   par tranche de profondeur, puis ratio UVP/filet. Indique le nombre de paires
   comparables dans le titre. »
10. « Si plusieurs stations ou profils sont comparables, ajoute un nuage de
    points avec ligne d'égalité et un profil vertical. Sinon, conserve les
    deux panneaux descriptifs et précise la limite de couverture. »

### Visuels à conserver

- Carte des déploiements NeoLabs 2024.
- Carte des correspondances certifiées et de leur couverture d'abondance.
- Comparaison d'abondance filet–UVP par tranche commune, en ind./m³.
- Ratio UVP/filet par tranche commune.
- Profil vertical et nuage de points avec ligne d'égalité seulement lorsque le
  nombre de paires et de stations le rend informatif.

### Message clé

Une proximité géographique n'est pas transformée en correspondance certaine.
La comparaison finale utilise les correspondances certifiées, le volume EcoPart
comme dénominateur et les mêmes intervalles de profondeur. Elle affiche aussi
sa couverture : une correspondance certifiée dans `neolabs_sample` ne garantit
pas qu'une abondance soit disponible dans `neolabs_abundance`. Les tranches
incomplètes restent visibles avec leur raison, sans être remplacées par zéro.

---

## Scénario 4 — Se déplacer dans EcoTaxa en baie de Baffin

### Question

Quelles observations UVP sont disponibles dans EcoTaxa en baie de Baffin en
2024, comment sont-elles réparties et quelles données validées peut-on exporter ?

Ce parcours reste entièrement centré sur EcoTaxa. Il montre que l'agent peut
explorer une zone sans connaître à l'avance les identifiants de projets ou de
samples, puis exporter une sélection précise.

### Conversation OpenWebUI — 10 tours

1. « Dans EcoTaxa, cherche ce qui est disponible en baie de Baffin en 2024. »
2. « Fais une carte de tous les samples UVP trouvés dans cette zone, avec une
   couleur par projet. »
3. « Compare les projets par nombre de samples, période couverte et nombre
   d'objets. Fais un graphique de couverture. »
4. « Montre comment les samples se répartissent entre les stations et au cours
   de la campagne. »
5. « Choisis le projet qui offre la meilleure couverture dans la zone et
   présente ses stations principales. »
6. « Pour ce projet, montre la proportion d'objets validés, prédits et non
   annotés. »
7. « Sélectionne les samples validés des trois stations les mieux couvertes et
   montre précisément ce qui sera exporté. »
8. « Prépare l'export de cette sélection avec uniquement les annotations
   validées. »
9. « Oui, lance cet export EcoTaxa. »
10. « À partir des données exportées, trace les principaux groupes taxonomiques
    et leur distribution verticale, puis donne le lien de téléchargement. »

### Visuels à conserver

- Carte des samples par projet.
- Graphique de couverture des projets.
- Répartition des samples par station et par date.
- Statut des annotations.
- Composition taxonomique et distribution verticale après export.

### Message clé

L'utilisateur n'a pas besoin de connaître les identifiants EcoTaxa. Il cadre une
zone et une période, explore les projets et les samples disponibles, construit
une sélection visible, puis confirme un export traçable.

---

## Règles de réalisation des conversations

- Créer une conversation OpenWebUI distincte pour chaque scénario.
- Donner à chaque conversation un titre court comprenant la campagne ou la zone.
- Exécuter les tours un par un et vérifier le résultat avant de poursuivre.
- Ne jamais corriger une réponse défaillante en inventant un chiffre dans le
  prompt suivant; corriger le périmètre ou la colonne explicitement.
- Conserver les cartes, graphiques et profils réussis dans la conversation.
- Utiliser des unités visibles sur tous les axes et toutes les légendes.
- Montrer les valeurs manquantes et les exclusions; ne jamais les remplacer par
  zéro.
- Séparer les confirmations EcoTaxa, EcoPart et Bio-ORACLE.
- Ne pas exposer les noms internes des outils dans les prompts de présentation.
- Décrire les résultats sans produire d'interprétation biologique automatique.

## Vérifications avant la présentation

- Les quatre conversations sont visibles et correctement nommées dans OpenWebUI.
- Chaque conversation contient au moins une carte et deux autres visuels.
- Les images restent accessibles après rechargement de la page.
- Les tables importantes affichent le total, le dénominateur calculable et les
  valeurs manquantes.
- Toute comparaison filet–UVP affiche séparément le nombre de correspondances
  certifiées et le nombre de prélèvements ayant une abondance filet disponible.
- Les exports EcoTaxa et EcoPart disposent d'un lien de téléchargement valide.
- Les profils verticaux utilisent une profondeur orientée vers le bas.
- Les sources et les unités sont visibles sans montrer les noms techniques des
  outils.
