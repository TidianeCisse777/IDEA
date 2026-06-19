# Enrichissement Environnemental — Ce Que Tu Peux Demander

Tu as chargé un fichier de samples (EcoTaxa, EcoPart, ou un fichier lab).
Tu veux y ajouter des variables océanographiques. Voici ce que l'agent
sait faire.

## Trois Sources Disponibles

| Source | Ce qu'elle apporte | Couverture |
|---|---|---|
| **Amundsen CTD** | Température, salinité, pression mesurées in situ par les missions Amundsen Science. | Arctique canadien, mer de Beaufort, baie de Baffin, baie d'Hudson. |
| **OGSL ISMER CTD** | Température, salinité, oxygène dissous mesurés in situ par les campagnes ISMER. | Saint-Laurent, golfe du Saint-Laurent. |
| **Bio-ORACLE** | Variables modélisées : température, salinité, oxygène, chlorophylle, nitrate — historique (baseline) ou projections climatiques (SSP1-2.6, SSP2-4.5, SSP5-8.5). | Mondiale, sur grille. |

## Ce Qu'il Faut Dans Le Fichier

Une seule condition pour les trois sources : **latitude, longitude, et
une date** (sauf Bio-ORACLE qui se contente de lat/lon). Les noms
courants sont reconnus automatiquement (`latitude`, `lat`, `object_lat`,
`object_date`, `date`, `time`, etc.).

Une colonne de profondeur (`depth`, `object_depth_min`, `pres`…) est
optionnelle mais améliore le matching CTD.

## Phrasings Qui Marchent

### Enrichir simplement

- `Enrichis ce fichier avec la CTD Amundsen.`
- `Ajoute la température et la salinité OGSL.`
- `Enrichis avec Bio-ORACLE température en surface.`

### Plusieurs scénarios Bio-ORACLE en une fois

- `Compare baseline, SSP1-2.6 et SSP5-8.5 sur la température.`
- `Bio-ORACLE température + salinité, horizon 2050.`

### Régler la sévérité du match

- `Enrichis avec Amundsen, tolérance 50 km et 48 h.`
- `OGSL avec tolérance temporelle relâchée.`

### Plusieurs fichiers en session

Si tu as chargé deux fichiers (par ex. filet + UVP), précise lequel
enrichir :

- `Enrichis le fichier filet avec Bio-ORACLE.`
- `Enrichis l'UVP avec Amundsen.`
- `Fais les deux fichiers indépendamment avec OGSL.`

### Chaîner les trois sources sur le même fichier

- `Enrichis avec Amundsen, puis avec OGSL, puis avec Bio-ORACLE.`
- `Ajoute toutes les variables environnementales disponibles.`

## Ce Que Tu Récupères

Chaque enrichissement renvoie :

- **ton fichier complet, ligne pour ligne**, avec les colonnes
  environnementales ajoutées en fin (température, salinité, oxygène
  selon la source) ;
- **un statut par ligne** : `matched` (valeur trouvée), `matched_no_value`
  ou `no_value` (point/profil trouvé mais variable manquante à l'origine),
  `no_match` (zone hors couverture ou hors tolérance) ;
- **la qualité du match** : distance en km au point CTD retenu et écart
  temporel en minutes ;
- **un bloc « Méthode »** récapitulant les colonnes détectées, les
  tolérances utilisées, et les comptes par statut ;
- **un lien de téléchargement** du fichier enrichi.

Le résultat reste accessible en session : tu peux le tracer, le
filtrer, l'agréger sans recharger.

## Après L'enrichissement

Tu peux enchaîner naturellement :

- `Affiche les 10 premières lignes enrichies.`
- `Trace la température Amundsen vs la profondeur du sample.`
- `Filtre les lignes matchées.`
- `Compare baseline et SSP5-8.5 par station.`
- `Exporte le fichier enrichi en TSV.`
- `Génère un livrable PDF avec ces résultats.`

## Cas Particuliers

L'agent gère aussi ces situations sans que tu aies à les anticiper :

- **Ton fichier porte déjà des identifiants natifs** (un export EcoPart
  avec `station` + `cast_number` Amundsen, ou un fichier OGSL avec
  `stationID`) → l'agent utilise un matching exact au lieu de
  l'approximation lat/lon/temps.
- **Tu veux les top N stations** d'un fichier zooplancton enrichies
  avec Bio-ORACLE → demande `top 10 stations` ou `les mêmes stations`
  et l'agent construit la table avant d'enrichir.

## Limites À Connaître

- L'agent **n'invente pas** de valeur quand la zone-temps n'est pas
  couverte par la source ; il marque `no_match`. Pas d'extrapolation,
  pas de remplissage.
- **Pas d'interprétation biologique** dans la réponse. Les valeurs sont
  livrées brutes ; à toi (ou aux skills d'analyse) de les lire.
- Sources autorisées uniquement : **Amundsen, OGSL, Bio-ORACLE**.
  Pas d'OBIS, pas de World Ocean Atlas, pas d'autres bases.
- **Opérations lourdes** (Bio-ORACLE sur >10 lignes × plusieurs scénarios,
  export PDF, téléchargement complet d'un dataset) demandent une
  confirmation explicite (`oui`, `go`, `lance`) avant exécution.

Pour les détails techniques (tolérances par défaut, statuts par mode,
noms de colonnes exacts produits), voir
[`ENRICHMENT_CAPABILITIES.md`](ENRICHMENT_CAPABILITIES.md).
