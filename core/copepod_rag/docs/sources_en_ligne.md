# sources_en_ligne.md
# Sources en ligne autorisées pour l'assistant copépodes
# Format RAG — chaque section délimitée par --- est un chunk autonome

---

# Quelle source utiliser pour quelle question ?

Mots-clés : sources en ligne, EcoTaxa, EcoPart, Amundsen CTD, OGSL, Bio-ORACLE, données labo, Mode En Ligne

| Question du chercheur | Source à utiliser |
|---|---|
| "Je veux les annotations taxonomiques de ma campagne" | EcoTaxa |
| "Je veux les objets individuels et la morphométrie image" | EcoTaxa |
| "Je veux les profils UVP avec CTD et volume échantillonné" | EcoPart |
| "Je veux calculer une concentration à partir d'objets EcoTaxa" | EcoTaxa + EcoPart |
| "Je veux une CTD officielle de campagne" | CTD externe, priorité Amundsen ERDDAP si disponible |
| "Je veux mes données de comptage filet, lipides ou biomasse" | Données labo, fichier local |
| "Je veux contextualiser avec des données régionales du golfe du Saint-Laurent" | OGSL |
| "Je veux extraire des conditions environnementales actuelles ou futures à des coordonnées" | Bio-ORACLE |

**Règle générale :**
- Les sources en ligne ne sont jamais appelées silencieusement.
- Le Mode En Ligne doit être activé par source.
- Si une source n'est pas activée, l'agent travaille avec les fichiers chargés et le RAG local.
- Les IDs de projets ou datasets sont découverts dynamiquement ou fournis par l'utilisateur ; ils ne sont pas des constantes système.

---

# Comment accéder à EcoTaxa ?

Mots-clés : EcoTaxa, annotations taxonomiques, objets individuels, morphométrie, validation humaine, credentials, export authentifié

**Ce que ça contient :** annotations taxonomiques, statut de validation, morphométrie image, métadonnées d'objet et parfois images/vignettes.

**Niveau :** objet individuel.

**Accès :** compte requis pour les exports complets. Credentials locaux dans `.env`, jamais commités.

**Workflow recommandé :**
1. découvrir les projets accessibles à l'utilisateur ;
2. sélectionner le projet demandé ;
3. lancer un export authentifié ;
4. attendre le job async ;
5. télécharger le ZIP/TSV ;
6. inspecter colonnes, validation, profondeur, taxon, morphométrie ;
7. travailler sur une copie ou table dérivée.

**Limites :**
- EcoTaxa ne fournit pas nécessairement le volume échantillonné ;
- poids, lipides et biomasse ne sont pas garantis dans les exports ;
- les annotations automatiques ne remplacent pas une validation humaine.

---

# Comment accéder à EcoPart ?

Mots-clés : EcoPart, profils UVP, bins de profondeur, volume échantillonné, particules, CTD, concentration, jointure

**Ce que ça contient :** profils UVP agrégés par bin de profondeur, variables environnementales associées, volume échantillonné, particules et biovolume par classes de taille.

**Niveau :** profil + profondeur, pas objet individuel.

**Accès :** compte requis selon les datasets ; souvent mêmes identifiants que les services EcoTaxa/EcoPart.

**Usage principal :**
- récupérer `Sampled volume [L]` ;
- rapprocher objets EcoTaxa et volume par `profile_id` + profondeur ;
- calculer des concentrations quand la jointure est valide.

**Limite :** EcoPart ne décrit pas les taxons individuels. Il doit être joint avec EcoTaxa pour les analyses taxonomiques objet-level.

---

# Comment accéder à une CTD externe ?

Mots-clés : CTD externe, Amundsen ERDDAP, température, salinité, oxygène, fluorescence, nitrate, cast, station, profondeur

**Ce que ça contient :** température, salinité, oxygène, fluorescence, nitrate et autres variables physico-chimiques mesurées indépendamment.

**Accès :** dépend du fournisseur. Certains datasets sont publics via ERDDAP ; d'autres nécessitent formulaire ou compte.

**Paramètres typiques :**
- fenêtre temporelle ;
- latitude/longitude ;
- profondeur ou pression ;
- variables (`temperature`, `salinity`, `oxygen`, `fluorescence`, `nitrate` ou alias).

**Règle de jointure :** sauf clé explicite, joindre par proximité date/heure + latitude/longitude + profondeur.

**Limite :** une CTD externe est une source distincte des capteurs associés à l'UVP. Ne pas mélanger les provenances sans métadonnées.

---

# Comment utiliser les données internes du labo ?

Mots-clés : données labo, fichier local, CSV, TSV, Excel, lipides, biomasse, comptage filet, structure inconnue

**Ce que ça contient :** comptages filet, mesures lipidiques, biomasse carbone, stades manuels ou autres mesures produites par le labo.

**Accès :** fichier local chargé par l'utilisateur.

**Règle :** ne jamais supposer les colonnes avant inspection.

Workflow :
1. inspecter le fichier ;
2. détecter séparateur, encodage, feuilles Excel si besoin ;
3. inférer les rôles sémantiques des colonnes ;
4. demander clarification si un rôle critique est ambigu ;
5. créer une table de travail dérivée pour nettoyage ou jointure.

---

# Comment utiliser OGSL ?

Mots-clés : OGSL, golfe du Saint-Laurent, source régionale, profils environnementaux, données complémentaires

**Ce que ça contient :** données et métadonnées régionales utiles pour contextualiser des observations dans le golfe du Saint-Laurent, selon les jeux disponibles.

**Accès :** à implémenter dans les tools ; consulter les métadonnées/source avant d'affirmer la disponibilité d'un jeu de données.

**Quand l'utiliser :**
- contexte régional ;
- profils ou séries environnementales complémentaires ;
- comparaison avec une couverture locale quand les données existent.

**Métadonnées obligatoires si utilisé :**
- source OGSL ;
- jeu de données ou profil ;
- zone/station ;
- période ;
- variables ;
- méthode d'extraction ;
- limites de couverture connues.

**Limite :** OGSL est complémentaire. Si une CTD officielle de campagne couvre le besoin, elle est prioritaire.

---

# Comment utiliser Bio-ORACLE ?

Mots-clés : Bio-ORACLE, environnement, conditions futures, scénario, modèle, coordonnées, raster, extraction

**Ce que ça contient :** variables environnementales actuelles ou futures, souvent sous forme de grilles/raster.

**Usage :**
- extraire des conditions environnementales à des coordonnées ou dans une zone ;
- contextualiser des observations locales avec des variables environnementales ;
- préparer des graphiques couplés zooplancton/environnement.

**Bio-ORACLE ne sert pas à :**
- valider un taxon ;
- confirmer une observation de copépode ;
- interpréter biologiquement un résultat.

**Métadonnées obligatoires si utilisé :**
- variable environnementale ;
- scénario ou modèle si disponible ;
- période ;
- coordonnées ou zone ;
- méthode d'extraction/interpolation ;
- source Bio-ORACLE.

---

# Quelles sources sont exclues du prompt cible ?

Mots-clés : sources exclues, OBIS, CMEMS, dette documentaire, prompt cible, source non autorisée

Le prompt cible autorise EcoTaxa, EcoPart, CTD externe, OGSL, Bio-ORACLE et fichiers labo.

OBIS et CMEMS peuvent apparaître dans d'anciennes specs, notes ou scénarios historiques, mais ne sont pas des sources autorisées dans le prompt cible actuel.

Règle :
- ne pas implémenter de requête OBIS/CMEMS sans décision explicite de réintégration ;
- si un ancien scénario mentionne OBIS/CMEMS, le traiter comme dette documentaire à réviser ;
- proposer OGSL, Bio-ORACLE, CTD externe ou RAG local selon la question.

---

# Quels sont les pièges courants avec les sources en ligne ?

Mots-clés : pièges sources, credentials, Mode En Ligne, hardcode, source activée, données brutes, métadonnées

| Piège | Règle |
|---|---|
| Appeler une source sans consentement | Exiger Mode En Ligne activé pour cette source |
| Hardcoder un project_id | Découvrir dynamiquement ou utiliser l'ID fourni par l'utilisateur |
| Exposer un credential | Ne jamais afficher token, mot de passe, cookie ou `.env` |
| Écraser les données brutes | Toujours créer une table dérivée |
| Mélanger sources sans méthode | Documenter jointure, filtres, unités et limites |
| Confondre absence de donnée et absence biologique | Présenter comme limite technique, pas conclusion scientifique |
| Répondre avec une source non autorisée | Bloquer ou proposer une source autorisée |

_Dernière mise à jour : mai 2026_
