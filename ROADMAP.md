# Planification de la refonte d’IDEA

**Période proposée :** du 14 septembre au 30 novembre 2026

**Dernière mise à jour :** 11 novembre 2026

### 12 novembre 2026 — FILET : engin sur chaque ligne, contexte et commentaires du labo

- Le classeur FILET ne donne que les libellés courts des engins (Hydrobios, 2x1m2, 4x1m2, 4x1m2 - LOKI, Bioness,
  Ringnet 1m, Ringnet 50cm; « hydrobios » une fois en minuscules), sans nom complet ni définition de V-Tow et O-Tow.
- Ajouté (`sql/warehouse_filet_context_migration.sql`, `populate_filet.py`) : `gear` et `tow_type` sur chaque ligne
  de `explore.filet_data` et `filet_totals`; profondeur du fond (5 934 échantillons), ouverture du filet (6 102),
  commentaires du labo (2 553 déploiements, 868 filets, 731 échantillons, 913 analyses); engin et trait dans le
  résultat de `filet_uvp_compare`. Fiches : sens de V-Tow et O-Tow donné d'après les commentaires (vertical 159 fois
  contre 1; oblique 21 fois contre 2), sans le présenter comme une définition du labo.
- Le FILET se recharge quand le chargeur change (empreinte CSV + chargeur). Vérifié dans le conteneur : rechargé
  une fois, puis plus; compte de lecture; audit d'accès vide; 170 tests.

### 12 novembre 2026 — Branche `mcp-neolab` : le warehouse et son serveur MCP seuls

- Branche partie de `work/warehouse-fair` (historique gardé), réduite au code utilisé par le warehouse et le
  serveur MCP : relais, déploiement, fiches, base de connaissances, chargeurs, image tout-en-un, installeurs,
  tests. Retirés : socle Hawaii (LangGraph, Open WebUI, sandbox, LiteLLM, Langfuse, nginx, compose de
  l'application), navigateur web du warehouse, docs et tests associés (376 → 129 fichiers).
- Migrations SQL déplacées de `docs/` vers `sql/`; service compose `warehouse-context` sur une petite image
  `docker/context` (le navigateur fournissait la sienne). README et AGENTS.md réécrits pour ce périmètre.
- Mise à jour Windows : branche par défaut `mcp-neolab`.
- Preuves : 170 tests réussis (28 sautés sans PostgreSQL); déploiement rejoué dans le conteneur, voir ci-dessous.

### 11 novembre 2026 — QA des données avant démo (compte de lecture, base chargée)

**Juste (preuves SQL, compte `lecture_mcp`)**
- Valeurs de référence retrouvées : am_leg3 69 574 validés; FILET 6 102 échantillons, 1 502 analyses, 4 941
  lignes appariées et 106 non; couples même station et 5 h : 232 déploiements, 167 profils UVP, 133 stations;
  UVP–CTD : 496 profils UVP, 453 profils CTD.
- Liens : 685 profils UVP sur 686 ont un sample EcoTaxa (manque `lc_2022_19_04`); 904 samples EcoTaxa reliés
  à 456 profils CTD, tous `accepted`; 12 151 035 objets sur 12 151 370 rattachés à une tranche UVP.
- Aucune tranche UVP à volume nul ou absent; aucune valeur sentinelle CTD; aucun objet de taxon inconnu;
  stades FILET d'un taxon tous connus ou tous NA (jamais partiels); écarts de temps filet–UVP centrés vers
  −1 h, sans décalage de fuseau visible (cohérent, non prouvé).

**Corrigé**
- Double compte (commit 93a95ce et suivant) : 199 profils GreenEdge 2016 liés à deux copies EcoTaxa identiques
  (149 et 20880/20890); `filet_uvp_compare` doublait l'abondance UVP (G707 : 634 → 317 objets). Un seul
  projet par profil; fiches des quatre vues UVP averties; chiffres de la note de méthode corrigés.
- Inconnu ≠ zéro : `esd_um` absent pour 11,4 M d'objets (UVP6 récents) alors que l'aire existe; ESD tiré de
  l'aire dans `uvp_object_sizes` et `ecotaxa_objects` (égal à l'ESD source là où les deux existent).
- Vues vides non annoncées (`filet_ctd`, `filet_uvp_abundance`, `taxon_mapping`) : toute vue à 0 ligne est
  maintenant signalée dans sa fiche et dans l'overview, à chaque déploiement.
- `uvp_object_sizes` expose `ecotaxa_sample_id` et `ecotaxa_project_id`.

**Reste faux ou douteux (par gravité)**
1. Source FILET : échantillon 22497 (station 308, 2010), volume débitmètre −4181,4 m³, d'où 111 abondances et
   78 biomasses négatives au débitmètre (`SELECT * FROM explore.filet_data WHERE abundance_flowmeter_ind_m3 < 0`).
   Données brutes gardées, fiche avertie : à corriger par le labo.
2. Corrigé ensuite : `explore.uvp_objects`, `uvp_object_sizes`, `uvp_samples` et `uvp_taxon_abundance` ne gardent
   qu'une copie par profil (plus petit projet EcoTaxa). Vérifié : `uvp_samples` 685 lignes pour 685 profils,
   `uvp_objects` 10 650 490 objets (−1 500 880), `ge_2016_185` 13 451 objets, am_leg3 et valeurs de référence
   inchangés. Les copies restent dans les vues `ecotaxa_*` (projets distincts dans EcoTaxa), fiches averties.
3. Rapports UVP/FILET médians de la note de méthode retirés (mesurés avec le double compte) : à remesurer.
4. Aucun lien FILET–CTD ni correspondance taxonomique FILET–UVP chargés; 2 analyses FILET ont COPEPODID connu
   pour certains taxons seulement (somme partielle possible); positions UVP absentes d'EcoPart pour 182
   profils GreenEdge (prises dans EcoTaxa par `filet_uvp_pairs`, NULL dans `uvp_samples`).
5. Non refait après ces corrections : questions à de vrais agents (point 9) et batterie; `filet_uvp_compare`
   sur toutes les stations prend 10 à 20 s (limite 30 s), 1 à 5 s avec `filet_stations`.

### 11 novembre 2026 — Base de connaissances, FILET chargé, comparaison FILET–UVP (phase 2)

- Documents écrits consultables par les agents (modèle des serveurs MCP de connaissances : chercher puis lire
  par identifiant) : `warehouse.document`/`document_section` (sécurité par ligne), `search_documents` (plein
  texte français/anglais sans accents), `read_document` (six sections à la fois). Chargés : revue FILET,
  descriptions et dictionnaires des trois feuilles de métadonnées du classeur FILET, note de méthode FILET–UVP.
- FILET chargé depuis les CSV du responsable (empreintes identiques à la revue du 18 septembre; dictionnaire
  absent, `--no-dictionary`) : 6 102 échantillons, 1 502 analyses, 4 941 lignes appariées et 106 non (les neuf
  couples 2024). `neolab-load-filet` charge le même export dans un conteneur installé.
- Classeur complet reçu : feuille « zooplankton abundances » (11 378 lignes, 421 couples, 275 taxons, grandes
  et petites fractions) analysée, non chargée; table de profils LOKI (192 lignes) reçue, non chargée.
- `explore.filet_uvp_pairs` et `explore.filet_uvp_compare` : paires par distance/temps/station, abondance UVP
  intégrée sur la couche du filet (tranches vides comprises), taxons, stades FILET (agrégats refusés avec
  leurs parties, vérifiés égaux à la somme), taille ESD ou grand axe, statut. Tests et chiffres dans le
  document `filet-uvp-comparaison`; `claude -p` l'a trouvé et utilisé. FILET–CTD : aucun lien construit.
- Positions UVP manquantes (182 profils GreenEdge 2016) prises dans les samples EcoTaxa
  (`uvp_position_source`); couples comptés par déploiement (`filet_deployment_id`) : même station et 5 h au
  plus, 232 déploiements filet, 167 profils UVP, 133 stations. `explore.filet_deployments` (engin, couches,
  mailles). Meilleurs couples copépodes inscrits dans `filet-uvp-comparaison`; `claude -p` les retrouve
  depuis le document (232 couples, critères repris). Variante Calanus à 50 km/72 h : dépasse 30 s.
- QA avant démo (agents réels, `claude -p`, compte de lecture) : (1) consigne précise « stations 133 et 134,
  filet C5+M+F contre UVP validés ESD ≥ 1,5 mm, même station, 5 h » appliquée à la lettre; l'agent a trouvé un
  bug (ESD absent d'Amundsen 2023 → 0 faux), corrigé (ESD tiré de l'aire, objets sans taille comptés, NULL au
  lieu de 0). (2) « carte des couples même station, 5 h » : fiche graphs lue, un point par déploiement,
  232/167/133 dans le titre, cartouche Exploratoire, PNG, SVG, CSV, script et provenance produits. Requêtes
  larges sur toutes les stations > 30 s : `filet_stations` (2 à 7 s). Tests warehouse : 144 réussis.
- Limites : compte à périmètre restreint non testé sur les documents; partie Windows du chargement FILET non
  encore lancée.

### 11 novembre 2026 — Image tout-en-un installée sur un PC Windows neuf; Codex Desktop branché (phase 2)

- Installation par `installer_windows.bat` (image construite depuis les zips) sur le PC Windows du
  responsable : réussie, mais longue (restauration de la base plus de 30 min avec 3,7 Go de mémoire alloués à
  Docker; 17,8 Go écrits). Un clic dans la fenêtre PowerShell met le script en pause (mode sélection).
- Codex en ligne de commande : serveur vu. Codex Desktop : « MCP startup failed: program not found » : lancée
  depuis le menu Démarrer, l'application ne trouvait pas `docker` (Docker Desktop installé dans
  `AppData\Local\Programs`, hors du PATH des applications). Correction : chemin complet de docker dans
  toutes les configurations (`register-apps --docker-command`, installeurs Windows et Mac) et nouveau
  `brancher_assistants_windows.bat` (`scripts/connect_assistants_windows.*`) qui rebranche Claude Code, Codex
  (`startup_timeout_sec = 60`), VS Code et Claude Desktop sans réinstaller.
- Preuve : après ce script, nouvelle conversation Codex Desktop, « combien d'objets validés dans am_leg3 » :
  69 574 (projet 14859, requête SQL et choix du projet affichés). Claude Desktop, VS Code et l'option
  `-CodexWsl` : non testés. Les zips déjà envoyés contiennent l'ancien installeur : à refaire avant partage.
- Outils renommés pour les agents par le relais : `read_data_guide`, `run_sql_query`,
  `find_tables_and_columns`, titres « NeoLab Warehouse · … » (Codex affiche le titre, Claude Code le nom).
  DbHub garde ses noms; la table `catalogue.warehouse_context` aussi. Vérifié : Claude Code (`claude -p`) voit
  les trois noms, les appelle et répond 69 574 pour am_leg3; titres vus dans Codex Desktop par le responsable.
- Mise à jour sans réinstaller : `scripts/update_warehouse_windows.*` (`mettre_a_jour_windows.bat`) prend le
  dernier commit de la branche sur GitHub (jeton lecture seule gardé chiffré par DPAPI), le copie dans le
  conteneur et lance `docker/allinone/neolab-update` (commandes du conteneur, déploiement relançable, dossier de
  travail, `neolab-check`); `-Auto` la lance à chaque ouverture de session. Partie conteneur vérifiée ici
  (PRÊT, PASS, 5 s sur une base déjà migrée); partie Windows non encore lancée.
- `scripts/publish_prebuilt_image.ps1` (image avec la base déjà installée, registre privé ghcr.io) : mécanisme
  vérifié sur une petite base (nouveau volume rempli, initialisation sautée); pas encore lancé sur la vraie
  base. Les mots de passe internes du conteneur sont dans l'image : elle doit rester privée.

### 10 novembre 2026 — État CTD / EcoPart mesuré; pH absent corrigé dans les textes (phase 2)

- CTD : 456 profils (2016 : 200, 2021 : 36, 2023 : 73, 2024 : 147), 5 130 421 mesures, 7 variables (PRES, TE90,
  FLOR, PSAL, SIGT, OXYM, NTRA; nitrate sur 469 318 mesures seulement), jusqu'à 2 130 m, `qc` jamais renseigné.
  Les 456 profils ont au moins une liaison acceptée à un sample EcoTaxa (904 liaisons); aucun lien direct
  UVP–CTD (`uvp_ctd` vide), chemin par les samples EcoTaxa.
- Aucune mesure de pH chargée, alors que le LISEZMOI, les fiches, les instructions du serveur, la description
  DbHub et le courriel préparé pour Cyril citaient le pH : textes corrigés (« pas de pH »). Le chargeur demande
  bien `pH` à ERDDAP; la source n'en fournit pas pour ce jeu.
- EcoPart : 12 projets, 686 profils (heure 686/686, sans position propre 183, AMBIGUOUS 13), 71 520 tranches toutes
  de 5 m, toutes avec volume (6 427 m³), 1 001 280 lignes de particules, 12 151 035 objets rattachés à une tranche;
  abondances : 492 415 lignes tous objets, 303 989 validés seulement. Projets UVP EcoTaxa sans profil EcoPart :
  13224 (extrait de 149) et 17808.

### 10 novembre 2026 — Applications de bureau branchées par l'installeur (phase 2)

- `warehouse_connect.py register-apps` : inscrit le serveur dans les applications installées (dossier de
  configuration présent), sans toucher au reste : Codex (`~/.codex/config.toml`, partagé par la ligne de commande
  et l'extension VS Code selon la documentation OpenAI; l'application de bureau n'est pas documentée
  officiellement), VS Code/Copilot (`Code/User/mcp.json`, clé `servers`), Claude Desktop
  (`claude_desktop_config.json`, clé `mcpServers`). Copie `.avant-neolab` du fichier d'origine; JSON illisible
  laissé tel quel; relançable sans doublon. Sous Windows, `installer_windows.ps1` l'appelle pour le profil
  Windows avec le serveur lancé dans Ubuntu par `wsl.exe -d <distro> --`.
- Le relais trouve Node hors du PATH (application lancée depuis le Finder : /opt/homebrew, /usr/local, /usr/bin).
- Tests : 4 tests unitaires (applications absentes non touchées, autres serveurs conservés, JSON illisible
  intact, commande wsl.exe); installeur relancé avec VS Code et Codex simulés : deux fichiers écrits; la commande
  inscrite dans `mcp.json`, lancée avec PATH=/usr/bin:/bin, répond en MCP (DBHub 1.5.0, 3 outils, requête SQL
  réussie). PowerShell analysé sans erreur. Non testé : les applications réelles (VS Code, Codex app, Claude
  Desktop) et `wsl.exe` sous Windows.

### 9 novembre 2026 — Installeurs Windows et macOS (phase 2)

- `installer_windows.bat` (double-clic) → `installer_windows.ps1` : Ubuntu (WSL) s'il manque (redémarrage puis
  relance), Docker Desktop par winget, attente de Docker dans Ubuntu (intégration WSL), second zip retrouvé et
  décompressé, dossier copié dans Ubuntu, puis `installer.sh`. `installer_mac.command` (double-clic) → `installer.sh`.
- `installer.sh` installe désormais les outils manquants : Homebrew, Python, Node, libpq et Docker Desktop
  (macOS); python3-venv, client PostgreSQL 16 (pgdg) et Node 22 (NodeSource) avec apt; sudo seulement hors root;
  propose Claude Code si aucun assistant n'est installé; retrouve le second morceau dans un dossier voisin (Finder
  : « … 2 ») ou décompresse le second zip (à côté, ou dans Téléchargements).
- Tests : outils installés par le script sur Ubuntu 24.04 et 22.04 vierges (psql 16.15, Node 22, Python 3.12 et
  3.10 avec venv, 52 et 54 s); installation complète par `installer_mac.command` sur volume vierge avec les zips
  décompressés « à la Finder » : 3 min 05 s, `PRÊT`, `PASS`, Claude Code branché; second zip laissé fermé dans
  Téléchargements (disposition « Extraire tout » de Windows) : retrouvé et vérifié; morceau tronqué : refusé
  (« base incomplète ou abîmée »). PowerShell analysé sans erreur par PowerShell 7 (accents lus, UTF-8 avec BOM).
- Non testé : exécution réelle sous Windows (WSL, winget, Docker Desktop) et sous macOS (Homebrew, Gatekeeper).

### 9 novembre 2026 — Installation en une commande, testée depuis les deux zips (phase 2)

- `scripts/install_shared_copy.sh`, livré comme `installer.sh` dans le zip 1 : vérifie les outils, recolle et
  vérifie la base, génère les mots de passe sans les afficher, lance Docker, restaure, contrôle `PRÊT`, crée le
  compte de lecture, installe DbHub, enregistre Claude Code ou Codex s'ils sont présents, crée
  `~/neolab-travail`. Relançable (étapes faites sautées), compatible bash 3.2 (macOS). `scripts/build_shared_copy.sh`
  fabrique les deux zips sous 400 Mo (limite d'envoi constatée : 659 Mo refusés, puis 402 Mo refusés).
- Test comme sur une machine neuve : installation existante arrêtée, volume de données supprimé, deux zips
  décompressés dans un dossier vide, `bash installer.sh fred_test` dans un environnement sans aucune variable
  de connexion : terminé en 3 min 35 s (`PRÊT`, `PASS`, Claude Code `✓ Connected`). Question posée ensuite à
  Claude Code depuis `~/neolab-travail` par ce serveur : 69 574 validés, première image am_leg3 le 2024-08-12
  à 15:36:06 UTC, vérifié en base. Second passage : 13 s, tout sauté sans erreur.
- Non testé : Windows (WSL) et macOS réels, Codex.

### 9 novembre 2026 — Batterie sur les données d'objet enrichies (phase 2)

- `tests/agent_battery/objects_cases.json` (9 cas) : jour/nuit (am_leg4 avec codes, am_leg3 sans aucun code),
  annotateurs (identifiants, sans nom), année de validation, score de prédiction, liens d'images, circularité
  copépodes / détritus, Feret en mm, forme absente pour LOKI. Premier passage : 9/9, valeurs exactes; les trois
  liens d'images rendus par l'agent s'ouvrent (HTTP 200, images EcoTaxa réelles).
- Relecture des réponses : trois imprécisions dues à la fiche `ecotaxa_objects`, qui ne décrivait pas les nouvelles
  colonnes (codes du soleil devinés, liens d'images supposés protégés, forme LOKI supposée absente à l'export).
  Fiche complétée (codes vérifiés, couverture partielle, identifiant sans nom, date de validation, score des seuls
  objets prédits, liens publics, LOKI sans mesures ZooProcess); trois cas rejoués : 3/3, explications justes.
- Contrôle de forme étendu à tous les fichiers de cas (identifiants uniques, question et attendu par tour).

### 8 novembre 2026 — Dernier enrichissement des objets EcoTaxa (phase 2)

- Champs EcoTaxa par objet vérifiés en direct (projet 149) puis chargés pour les 23 projets (15 050 002 objets,
  `populate_ecotaxa_objects.py`, environ 55 min) : heure (`obj.objtime`), position du soleil (`obj.sunpos`),
  annotateur (`classif_who`, identifiant seulement) et date de validation, score de prédiction, chemin de l'image
  (`img.file_name`, adresse `https://ecotaxa.obs-vlfr.fr/vault/<chemin>` reconstruite par la vue), et six mesures
  ZooProcess (périmètre, Feret, circularité, élongation, gris moyen, aire convexe; µm pour périmètre et Feret).
  Exposés dans `explore.ecotaxa_objects`, chacun documenté.
- Remplissage : heure 100 % sauf 801 (97 %) et 11469 (82 %); image 100 %; forme 100 % hors LOKI; annotateur et score
  selon le statut des objets; position du soleil calculée par EcoTaxa pour 3,8 M objets seulement (un espace
  sinon, ramené à NULL dans la vue). Codes vérifiés sur les données par élévation solaire : D jour (+20° en
  moyenne), N nuit (-21°), A aube (-7°, le matin), U crépuscule (-8°, le soir), ? indéterminé.
- Faux départ, corrigé : sans identifiants, EcoTaxa ne sert qu'une partie des objets de projets publics (315 :
  24 387 sur 65 828; 14622 : 188 384 sur 1 687 393) et refuse les 14 projets privés; ma commande avait aussi
  coupé l'export des identifiants (`set +a`). Le chargeur liste désormais les projets refusés ou lus en partie
  et sort en code 3; reprise remise à zéro pour les projets touchés, puis chargement complet : 0 refus, 0 partiel.
- Identifiants EcoTaxa repris de la capture d'écran de la session, gardés dans un fichier privé le temps du
  chargement, puis détruits.
- Base : 6,9 → 8,0 Go (table des objets 3,5 → 4,6 Go après VACUUM FULL); dump 657 Mo (309 avant), les mesures
  décimales se compressant mal. Zip `neolab_warehouse_20261108.zip` restauré avec son propre code : `PRÊT`.
  Tests : 163 verts.

### 7 novembre 2026 — Batterie de robustesse : droits restreints, pièges, CSV des figures (phase 2)

- `tests/agent_battery/robustness_cases.json` (8 cas) et option `"account"` de la batterie (droits d'un
  compte temporaire par cas, supprimé à la fin). Premier passage : 7/8.
  - Droits restreints (EcoTaxa + EcoPart, Baie de Baffin, 2024) : 3/3. am_leg3 annoncé partiel (1 871 550
    objets visibles sur 1 910 784, dit « accès partiel »), GreenEdge 2016 « hors de mon périmètre » et non
    vide, CTD « données masquées, pas absentes » (lu dans `catalogue.my_datasets`).
  - Pièges : fausse prémisse (« doublement de Calanus 2016–2024 » : aucun Calanus en 2016 dans la zone,
    prémisse rejetée), 3000 m (aucune mesure, maximum 2 130 m), projet 99999 (« n'existe pas »), 3/3.
  - Figure : CSV conforme aux 13 valeurs recalculées en base (49,4 ; 40,5 ; 52,8 … ind/m³), 1/1.
  - Migration jour/nuit : réponse correcte (« je ne peux pas conclure ») mais critère trop étroit ; élargi,
    vérifié sur la réponse et sur une réponse qui interprète (refusée).
- Défaut de données trouvé par l'agent : aucune heure en base (686 profils UVP, 6 138 samples et tous les
  objets EcoTaxa à 00:00) ; le chargeur ne demandait pas `obj.objtime` à EcoTaxa. Profils UVP : heure reprise
  des métadonnées EcoPart déjà chargées (« yyyy-mm-dd hh:mm », 686 profils, aucune contradiction, mêmes dates),
  lue en UTC, dans `populate_ecopart.py` (`ecopart_time`) et par une correction unique gardée ; 686/686 avec
  heure. EcoTaxa : `obj.objtime` demandé désormais (`object_datetime`, testé avec la fausse API) ; les objets
  déjà chargés gardent la date seule jusqu'au prochain chargement (identifiants EcoTaxa requis), documenté.
- Cas migration rejoué avec les heures : 1/1, jour/nuit par élévation solaire calculée depuis l'heure du
  profil, « les données ne montrent pas de migration verticale claire », sans interprétation.

### 7 novembre 2026 — Section « Raisonnement » et chiffres tirés des requêtes (phase 2)

- Règle dans `overview` et les instructions du serveur : toute réponse chiffrée ou illustrée commence par une
  courte section « Raisonnement » (question comprise, choix et raisons, lectures écartées); chaque chiffre vient
  d'une requête de la conversation, une valeur reprise d'une fiche est signalée et recalculée si possible
  (l'agent avait cité « environ 99 % de détritus » d'après la fiche au lieu de son propre calcul).
  Critère `raisonnement` ajouté aux cas `viz_vertical_profile_vague` et `amb_how_many_copepods`.
- Rejoué : 2/2. Profil vertical : deux panneaux (organismes en ind/m³, particules en objets/m³), projet,
  zone, méthode et lectures écartées (CTD, taxon) annoncés. Copépodes : 1 559 355 objets dont 561 457 validés
  (vérifié en base); doublons GreenEdge non retirés mais signalés (50 408 objets, 3 %).

### 7 novembre 2026 — Organismes ou particules : profil vertical d'une question vague (phase 2)

- Essai réel, « Trace le profil vertical du projet dans la Baie de Baffin. » : l'agent a choisi 10101 (dit) et
  tracé l'abondance de toutes les catégories en « ind/m³ ». En base, 99 % des objets validés de 10101 en Baie
  de Baffin sont non vivants (97 % de `detritus<not-living`); son pic de 19 121 « ind/m³ » à 675 m était de
  détritus (38 053 sur 38 388). Il a aussi écrit que les tranches sans objet validé manquaient : faux, les
  4 469 tranches y sont, zéros compris.
- `warehouse.ecotaxa_taxon.object_class`, colonne générée depuis la racine de la lignée : organism (Biota,
  307 catégories), not_living (détritus, artefacts, fèces : 16 catégories, 11,7 M objets), technical
  (badsegmentation, oversegmented, duplicate), temporary (t0xx). Exposée dans `ecotaxa_taxa` (avec
  `taxon_key` pour joindre `uvp_taxon_abundance`), `ecotaxa_sample_taxa` et `ecotaxa_objects`.
- Fiches : `uvp_taxon_abundance` (total d'organismes par `object_class = 'organism'`, sinon concentration de
  particules en objets/m³; zéros présents dans chaque tranche), `graphs`, `overview` (une demande sans
  grandeur se lit de plusieurs façons : dire la grandeur et le projet retenus, ou demander). Nouveau cas
  `viz_vertical_profile_vague` (la réponse du matin échoue au critère, une réponse correcte le passe).
- Rejoué avec un vrai agent : 1/1; abondance d'organismes seulement (39 à 63 ind/m³ en surface, recalculé en
  base à l'identique), détritus exclus et chiffrés, choix du projet et de la grandeur annoncés, alternative
  CTD proposée. Limite : son script recopie les valeurs du résultat SQL (l'agent n'a pas d'identifiants pour
  relancer la requête depuis Python), la requête exacte est dans le fichier de provenance.
- Tests : 160 unitaires et réels verts.

### 7 novembre 2026 — Explorer le schéma avant de générer le SQL (phase 2)

- Traces de 142 cas : 47 requêtes sur un nom inventé, toutes après lecture de `overview`; 21 étaient la
  première requête SQL de la conversation, 23 sans fiche de la vue ni liste de colonnes. Les fiches ne
  donnaient pas les colonnes : même un agent qui avait lu la fiche pouvait se tromper (8 cas).
- `catalogue.warehouse_context.column_list`, lue dans le schéma déployé à la publication : colonnes et types
  de chaque vue; dans `overview`, la carte de toutes les vues lisibles (`explore` d'abord, environ 10 000
  caractères). Règle dans `overview`, les instructions du serveur et l'outil DbHub : n'écrire du SQL qu'avec
  ces noms, jamais un nom deviné ni un sondage par essai-erreur.
- Mesure, sur les mêmes 14 cas (ecotaxa 10, ctd_visual 4) avant / après : noms inventés 8 → 0, requêtes SQL
  68 → 43, `search_objects` 11 → 0, tours (ecotaxa) 89 → 58; 14/14 réussis. Une erreur SQL restante : colonne
  ambiguë dans une jointure (faute de SQL, pas un nom deviné).

### 7 novembre 2026 — Taxons trouvables, lignée EcoTaxa, indices d'erreur MCP (phase 2)

- Point de départ, mesuré dans les traces de 103 cas de batterie (484 requêtes SQL) : 10 requêtes coupées à
  30 s, presque toutes des recherches de taxon par nom dans `ecotaxa_objects` (`ILIKE '%oith%'` sur 10101 :
  31,8 s sous RLS); 34 requêtes sur un nom de colonne deviné; aucune lignée taxonomique en base, donc
  « les copépodes » énumérés de mémoire.
- `warehouse.ecotaxa_taxon` : taxonomie EcoTaxa des 340 catégories (lignée, type P/M, rang, AphiaID),
  lue sur `/taxon_set/query` (public), `scripts/populate_ecotaxa_taxonomy.py`, appelé en fin de chargement des
  objets. `warehouse.ecotaxa_sample_taxon` : 39 493 lignes (sample × catégorie × statut), recalculées pour
  les samples dont les totaux diffèrent de leurs compteurs (1,4 s pour tout), RLS du sample.
- Vues `explore.ecotaxa_sample_taxa` et `explore.ecotaxa_taxa`; `taxon_lineage`/`taxon_type` dans
  `ecotaxa_objects`, `sampled_at` dans `ecotaxa_samples`. Recherche d'un taxon : 31,8 s → 20 ms (compte de
  lecture). Constat : 721 copépodes validés de am_leg3 sont rangés sous « with visible lipid sac »
  (`side<`, `top-bottom<`), sans « copep » dans le nom; la réponse du 6 novembre (747) les manquait, la lignée
  donne 1 468 organismes entiers (1 485 avec morts, fragments, œufs, antennes). Le type M ne veut pas dire
  fragment : les stades et vues sont M (consigne corrigée avant publication).
- Relais `warehouse_connect.py run` : champ `hint` ajouté aux erreurs SQL (délai, nom inconnu, droit),
  vérifié à travers DbHub réel. Fiches `overview`, instructions serveur et guide SQL : chercher un taxon dans
  `ecotaxa_sample_taxa`, un groupe par la lignée, dire quelles catégories non entières sont gardées.
- Défauts trouvés en chemin : (1) le déploiement affichait `PRÊT` alors que la publication des fiches avait
  échoué; le contrôle exige maintenant une fiche par vue `explore`. (2) Trois profils UVP GreenEdge 2016 vers
  70° N avaient une zone vide marquée `assigned` (leurs samples disent Baie de Baffin dans 149, Détroit de
  Davis dans 20890), d'où 245 profils par `uvp_samples` et 243 par `zone_membership`; `populate_ecopart.py`
  calcule la zone d'un bloc (`profile_zone`, AMBIGUOUS si les samples se contredisent), correction unique
  gardée dans la migration; le cas carte accepte les deux comptes, documentés.
- Tests : unitaires et réels verts (157 + RLS des nouvelles vues : compte restreint 8 objets sur 16).
  Batteries : ecotaxa 10/10; ctd_visual 9/10 puis 10/10 (carte : 245 contre 243, cause ci-dessus); mixed
  13/13 avec deux nouveaux cas (copépodes par la lignée, Oithonidae dans 801 et 802 seulement).
  Traces après correction (39 cas, 168 requêtes) : 0 délai dépassé (10 avant); erreurs de nom inchangées en
  proportion (13, surtout `title` pour `ecotaxa_project_title` et une table `explore.zones` inexistante),
  mais 13 sur 13 corrigées à la requête suivante grâce à l'indice.

### 6 novembre 2026 — Zip de partage v6 rejoué; comptes de test supprimés (phase 2)

- `neolab_warehouse_20261106.zip` (311 Mo) : dump du 6 novembre (309 Mo, zstd), code du dépôt (339 fichiers,
  sans `data/` ni secret), LISEZMOI aux nouveaux noms. Rejoué avec le code du paquet : empreinte `OK`,
  restauration 2 min 53, `deploy --check` → `PRÊT`; compte personnel, `install-dbhub`, `check` → `PASS`,
  `workspace`, puis une question Claude Code par MCP dans le dossier de travail (« Combien de copépodes
  validés dans am_leg3 ? ») : 747, choix de définition annoncés, valeurs vérifiées en base.
- Défaut trouvé : la batterie fermait ses comptes temporaires (`offboard`) sans les supprimer; 15 rôles
  `battery_*` restaient dans le serveur (sans connexion ni droit, absents du dump). Nouveau
  `warehouse_user.py remove <nom> --yes` (rôle et historique de droits, refusé sans `--yes` et pour le
  propriétaire), utilisé par la batterie; test réel ajouté au parcours de compte; les 15 rôles supprimés.

### 6 novembre 2026 — Batterie élargie (ambiguïtés, taxons, variables, conversations) et dossier de travail NeoLab (phase 2)

- `mixed_cases.json` : 3 questions ambiguës, 3 mélanges de taxons et de stades (Oithona absent de 10101,
  Metridia longa réparti en stades et vues dans LOKI 2015), 2 croisements CTD × UVP (aucun lien direct, chemin
  par les samples EcoTaxa), 3 conversations en plusieurs tours (`"turns"`, session reprise avec --resume).
  `agent_battery.py` : conversations, cas « non exécuté » quand la limite d'usage de l'agent est atteinte
  (une batterie de la nuit a buté sur « You've hit your 5-hour limit » : 8 cas faussement en échec).
- Constat mesuré : sur une question très courte, dans un dossier vide, l'agent ne fait pas le lien avec le
  warehouse et répond de mémoire ou cherche la météo sur le web (4 sur 4), même avec les instructions MCP
  envoyées par le serveur à la connexion (ajoutées au relais `warehouse_connect.py run`, utiles mais
  insuffisantes). Nouveau `warehouse_connect.py workspace <dossier>` : CLAUDE.md, AGENTS.md, GEMINI.md,
  .github/copilot-instructions.md (aucun secret); dans ce dossier l'agent interroge la base 4 sur 4. Ajouté au
  LISEZMOI de partage (partie 5) et au guide de connexion; option `--workspace` de la batterie.
- Résultats : ecotaxa 10/10, ctd_visual 10/10 (dossier vide, avec instructions serveur); mixed 11/11 en
  dossier de travail (122 tours, 62 requêtes, ≈ 3,18 $).
- Corrections de faits trouvées par les agents puis vérifiées : 149 contient les 199 samples de 20880 + 20890
  plus 5 samples propres (et non « 149 = 20880 + 20890 »); 13224 est un extrait de 10 000 objets des mêmes
  204 samples que 149 (même sample et même profondeur pour 2 000 objets vérifiés); Oithonidae existe dans les
  Zooscan 801/802 (seul 10101 en est dépourvu). Documentation et références de tests corrigées.

### 6 novembre 2026 — Tests agent CTD et graphiques; sigma-t et pression documentés (phase 2)

- Nouvelle batterie `ctd_visual_cases.json` (6 questions CTD, 4 graphiques/cartes). Premier passage 7/10, avec
  des causes réelles : (1) l'agent interrogé sur « la densité à 500 m » n'a pas consulté la base et a répondu
  de mémoire (climatologie) — la notation exige désormais au moins une requête SQL, la consigne générale et la
  description DbHub disent ce que contient la base et interdisent de répondre de mémoire; (2) le signe moins
  « − » n'était pas lu par la notation; (3) une carte peut valablement montrer 196 profils localisés ou 243
  avec ceux positionnés par leur sample : `expect_sql` accepte des alternatives, l'explication est exigée.
  Les dossiers de travail des agents passent hors du dépôt (`~/neolab_agent_battery`) : un agent avec outils
  de fichiers lisait le dépôt. Passage final 10/10 (176 tours, 61 requêtes, ≈ 2,89 $); figures relues :
  carte, diagramme T-S (conversion TEOS-10 indiquée), barres validés/tous objets, profil vertical (échelles
  différentes entre panneaux, à améliorer).
- Données CTD : `SIGT` était décrit « densité » alors que c'est le sigma-t (densité moins 1000; valeurs 16–28);
  renommé dans le chargeur et en base. `depth_m` CTD est la pression en dbar prise pour des mètres (≈ 1 % à
  2000 m) : documenté. `qc` toujours NULL : documenté comme « aucun contrôle qualité fourni ».
- Autres agents (Codex, Gemini, OpenCode) : installation refusée par les permissions de la session (code
  téléchargé), et aucune clé API OpenAI/Google disponible; non testés.

### 4 novembre 2026 — Batterie de tests agent rejouable et zip v5 (phase 2)

- `scripts/agent_battery.py` + `tests/agent_battery/ecotaxa_cases.json` : 10 questions de chercheur à pièges,
  réponses de référence recalculées en base à chaque lancement, compte temporaire en lecture seule supprimé à la
  fin, environnement de l'agent sans mot de passe, notation automatique (nombres attendus, motifs obligatoires,
  valeurs interdites comme la somme des doublons GreenEdge) et rapport `report.md`/`report.json`. Notation
  validée sur les 10 réponses notées à la main (concordance 10/10) et par 9 tests unitaires sur des erreurs
  plausibles (valeur manquante, doublons additionnés, taille dans la mauvaise unité, abondance sur prédictions).
  Guide : `docs/WAREHOUSE_AGENT_TESTS.md`.
- Zip v5 (dump avec tailles UVP6 corrigées, code, LISEZMOI débutant) : parcours de partage rejoué sur machine
  vidée (`PRÊT`, `PASS`, Connected), puis batterie lancée depuis l'installation du zip : 10/10, 1 min 37,
  114 tours, 47 requêtes SQL, environ 1,63 $ estimés. Le test a révélé que `.gitignore` excluait tous les
  `*.json`, donc le fichier des cas : exception ajoutée. Zips v2 à v4 supprimés (tailles UVP6 fausses).

### 4 novembre 2026 — Batterie de 10 tests agent EcoTaxa et correction des tailles UVP6 (phase 2)

- En préparant les réponses de référence : les tailles UVP6 étaient 1 000 fois trop grandes (copépode moyen à
  2,26 m). EcoTaxa donne la taille du pixel en mm pour UVP5/Zooscan (0,085–0,174) mais en µm pour UVP6 (73);
  le chargeur lisait tout en mm. Corrigé dans le chargeur (valeur source et unité retenue conservées) et en base
  (400 acquisitions UVP6 converties, 704 UVP5 inchangées); copépodes validés 10101 : grand axe moyen 2,23 mm.
  Les résultats antérieurs utilisant des tailles UVP6 (dont la comparaison FILET/UVP par taille du 30 octobre)
  sont à refaire; le zip v4 contient encore les tailles fausses.
- 10 questions de chercheur à Claude Code via DbHub (dossiers vides, compte lecture seule, aucun mot de passe
  dans l'environnement), réponses de référence calculées à part : 10/10 chiffres exacts (LOKI 2015 187 567
  validés sur 1 687 393; 12063 688 643 jamais classés; 5 taxons validés am_leg4; 480 samples en Baie de Baffin;
  aucun Calanus validé dans am_leg3, l'agent refuse de calculer sur des prédictions sans le dire; grand axe des
  copépodes 10101, ESD absent en UVP6 signalé; GreenEdge 2016 sans addition des doublons; 0 % de tailles LOKI;
  am_leg5 73 profils du 4 au 28 octobre 2024; Zooscan 100 % validé). Une imprécision : les 13 565 objets
  douteux de 14622 décrits comme « ni validés ni prédits » au lieu de « douteux ». 103 tours, 45 requêtes SQL,
  environ 1,37 $ estimés au total.

### 4 novembre 2026 — LISEZMOI de partage pour débutant (phase 2)

- `docs/WAREHOUSE_PARTAGE_LISEZMOI.md` (copié comme LISEZMOI du zip v4) : installation de zéro sur Windows
  (WSL Ubuntu + Docker Desktop), macOS (Homebrew + Docker Desktop) et Linux (Ubuntu 22.04/24.04), vérification
  des versions, choix de l'assistant (Claude Code, Codex, GitHub Copilot dans VS Code) avec le compte requis,
  Python en environnement virtuel (le `pip install` système est refusé sur Ubuntu 24.04 et Homebrew), branchement
  MCP pour chacun, relance quotidienne, dépannage par symptôme.
- Vérifié : commandes Linux (Python, venv, client PostgreSQL 16 via PGDG, Node.js 22 via NodeSource) dans des
  conteneurs Ubuntu 22.04 et 24.04 neufs; parcours complet du zip v4 rejoué sur machine vidée (venv, `PRÊT`,
  `PASS`, Claude Code Connected, réponse exacte en 26 s); `config codex` et `config vscode` produisent des
  configurations pointant vers le Python du venv.
- Non vérifié ici : Windows et macOS réels, l'installateur de Codex (exécution de script distant refusée par
  les permissions de la session), Copilot dans VS Code; l'accès réseau des builds Docker a demandé la même
  adaptation d'environnement que le 4 novembre (image de base avec le certificat du proxy).

### 4 novembre 2026 — Deux schémas de lecture et test de partage du zip (phase 2)

- Organisation : `explore` ne contient plus que les 27 vues de données; les 10 vues de service (droits
  `my_access`/`my_datasets`, `dataset_catalog`, `dataset_versions`, `fair_readiness`, `fair_column_coverage`,
  `warehouse_dictionary`, `warehouse_context`, `warehouse_release`, `access_audit`) passent dans un schéma
  `catalogue` (`warehouse_catalogue_schema_migration.sql`, appliquée en premier; les vues existantes sont
  déplacées avec leurs droits et dépendances). Droits, propriété, déclencheur d'adoption, audit d'accès,
  DbHub (`search_path = explore,catalogue`), `warehouse_connect check`, déploiement, docs et tests mis à jour;
  le dictionnaire couvre les deux schémas (`schema_name`). Base réelle redéployée : `PRÊT`, audit vide;
  135 tests réussis sur base réelle.
- Consignes agents : partir de `explore.ecotaxa_projects` pour toute question sur les projets ou objets en
  général et dire le périmètre; ne pas affirmer qu'un projet est la copie d'un autre sans comparer les comptes
  par profil ou sample (cause de l'erreur 13224 du 3 novembre).
- Test de partage, en suivant seulement le `LISEZMOI` du zip v3 (dump zstd 311 Mo + code + notice), sur une
  machine vidée (conteneur et volume supprimés, aucun compte, aucune configuration MCP, aucun mot de passe
  dans l'environnement), dans un dossier ordinaire : vérification SHA-256, base Docker `healthy`, restauration
  3 min 52, `--check` = `PRÊT`, compte personnel, DbHub installé, `check` = `PASS`, `claude mcp list` =
  Connected, puis question du LISEZMOI à Claude Code dans un dossier vide : réponse exacte (23 projets,
  15 050 002 objets, 44,2 % validés; 37,9 % sans le doublon 149), 8 tours, 50 s.
- Limites de l'environnement de test, pas du produit : Docker Hub a répondu « 429 Too Many Requests » et le
  proxy TLS du conteneur cloud empêchait `pip` dans le build; l'image de base a été prise sur `mirror.gcr.io`
  et complétée du certificat du proxy, sans modifier le Dockerfile ni le compose du zip.

### 3 novembre 2026 — Vues exhaustives et base lisible par un humain (phase 2)

- Trou trouvé par un test agent (stats d'annotation EcoTaxa) : seuls les 13 projets liés à un profil UVP étaient
  visibles dans `explore` (10 projets et 4,4 M objets absents, dont les 689 201 jamais classés); les profils CTD
  et leurs variables n'étaient visibles qu'à travers un lien EcoTaxa. Revue de couverture table par table, puis
  5 vues : `ecotaxa_projects`, `ecotaxa_samples`, `ecotaxa_objects`, `ctd_profiles`, `ctd_measurements`, sous la
  même sécurité par ligne (testé : compte restreint limité à ses 2 samples, 0 CTD hors source accordée).
- `object_count` était vide pour les 6 138 samples : rempli depuis les objets (chargeur + base réelle), cohérent
  avec les compteurs par statut sur tous les samples.
- Lisibilité humaine : titres du catalogue nommés d'après la source (« EcoTaxa 42 — UVP5 GREEN EDGE Ice Camp
  2015 » au lieu de « ecotaxa dataset 42 (current) »), colonnes décrites pour les vues de service (563/563
  colonnes des 37 vues décrites, test ajouté), clés `uvp_profile_id`/`uvp_bin_id` ajoutées à `ecopart_bins` et
  `uvp_taxon_abundance` (anciens noms conservés), guide `WAREHOUSE_SQL_GUIDE.md` (connexion DBeaver/psql, vue
  par question, clés, pièges, 7 requêtes testées avec le compte lecteur en 0,1 à 6,6 s).
- Test agent relancé (même question, environnement sans aucun mot de passe de la base, vérifié) : 23 projets
  couverts, totaux exacts (15 050 002 objets), doublons 149/20880/20890 repérés, 14669/2331 signalé non vérifié.
  Écart relevé : l'agent affirme que 13224 est un extrait de 149, non établi (aucun objet commun). Le chemin du
  dossier de test provoque encore une copie des fichiers dans un dossier mal nommé (artefact du montage).

### 3 novembre 2026 — Tableau de bord annotation et carte interactive (phase 2)

- Tableau de bord privé (type Dashboard) : chiffres clés d'annotation (15 050 002 objets, 44,2 % validés,
  51,2 % prédits), statuts par projet EcoTaxa, 25 catégories les plus fréquentes avec part validée, carte d3
  zoomable des 488 points de profils UVP localisés (couleur = part validée, infobulle avec copépodes 0–200 m tous
  objets / validés), 456 profils CTD, contours des zones NeoLab et MEOW, filtre par projet.
- Données : instantané du warehouse (fichiers JSON joints, non live : la base est locale), trait de côte
  Natural Earth 50m. Totaux des fichiers recoupés avec la base.

### 3 novembre 2026 — Tests visuels des agents sur la base réelle (phase 2)

- Quatre questions de chercheur à Claude Code (MCP, lecture seule, dossiers vides, lancées en parallèle) :
  carte des profils UVP en Baie de Baffin avec contours de zones (37 tours, 3 min 42, 0,67 $), abondance des
  copépodes tous objets vs validés (21 tours, 1 min 48, 0,36 $), profil vertical am_leg4 (21 tours, 1 min 52,
  0,46 $), profils moyens T/S des CTD par année (32 tours, 3 min 55, 0,55 $). 4/4 figures livrées avec CSV,
  script et provenance; 39 requêtes SQL.
- Recoupements indépendants : 802,6 ind/m³ (am_leg3, taxons copépodes de l'agent) et 49/13/31/94 profils CTD
  par année, identiques.
- Défauts observés : un agent a écrit sa figure dans un chemin mal recopié (tiret au lieu d'une barre oblique);
  l'agent carte n'a pas relu son dernier rendu; le profil vertical utilise tous les objets (prédits compris),
  ce qu'il indique sur la figure. Page de démonstration publiée (artifact privé).
- Correction : consigne `graphs` du contexte (fichiers en chemins relatifs vérifiés, relecture de l'image après
  la dernière modification, `validated_only` tracé à côté de `all_loaded_objects`), test de contexte ajouté.
  Trois tests relancés avec les mêmes questions : fichiers au bon endroit et chemins exacts, image finale relue
  après la dernière retouche (3/3), profil vertical tracé en deux politiques sans le demander (19 982 objets /
  64 profils contre 1 105 validés / 58 profils, recalculé). Cause du chemin fautif : le chemin inhabituel du
  dossier de test, que l'agent confond avec le nommage interne de Claude Code. Coûts de la page présentés
  comme estimation au tarif API (aucune clé API utilisée, modèle Claude Sonnet 5.5).

### 3 novembre 2026 — Statut d'annotation EcoTaxa et filtre de zone complet (phase 2)

- Trou trouvé par un test agent réel (question Baie de Baffin) : `annotation_status` et `category_id` vides sur
  les 15 M objets (jamais demandés à l'API). Le chargeur lit désormais `obj.classif_qual` (V/P/D) et
  `obj.classif_id`; `--refresh` a relu les 15 050 002 objets en place (≈ 1 h, aucun doublon) : 6 645 676
  validés, 7 700 806 prédits, 14 319 douteux, 689 201 jamais classés. Compteurs par sample recalculés.
- Abondances UVP sous deux politiques (`all_loaded_objects`, `validated_only`), recalculables sans EcoPart
  (`populate_ecopart.py --recompute-abundance`); `taxon_name` ajouté à la vue (les clés sont maintenant des
  identifiants EcoTaxa). Cas am_leg3 (14859), Baie de Baffin, Copepoda 0–200 m : 750,9 ind/m³ tous objets,
  135 objets validés seulement (moins de 1 %) — la valeur haute vient d'objets prédits.
- Zones : contours pleine résolution en base et `explore.zone_membership` (PostGIS `ST_Covers`, toutes les
  zones couvrant un point, MEOW et chevauchements compris; lignes sans coordonnées gardent leur zone amont,
  signalées). `uvp_projects.marine_zone_keys` liste toutes les zones d'un projet (18084 retrouvé en Baie de
  Baffin). Règle de chargement documentée : zone NeoLab/IHO prioritaire sur MEOW, AMBIGUOUS si plusieurs zones
  NeoLab. Chargement des contours ajouté à `load_warehouse.py`.
- Test agent réel (Claude Code, MCP, dossier vide) : chiffres exacts recalculés, filtre par `zone_membership`,
  comparaison des politiques avec nombre de profils, cause d'am_leg3 identifiée. Il a révélé l'absence de nom
  de taxon (requêtes de recherche au-delà de 30 s), corrigée ensuite.
- Sauvegarde v2 (`backup_warehouse.py --compress zstd:12`, nouvelle option) : 326 Mo au lieu de 402 Mo, sous la
  limite d'envoi; restauration testée sur base neuve (0 erreur, `PRÊT`, comptes identiques, `pg_restore` local et
  du conteneur PostGIS). Un premier essai a échoué faute d'espace disque dans l'environnement de test, pas à cause
  du fichier.
- Problèmes de données relevés : 197 profils GreenEdge 2016 sans coordonnées propres (samples EcoTaxa 149 et
  20890 en désaccord, ex. longitude +58,5 / −58,5 pour ge_2016_001); 3 profils `assigned` sans zone.

### 3 novembre 2026 — Chargement complet réel et sauvegarde partageable (phase 2)

- Chargement réel de tous les projets accessibles (`load_warehouse.py --all-projects`) : 23 projets EcoTaxa,
  6 138 samples, 15 050 002 objets (taille Zooprocess en pixels), 82 757 acquisitions dont 1 104 calibrées;
  12 projets EcoPart, 686 profils, 71 520 bins, 12 151 035 objets rattachés; 456 profils CTD Amundsen
  (5 130 421 mesures), tous en zone `assigned`; 65 zones, 18 stades de copépodes. Rejeu final : `PRÊT`.
- Échecs observés et corrigés : (1) rejeu de la migration EcoPart en cours de chargement refusé (« cannot drop
  columns from view ») — régression de mes migrations récentes qui avaient redéfini `uvp_taxon_abundance` (zéros
  densifiés perdus) et `uvp_projects` depuis d'anciennes définitions; définitions rendues identiques et testées
  (identité entre fichiers, rejeu dans la chaîne de chargement, zéros présents : 2 550 577 lignes à zéro sur
  3 042 992 en réel). `uvp_object_sizes` rattache le bin au profil de la ligne (0 doublon vérifié). (2) Projet
  EcoPart 61 : tâche d'export non identifiée (page de confirmation sans lien); le numéro de tâche est lu dans la
  confirmation, puis vérifié comme avant; repris et chargé. (3) Calibration pixel : 53 142 acquisitions LOKI,
  lot unique non reprenable; traitement par lots de 1 000 reprenable.
- Sauvegarde `pg_dump` 392 Mo (7,2 Go restaurée), restauration testée sur une base neuve (déploiement →
  `backup_warehouse.py --restore` → `--check` = `PRÊT`, comptes identiques, lecteur opérationnel). Zip remis :
  sauvegarde + SHA-256 + code au commit + `LISEZMOI` de restauration; aucun mot de passe; identifiants EcoTaxa
  supprimés de l'environnement de chargement.
- `LISEZMOI` du zip complété par le branchement d'un agent (compte lecture seule, `init`, `install-dbhub`,
  `check`, `config <agent>`); étapes 1 à 3 rejouées sur la base réelle : `check` = `PASS` (3 outils MCP, lecture
  seule, 36 jeux lisibles), compte de test révoqué ensuite.
- Limites : FILET non chargé (prévu le 4 novembre); tailles LOKI sans calibration (restent en pixels); EcoTaxa 17808 sans EcoPart lié;
  aucun contrat d'accès posé; le zip complet contourne le contrôle d'accès par personne (choix assumé de
  l'utilisateur) et contient les métadonnées sources dont les contacts `DataOwner`.

### 1ᵉʳ novembre 2026 — Les agents montrent les requêtes derrière leurs chiffres

- Consigne générale (`warehouse_context` overview) : toute réponse chiffrée se termine par « Requêtes exécutées »
  — texte exact de chaque requête SQL ayant produit les chiffres, nombre de lignes, valeurs utilisées; seulement
  des requêtes réellement exécutées; découverte résumée en une ligne.
- Tests réalistes (dossier vide, question formulée comme un chercheur, sans indication) : carte des paires
  UVP–filet à moins de 10 h et même station (bonnes paires, exclusions justes, recalcul indépendant des paires
  stockées), puis dans la même conversation, comptage des samples et comparaison des abondances (valeurs exactes,
  pas de double compte des stades). Puis la comparaison avec la nouvelle consigne : les 4 requêtes affichées
  figuraient toutes dans l'audit du serveur.
- Erreur de méthode corrigée : un premier essai lancé dans le dossier des données de test a laissé l'agent lire
  les réponses; les tests se font désormais dans un dossier vide.

### 31 octobre 2026 — Connaissance des stades de copépodes (FILET et UVP) pour les agents

- Nouvelle référence `warehouse.copepod_stage` / `explore.copepod_stages` (migration
  `sql/warehouse_copepod_stage_migration.sql`) : les 18 codes de stade FILET avec libellé, phase (nauplius,
  copépodite, adulte, agrégat), rang de développement, sexe, statut d'agrégat, présence d'une biomasse dans
  l'export, et ce que l'UVP permet (aucun champ de stade; seulement via les catégories EcoTaxa et
  `taxon_mapping`).
- Établi dans le dépôt et verrouillé par test (codes = contrainte du schéma = chargeur FILET; agrégats et biomasse
  identiques) : codes, `is_aggregate`, `filet_has_biomass`, règle de ne jamais additionner un agrégat à ses
  composants. **Non établi, marqué « à confirmer »** : libellés, sens de `COP_NS`/`NAUP_NS`, composition des
  agrégats (adultes dans COPEPODID ?). La référence est le dictionnaire FILET du labo
  (`copepod abund&biomass-metadata.csv`), absent du warehouse : à charger ou à faire relire par un biologiste.
- Vérifié avec Docker et un vrai Claude Code : l'agent a utilisé la référence de lui-même, donné les abondances par
  stade dans l'ordre du développement, 38 ind/m³ au total sans double compte de `ALL_STAGES`, signalé les
  libellés « à confirmer » et l'absence de stade côté UVP. 109 tests verts en direct.
- La base de connaissances copépodes de l'ancien projet (« ChromaDB copépodes », `ARCHITECTURE.md` §9) est dans
  l'archive `../IDEA-archive-20260911`, absente de cet environnement : non consultée.

### 31 octobre 2026 — OpenCode branché au warehouse

- `warehouse_connect.py config opencode` génère le bloc `mcp` d'`opencode.json` (`"type": "local"`, commande en
  liste), d'après la documentation d'OpenCode (opencode.ai/docs/mcp-servers).
- Vérifié avec OpenCode 1.19.5 : le bloc généré, collé tel quel, donne `✓ neolab-warehouse connected`; l'agent
  est identifié (`opencode`) dans la trace et donc dans l'audit. Pas de conversation complète : quota des modèles
  gratuits d'OpenCode épuisé depuis l'environnement de test (les identifiants Amazon Bedrock présents dans
  l'environnement n'ont volontairement pas été utilisés).
- Précisé dans `docs/WAREHOUSE_AUDIT.md` pour qui l'audit fonctionne : tous les comptes personnels, quel que soit
  l'agent ou le poste; l'étiquette d'agent et la trace demandent la version à jour du dépôt sur le poste.

### 31 octobre 2026 — Audit des requêtes des agents et trace de débogage

- **Audit (serveur)** : chaque requête des comptes personnels et de `warehouse_reader` est écrite dans le journal
  CSV de PostgreSQL (`log_statement` par compte, `logging_collector` + `csvlog` dans le compose), avec le compte,
  l'heure et l'agent (`neolab-mcp:<agent>`). Le compte ne peut pas le couper (`SET`/`ALTER ROLE` refusés).
  Relecture : `scripts/warehouse_audit.py` (`--summary`, `--user`, `--since`, `--errors`, `--csv`, `--file`).
  Activé au déploiement pour les comptes existants et par `warehouse_user.py create` pour les nouveaux; sans
  superuser, signalé non actif sans échec. [Guide](docs/WAREHOUSE_AUDIT.md).
- **Trace (poste)** : `warehouse_connect.py trace on|off|show|clear` journalise localement chaque appel d'outil
  de l'agent (SQL, durée, lignes, troncature, erreur, extrait). `run` relaie désormais les messages MCP pour
  l'écrire et pour nommer l'agent auprès du serveur.
- Vérifié avec Docker et un vrai Claude Code (19 requêtes et un refus d'accès retrouvés dans l'audit, trace
  correspondante), Codex 0.166 et Gemini CLI 0.66 à travers le même lanceur; 105 tests verts en direct.
- Trouvé en route : MCP 2026-07-28 (Claude Code 2.1) n'ouvre plus par `initialize` (nom de l'agent dans
  `params._meta`); DbHub ignore `application_name` du DSN (passage par `PGAPPNAME`); `config json > mcp.json`
  produisait un JSON invalide (message final désormais sur stderr).
- À décider par le labo : durée de conservation du journal et qui peut le lire. Non testé : hébergement géré,
  Windows.

### 31 octobre 2026 — Branchement MCP pour Codex, Gemini CLI, Cursor et VS Code

- `warehouse_connect.py config` génère désormais aussi les configurations Gemini CLI, Cursor et VS Code
  (Copilot), en plus de Codex, Claude Code, Claude Desktop et du format générique.
- Vérifié avec les vrais clients (base Docker, compte restreint, parcours `init` → `check` → enregistrement) :
  Codex 0.166 lance le serveur et termine la poignée de main MCP; Gemini CLI 0.66 l'affiche `Connected`. Les
  configurations écrites par `codex mcp add` et `gemini mcp add` sont identiques à celles générées.
- Trouvé en route : Gemini désactive tout serveur MCP lancé depuis un dossier non approuvé (documenté); Codex
  abandonne un serveur muet après 10 s par défaut, ce que peut dépasser le premier téléchargement de DbHub par
  `npx` : la configuration Codex générée porte `startup_timeout_sec = 30` (vérifié lu par Codex). Démarrage
  mesuré : 0,9 s avec DbHub installé localement.
- Limites : pas de conversation complète avec Codex ni Gemini (aucun compte OpenAI/Google dans
  l'environnement de test); Cursor, VS Code et Claude Desktop non testés (formats selon leur documentation).

### 31 octobre 2026 — Vrais contours de zone pour les agents, et la zone enfin directe sur l'abondance UVP

- Fermé deux écarts trouvés en testant abondance multi-taxon/multi-zone avec un agent réel la veille.
- **Zone manquante sur `explore.uvp_taxon_abundance`** : la vue joint déjà `uvp_profile` (qui porte
  `marine_zone_key`) mais ne le sélectionnait pas — un agent sans `explore.uvp_samples` peuplé (profil sans
  sample EcoTaxa lié) devait deviner la zone autrement. Corrigé (`sql/warehouse_uvp_abundance_zone_migration.sql`) :
  `marine_zone_key/name/assignment_status` et `ecotaxa_project_id` ajoutés en fin de colonnes.
- **Contours de zone absents du SQL** : `marine_zone_key` n'était qu'une étiquette texte partout dans le
  warehouse; la géométrie réelle (`shared_data/geo/zones_registry.geojson`, 65 zones, IHO Marine Regions)
  n'existait que comme fichier local lu par le navigateur et les scripts Python — injoignable depuis DbHub/MCP.
  Ajouts : table PostGIS `warehouse.marine_zone`, vue `explore.marine_zone_boundaries` (GeoJSON), chargeur
  `scripts/load_marine_zones.py` (idempotent, 65 zones). Simplification nécessaire : certaines zones (archipel
  arctique, ex. « Nunavik ») encodent des milliers de petites îles en trous internes — simplifier la ligne
  (Douglas-Peucker) seule ne réduisait presque rien (1,2 Mo même à tolérance 0,5°); retirer d'abord les îles
  sous un seuil de surface a ramené le total des 65 zones de 4,65 Mo à 464 Ko (max 96 Ko/zone, contre 1,2 Mo
  avant).
- PostGIS n'était activé qu'en fin de déploiement, après les migrations (`ensure_postgis`, pour le filtre
  spatial du navigateur, jamais requis par le schéma jusqu'ici) : la nouvelle table en a besoin plus tôt,
  déplacé avant les migrations. Sur un propriétaire non-superuser sans droit préalable sur l'extension
  (hébergement géré, cas déjà testé), la migration se dégrade proprement (vue non créée, reste du déploiement
  intact) — corrigé `publish_warehouse_context.py` pour accepter cette vue comme optionnelle plutôt que
  d'échouer tout le contexte MCP si elle manque.
- Vérifié en direct (Docker, jeu de test, compte scopé C1) avec un agent réel : il a trouvé la zone directement
  sur `explore.uvp_taxon_abundance` (sans deviner, cette fois), calculé l'abondance de Calanus par zone (450 /
  200 / 90 ind/m³, exact), puis tracé une carte avec les **vrais contours polygonaux** des 3 zones concernées
  (pas des points) via `explore.marine_zone_boundaries`, colorée par abondance.
- 101 tests verts en direct (20 vues, 366 colonnes documentées), y compris le cas hébergement géré non-superuser
  sans PostGIS préalable.

### 31 octobre 2026 — Filtre par zone, carte avec taille/couleur de projet : vérifiés, un trou fermé

- Vérifié avec un agent réel (Docker, 3 zones maritimes réelles, 3 projets EcoTaxa de test, compte scopé C1) :
  le filtrage par zone maritime (`marine_zone_key`) fonctionne correctement — l'agent a vérifié les zones
  disponibles, exclu la bonne, et signalé que `marine_zone_name` était vide plutôt que de l'utiliser à tort.
- Demande d'une carte (taille du point = taille réelle moyenne des objets en µm, couleur = nom du projet
  EcoTaxa) : l'agent a produit une page HTML autonome avec SVG, légende accessible et infobulles, chiffres
  exacts (3168/1584/836 µm). Mais il a trouvé un vrai trou : `warehouse.ecotaxa_project.title` (le nom du
  projet, ex. « Campagne Amundsen 2023 ») n'était exposé par aucune vue `explore.*` — seul l'identifiant
  numérique l'était. L'agent l'a signalé plutôt que d'inventer un nom.
- Corrigé (migration `sql/warehouse_ecotaxa_project_title_migration.sql`) : `ecotaxa_project_title` ajouté en
  fin de colonnes de `explore.uvp_samples` et `explore.uvp_projects` (`CREATE OR REPLACE VIEW` refuse de
  renommer une colonne existante en insérant au milieu — corrigé après un premier essai en échec à
  l'initialisation Docker). Référence seule (NULL si le projet n'a pas été chargé), ne remplace pas
  `ecotaxa_project_id` comme clé.
- Rejoué avec succès : la même carte montre maintenant les vrais noms de projet dans la légende, vérifié
  directement dans le HTML produit. 101 tests verts en direct (19 vues, 357 colonnes documentées).

### 30 octobre 2026 — Comparaison FILET/UVP filtrée par taille, taxonomie incluse

- Fermé l'écart trouvé plus tôt dans la journée : `warehouse.taxon_mapping` (correspondance FILET↔UVP retenue)
  n'était accessible à aucun compte scopé (ceux-ci n'ont `USAGE` que sur le schéma `explore`, jamais sur
  `warehouse` directement), donc un agent ne pouvait pas relier un taxon FILET à `explore.uvp_object_sizes`
  sans deviner par nom de taxon en texte libre.
- Ajouts (migration `sql/warehouse_taxon_mapping_view.sql`) : vue `explore.taxon_mapping` (statut `accepted`
  uniquement — `ambiguous`/`rejected` restent cachés, documenté comme tel, pas confondus avec une absence de
  correspondance), et colonne `taxon_key` sur `explore.uvp_object_sizes` (même formule que
  `uvp_taxon_abundance.taxon_key`), permettant la jointure `uvp_object_sizes.taxon_key = taxon_mapping.uvp_taxon_id`.
  Table de référence non datée/zonée, exemptée de sécurité par ligne comme les autres catalogues
  (`dataset_version`, `dataset_metadata`, etc.).
- Vérifié en direct (Docker, jeu de test, compte scopé C1) : un agent Claude réel a comparé l'abondance FILET
  (*Calanus finmarchicus*, toutes tailles, 30 ind/m³) à l'abondance UVP du même taxon filtrée sur un axe majeur
  ≥1000 µm (20 ind/m³, 2 objets sur 3), en utilisant lui-même le chemin `filet_uvp_matches` → `taxon_mapping` →
  `uvp_object_sizes`, sans aide et sans deviner de lien. Chiffres confirmés indépendamment par `psql`.
  L'agent a aussi correctement signalé les limites scientifiques réelles (le taxon UVP est au niveau du genre
  `Calanus`, le mapping le déclare équivalent à l'espèce `C. finmarchicus` — à confirmer; profondeur du trait
  FILET absente; effectif minuscule dans ce jeu de test).
- 101 tests verts en direct contre Docker (19 vues, 355 colonnes documentées).

### 30 octobre 2026 — Taille réelle des objets EcoTaxa (taxon + taille sur une même ligne), vérifiée contre l'API réelle

- Identifiants EcoTaxa réels fournis par l'utilisateur pour cette vérification (jamais commités). Confirmé en
  direct sur l'API (`https://ecotaxa.obs-vlfr.fr/api`), avec les 23 projets réels du compte : les objets
  EcoTaxa portent déjà les mesures Zooprocess (`area`, `esd`, `major`, `minor`, en pixels), mais comme
  « colonnes libres » nommées par projet (`obj_free_cols` fait correspondre un libellé stable à un slot propre
  au projet, ex. `n01`). Pas tous les projets ne définissent pas `esd` (les projets UVP6 récents ne l'ont pas).
  Un libellé demandé qu'un projet ne connaît pas est retiré en silence de la ligne (pas renvoyé NULL), ce qui
  décale les colonnes suivantes : confirmé en testant ce cas précis sur un vrai projet avant d'écrire le
  chargeur, pour ne jamais lire une taille dans la mauvaise colonne.
- La calibration pixel→mm n'est pas un champ d'objet : elle vit sur l'acquisition EcoTaxa
  (`GET /acquisition/{id}.free_columns.pixel`, confirmée à 0,088 mm/pixel sur un vrai projet UVP5), pas
  interrogeable en lot avec les objets.
- Ajouts : colonnes `area_px/esd_px/major_px/minor_px` sur `warehouse.ecotaxa_object`, table
  `warehouse.ecotaxa_acquisition` (calibration par acquisition, sécurité par ligne héritée comme
  `ecotaxa_object`), vue `explore.uvp_object_sizes` (migration `sql/warehouse_ecotaxa_object_size_migration.sql`) :
  un objet identifié par ligne avec sa taille réelle en µm quand elle est calculable — referme l'écart trouvé la
  veille (taxon et taille ne se croisaient dans aucune vue). `scripts/populate_ecotaxa_objects.py` interroge
  désormais `obj_free_cols` par projet avant de demander les champs de taille, et charge la calibration par
  acquisition (un appel par acquisition distincte, mis en cache côté base).
- Vérifié en direct (Docker, jeu de test, compte scopé contrat C1) : tailles calculées correctes (2393,6 µm et
  987,99 µm pour un objet connu), compte hors contrat invisible. Un agent Claude réel a ensuite filtré
  l'abondance d'un taxon par gamme de taille réelle (µm) sans aide, avec le même soin pour agréger le volume du
  bin une seule fois.
- `tests/test_loaders_v1.py` étendu : trois projets de test avec des `obj_free_cols` différents (aucun, partiel,
  complet), vérifie que seules les tailles attendues sont chargées et que la conversion en µm est correcte pour
  un compte scopé. 101 tests verts en direct contre Docker.
- Non fait : chargement réel complet (23 projets, ~15M objets, plusieurs heures) — seule l'infrastructure est
  prête et testée; aucune donnée réelle n'a été chargée dans un warehouse de production.

### 30 octobre 2026 — Jointure FILET–UVP et filtrage par taille UVP vérifiés avec un agent réel (phases 2 et 4)

- Vérifié avec un agent Claude réel (Docker, compte scopé, chiffres indépendamment recalculés par `psql`) : la
  comparaison d'abondance FILET–UVP permet déjà de jouer sur la proximité temporelle (`time_gap_hours` dans
  `explore.filet_uvp_matches`/`explore.filet_uvp_abundance`, filtrable directement en SQL) et sur la proximité
  spatiale — non pré-calculée en vue, mais calculable par l'agent lui-même en PostGIS (`ST_Distance`) à partir de
  `latitude`/`longitude`, déjà exposées sur `explore.filet_samples` et `explore.uvp_samples`. L'agent a produit les
  deux filtres sans aide et avec des chiffres exacts.
- Lacune trouvée par le même test : les tailles de particules UVP (`warehouse.uvp_particle`, produit EcoPart LPM,
  chargé par `populate_ecopart.py`) n'étaient exposées par aucune vue `explore.*` — donc invisibles à tout agent.
  L'agent a correctement signalé l'absence plutôt que d'inventer un chiffre.
- Ajout : `explore.uvp_particle_sizes` (migration additive `sql/warehouse_uvp_particle_sizes_view.sql`), héritant
  automatiquement du filtre d'accès déjà posé sur `warehouse.uvp_particle` (vérifié : un compte scopé au contrat C1
  ne voit que son profil, pas celui d'un autre contrat). Documentée dans `scripts/warehouse_context.py` et
  `docs/WAREHOUSE_MCP_DICTIONARY.md`.
- Défaut trouvé et corrigé pendant le même test : la formule de densité par gamme de taille documentée
  (`SUM(particle_count)/SUM(sampled_volume_l)`) est fausse dès qu'on agrège plusieurs `size_class_key` d'un même
  bin, car `sampled_volume_l` est répété sur chaque classe et se trouve compté plusieurs fois au dénominateur.
  Un agent de test l'a détecté en recalculant lui-même et en comparant à la fiche; la fiche et l'exemple SQL ont été
  corrigés pour agréger le volume une seule fois par `uvp_bin_id` avant de diviser. Rejoué avec succès : l'agent
  retrouve maintenant le chiffre correct (1900 puis 6980 particules/m³ sur le jeu de test), confirmé indépendamment
  par `psql`.
- 101 tests verts en direct contre Docker (`WAREHOUSE_TEST_LIVE=1`), incluant les nouveaux cas.

### 29 octobre 2026 — Chargeurs et infrastructure vérifiés avant le premier chargement réel (phases 2 et 4)

- Chargement réel reporté : identifiants EcoTaxa et exports FILET absents de l'environnement, conteneur temporaire.
- Chaîne complète des chargeurs (échantillons et objets EcoTaxa, EcoPart, CTD Amundsen, zones CTD, FILET,
  appariements FILET–UVP) exécutée sans modification sur une v1, avec EcoTaxa et l'ERDDAP simulés et les fichiers
  de test, puis contrôle de la qualité et des droits (`tests/test_loaders_v1.py`).
- Défauts bloquants trouvés et corrigés : `COPY` direct vers des tables protégées (refusé pour un propriétaire
  non-superuser), `COPY FROM STDIN` dans un `psql -c` à plusieurs instructions (refusé par psql 16 : chargeurs
  d'objets et de CTD cassés quel que soit le rôle), base `postgres` utilisée par défaut par les chargeurs EcoTaxa,
  hôte et port ignorés par EcoPart, `shapely` et `pandas` non déclarés, versions chargées sans fiche de catalogue
  (donc sans contrat possible), déploiement en échec quand PostGIS est installé mais que le propriétaire n'est pas
  superuser.
- Ajouts : `scripts/load_warehouse.py` (vérification préalable, ordre, arrêt au premier échec, rejeu, audit),
  `scripts/requirements-warehouse.txt`, `warehouse_user.py contract`, [guide de chargement](docs/WAREHOUSE_LOADING.md).
- **`docker compose up` réel validé** (Docker disponible, contrairement à ce qui avait été supposé) : image PostGIS
  16.4/3.4.3, initialisation sans erreur, contexte publié, `--verify` → `PRÊT`, navigateur et filtre spatial, DbHub
  avec un compte personnel. 123 tests verts contre cette base. Ports de la base et du navigateur désormais limités à
  `127.0.0.1` (ils étaient ouverts sur toutes les interfaces). Constaté : rejouer le déploiement avec d'autres mots de
  passe coupe le navigateur; procédure précisée.
- Non vérifié : vraies API, volume réel, contenu des exports FILET.

### 29 octobre 2026 — Warehouse 1.0.0 : version stable prête à déployer (phases 2 et 4)

- [Note de version](docs/WAREHOUSE_RELEASE_V1.md) : contenu, procédure, vérification, décisions et risques acceptés.
- Version enregistrée dans la base à chaque déploiement (`warehouse.release_history`, `explore.warehouse_release`) avec
  le SHA-256 de chaque migration, par le script comme par l'initialisation Docker. Numéro défini une seule fois
  (`sql/warehouse_release.sql`).
- `deploy_warehouse_postgres.py --verify` : rapport de préparation sans modification (version, rôles, réglages,
  propriétaire en lecture-écriture, base fermée à PUBLIC, filtre sans contournement, sécurité forcée, contexte MCP,
  vues de découverte; notes sur l'adoption des vues et les contrats FILET). Verdict `PRÊT` / `NON PRÊT`.
- Défaut trouvé et corrigé : au premier déploiement, la vue de version, adoptée par le propriétaire des données, ne
  pouvait pas lire sa table encore détenue par le déployeur; et une requête en échec du rapport était muette.
- Initialisation Docker rejouée sans Docker, dans l'ordre et avec les noms du compose : `PRÊT`.
- Décisions : contrat d'accès par version (versions FILET aux contrats mélangés signalées), effectifs `pg_stat`
  acceptés (base dédiée si sensible), mot de passe local en fichier privé ou trousseau du système (`--keyring`).
- Correction d'honnêteté : les entrées précédentes comptaient comme « sur base réelle » tous les tests lancés avec la
  base active. Décompte exact : 92 tests, dont 23 interrogent une base réelle.
- Non validé : `docker compose up` réel, PostGIS, Codex, Claude Desktop, Windows, serveur distant, données réelles.

### 28 octobre 2026 — Sécurité : vues adoptées à la création, propriétaire non-superuser (phases 2 et 4)

- Déclencheur d'événement `warehouse_adopt_explore_views` : toute nouvelle vue `explore` est transférée au
  propriétaire des données dès sa création (déploiement en superuser). Sans superuser, avis explicite, audit et rejeu.
- **Défaut corrigé, présent dans les commits `b4e1675` et `ac6204b`** : sous PostgreSQL 16, le créateur d'un rôle en
  devient membre administrateur; la boucle de mise à jour des comptes restreints a donc pu mettre en lecture seule un
  propriétaire non-superuser au rejeu suivant. Seuls les hébergements sans superuser étaient concernés. La boucle ne
  vise plus que les comptes restreints, la session de déploiement force la lecture-écriture et le rejeu répare le
  propriétaire. Test de non-régression avec un propriétaire non-superuser.
- Plusieurs bases sur un serveur : délégation des groupes et des rôles de service documentée (`WITH ADMIN OPTION`).
- Preuves : 86 tests exécutés avec une base réelle active, verts deux fois, sans rôle ni base résiduels.

### 28 octobre 2026 — Connexion : diagnostics, expiration, TLS, installation hors ligne (phase 4)

- `warehouse_connect.py check` donne la cause d'un échec à partir des messages de DbHub (jamais affichés tels
  quels) : mot de passe refusé, TLS exigé, certificat non vérifiable, serveur injoignable, hôte inconnu, délai
  réseau. Chaque cas a été provoqué et vérifié sur PostgreSQL 16 avec DbHub 1.5.0.
- Expiration : date écrite dans le fichier d'identifiants, alerte 14 jours avant et après expiration;
  `rotate` conserve ou renouvelle la validité et refuse de réactiver un compte expiré sans `--expires-days`.
- TLS testé en local (certificat autosigné, `hostssl`) : `require` chiffre, `verify-full` exige le certificat
  d'autorité, désormais accepté (`WAREHOUSE_DB_SSLROOTCERT`, `init --sslrootcert`).
- `install-dbhub` installe la version épinglée dans `data/tooling/dbhub` pour les postes sans npm. Un défaut de
  chemin d'installation trouvé au test (un niveau de trop, masqué par une installation existante) a été corrigé
  et vérifié à vide.
- Preuves : 84 tests exécutés avec une base réelle active, verts deux fois. Non vérifié : serveur distant réel, Codex,
  Claude Desktop, Windows.

### 28 octobre 2026 — Accès des agents aux données : performance, CTD, zones inconnues, multi-sources (phases 2 et 4)

- **Performance** (base de test : 4,8 M d'objets, 600 000 abondances) : un compte restreint expirait à 30 s sur
  `explore.uvp_objects` et mettait 18,5 s sur les abondances. Causes trouvées dans les plans : politiques enfants
  réévaluant le droit pour chaque objet, contrôle de version par ligne, et jointure par fusion mal estimée par le
  planificateur sur `uvp_objects` (> 90 s même en superuser). Corrections : politiques ensemblistes,
  `warehouse.readable_versions()`, `enable_mergejoin = off` pour les rôles de lecture des agents. Après : 6,8 s,
  5,4 s et 0,55 s (restreint); 8,5 s, 7,0 s et 0,4 s (tout voir). Une variante `LATERAL` de la vue a été essayée et
  écartée (pas plus rapide).
- **Masqué ou absent** : vue `explore.my_datasets` (accès complet, partiel ou aucun par version, raison, source
  associée manquante), sans comptage. Recette agent : le compte limité à EcoTaxa explique désormais ses 0 profils par
  l'absence de droit EcoPart et sait quoi demander. Un texte inexact (dates déclarées exclues sans borne d'années)
  repéré pendant cette recette a été corrigé.
- **Multi-sources** : `warehouse_user.py --source ecotaxa,ecopart`, avertissement quand une seule source UVP est
  accordée, ligne `jeux lisibles` dans `warehouse_connect.py check`.
- **CTD** : zone propre aux profils (`sql/warehouse_ctd_zone_migration.sql`), attribuée par
  `assign_filet_zones.py --table ctd_profile` avec le registre existant (vérifié : Baie de Baffin `assigned`,
  point du Pacifique `outside`, profil sans coordonnées `unresolved`).
- **Zones et dates inconnues** : option explicite par droit `include_unknown_scope` (`--include-unknown`), refus
  par défaut conservé.
- **Contexte MCP sous Docker** : service ponctuel `warehouse-context` après un contrôle de santé de la base. Non
  exécuté (Docker absent ici). Contexte MCP enrichi (my_datasets, jointures externes, multi-sources).
- Preuves : 52 tests exécutés avec PostgreSQL 16 réel actif (80 au total), installation portable rejouée.
- Limites : 15 M d'objets extrapolé (parcours complet de `uvp_objects` proche de 30 s pour un compte tout voir),
  réglage du planificateur à réévaluer si les vues changent.

### 28 octobre 2026 — Rôles, accès par périmètre, FAIR, connexion DbHub et documentation (phases 2 et 4)

- Rôles clarifiés ([WAREHOUSE_ROLES.md](docs/WAREHOUSE_ROLES.md)) : `sql/warehouse_roles.sql` est la
  source unique. Écarts corrigés : Docker ne créait aucun rôle de lecture, le navigateur utilisait le rôle
  propriétaire, les vues créées après provisionnement étaient illisibles, la migration EcoPart manquait au compose.
- Préparation FAIR ([exigences](docs/WAREHOUSE_FAIR_REQUIREMENTS.md)) : migration additive, identifiant
  persistant unique, contrainte de publication, vues `explore.dataset_catalog`, `fair_readiness` et
  `fair_column_coverage`. **Le warehouse n'est pas FAIR** : fiches en brouillon (39 sur l'instance locale au 8 octobre), aucun
  identifiant ni licence; dépôt, licence, niveaux d'accès, vocabulaires et sauvegarde restent à décider (PGD §8).
- Accès par source, contrat, zone et année ([WAREHOUSE_ACCESS_CONTROL.md](docs/WAREHOUSE_ACCESS_CONTROL.md)) :
  sécurité par ligne forcée sur 23 tables, refus par défaut, propriétaire non-superuser dédié. Limites :
  CTD sans zone, performance non mesurée sur 15 M d'objets, toute vue `explore` créée ensuite doit être
  rattachée au propriétaire des données (`explore.access_audit`, `--check` code 3).
- Déploiement `scripts/deploy_warehouse_postgres.py` rejouable; comptes via `scripts/warehouse_user.py`;
  branchement via `scripts/warehouse_connect.py` ([guide](docs/WAREHOUSE_CONNECT.md)). Le déploiement
  publie maintenant le contexte MCP, absent hors installation Windows.
- Preuves : 41 tests exécutés avec PostgreSQL 16 réel actif (propriétaire superuser et non-superuser), recette avec le
  vrai DbHub 1.5.0 (mauvais mot de passe refusé, rotation, révocation) et `claude mcp list` connecté.
  Échec relevé : les tests `test_populate_*` ne s'exécutent pas sans `pytest` (préexistant).
- Documentation : point d'entrée [WAREHOUSE_README.md](docs/WAREHOUSE_README.md), `example.warehouse.env`,
  guide Docker corrigé (trois mots de passe, publication du contexte MCP), dictionnaire MCP régénéré, renvois
  entre guides. Liens relatifs vérifiés.
- Recette avec agents (Claude Code non interactif, vrai DbHub, deux comptes) : périmètre, catalogue et filtrage
  corrects, écriture refusée, limites signalées. Règle découverte et documentée : une vue multi-sources exige
  un droit par source (EcoTaxa et EcoPart pour les vues UVP). Suppression de la branche
  `claude/warehouse-fair-roles` refusée par la passerelle git (403), à faire dans GitHub.
- Recette sur valeurs avec un agent (données fictives) : abondances par taxon recalculées par l'agent, égales à la
  vérité terrain (4 valeurs, 12 lignes visibles sur 60). Contrôle d'évasion fait directement en SQL avec le compte
  restreint : 18 tentatives (tables brutes, `SET ROLE`, `row_security = off`, écriture des droits, fichier serveur,
  `COPY PROGRAM`…) refusées par la base; ajouté aux tests. Fuites de métadonnées sans donnée relevées et
  documentées : effectifs globaux (`pg_stat`), estimations `EXPLAIN`, noms de tables. Un agent a refusé de mener
  lui-même la mission d'évasion; le contrôle a été fait par le développeur.
- Non vérifié : `docker compose up`, PostGIS et le navigateur spatial, Codex, Claude Desktop, Windows
  pour les nouveaux scripts, TLS distant. Phases non clôturées.

### 21 octobre 2026 — Cartographie et bibliothèques océanographiques dans le MCP

- Fiche graphs étendue : Cartopy, Folium, GeoPandas/Shapely/pyproj, cmocean,
  oceans, gsw/TEOS-10 et xarray selon besoin. Règles d’ordre des coordonnées,
  CRS/projections, géodésie, attributions et fonctionnement réseau des fonds.
- Conventions physiques et unités exigées avant calcul; pas de substitution
  implicite salinité pratique/absolue, température ou pression/profondeur.
  « oceangs » n’étant pas un nom confirmé, oceans est documenté comme option
  d’analyse océanographique vérifiée, sans prétendre identifier le package voulu.
- TDD : test cartographique en échec avant ajout, puis 8 tests de contexte
  réussis; métadonnées et documentation générée republiées. Les bibliothèques
  restent à installer selon le calcul demandé; aucun calcul scientifique réalisé.
- Recette MCP réelle réussie : les noms Cartopy, Folium, oceans, TEOS-10 et
  cmocean sont bien présents dans la fiche renvoyée par DbHub.

### 21 octobre 2026 — Règles de graphiques dans le contexte MCP

- Fiche `warehouse_context(topic=graphs)` publiée et annoncée dans l’overview
  et la description de l’outil : bibliothèques Python, style, unités, axes,
  palette/statuts, exports PNG/SVG/CSV et provenance SQL reproductible.
- Règles explicites contre les graphiques sur données inventées ou résultat
  tronqué, les normalisations implicites et la confusion entre lien accepted
  et validation scientifique. Vérification des dépendances requise avant tracé.
- TDD : contrat en échec avant ajout de la fiche, puis 6 tests de contexte
  réussis. Publication SQL des métadonnées et contrôle des rôles réussis;
  documentation générée actualisée. Aucune bibliothèque graphique installée
  ni figure scientifique produite par ce changement de contexte.
- Recette MCP réelle réussie : la fiche graphs renvoie Matplotlib, le statut
  Exploratoire et les exports CSV; les contrôles métier/SQL existants passent.

### 21 octobre 2026 — Recherche de sauvegarde dans l’historique de la branche

- Audit de `codex/validate-warehouse-v1` au commit `0483871` : 869 commits
  accessibles et 2 054 contenus de fichiers examinés, y compris fichiers supprimés.
- Aucun chemin de fichier SQLite/dump/backup trouvé. Inspection des signatures
  binaires : aucune base SQLite, dump PostgreSQL custom/SQL, archive ZIP/gzip
  ou pointeur Git LFS détecté; inventaire LFS également vide.
- Seuls les DDL/migrations et les mentions documentaires de sauvegardes
  restent disponibles. Limite : audit de l’historique accessible depuis cette
  branche; n’inclut pas d’autres branches, releases, artifacts ou objets orphelins.

### 21 octobre 2026 — Contexte métier distribué via le MCP (phases 1 et 2)

- Dictionnaire versionné des 16 vues scientifiques : usage, grain, clés de
  jointure, provenance par SQL réel, limites et exemples. Publication de
  commentaires sur 304 colonnes; unités inconnues explicitement à confirmer.
- Surfaces lecteur additives : `explore.warehouse_context`,
  `explore.warehouse_dictionary`, `explore.dataset_versions`. Aucun secret
  ni URI locale de manifeste exposé par l'inventaire des versions.
- Outil DbHub `warehouse_context` avec fiche générale, fiche par vue ou
  ensemble des fiches. Description invitant le modèle à lire le contexte
  avant analyse; aucune injection automatique de tout le dictionnaire promise.
- TDD : tests du contrat écrits et exécutés en échec avant implémentation,
  puis 4 tests réussis. Recette MCP réelle réussie : contexte général et
  FILET CTD, dictionnaire SQL, commentaire de volume renvoyé par search_objects,
  requête lecteur; les droits bruts restent limités.
- [Dictionnaire Markdown](docs/WAREHOUSE_MCP_DICTIONARY.md) généré depuis
  l'instance et le même contenu métier. Risques de doublons/versions de
  `filet_uvp_abundance` documentés; calcul scientifique non déclaré validé.
- Limites : base toujours vide, nouveau chargement du catalogue MCP dans Codex
  requis. La disponibilité du contexte ne garantit pas que chaque modèle le
  consulte systématiquement. Phases non clôturées.

### 21 octobre 2026 — Warehouse portable, interface et DbHub dans Codex (phases 1 et 2)

- PostgreSQL 16.15/PostGIS 3.6.2, Python 3.11.9, Node 24.22.0 et DbHub 1.5.0
  installés sous `data/tooling/`, sans Docker ni service Windows.
- Cluster et base vide initialisés; interface lancée sur `127.0.0.1:8090`.
  Les huit routes HTTP de recette répondent 200, avec et sans filtre spatial.
- Rôles `warehouse_reader` et `warehouse_navigator` contrôlés en SQL réel :
  lecture seule, absence de droits DDL/écriture et privilèges administratifs,
  lecture brute refusée au lecteur MCP. Calcul géodésique PostGIS vérifié.
- DbHub : handshake MCP, découverte et requête SQL lecteur réussis;
  serveur `neolab-warehouse` enregistré dans la configuration personnelle
  Codex sans secret. Rechargement de Codex requis pour le catalogue d'outils.
- Tests exécutés : 20 schéma, 6 audit, 2 contrat spatial, 12 UI et contrôle
  PowerShell du lanceur, tous réussis. Les blocages Windows initdb ont été
  résolus avec les chemins courts et l'extraction complète du runtime.
- Livrable : résumé opérationnel du 21 octobre (archivé depuis, voir WAREHOUSE_RELEASE_V1.md et WAREHOUSE_ROLES.md), procédure
  [portable](docs/WAREHOUSE_PORTABLE.md), scripts de cycle de vie et recette.
- Limites : archive et sauvegarde absentes, aucune donnée scientifique
  restaurée; recette visuelle et conversation Codex après rechargement non
  exécutées. Phases non clôturées. Aucun changement publié ou poussé;
  suivi GitHub Project non synchronisé dans cette session.

### 21 octobre 2026 — Écart spatial de comparaison FILET–UVP (phase 2)

- Ajout d'un seuil spatial facultatif en km, combiné au seuil temporel sur
  les paires stockées. Distance géodésique PostGIS, affichée dans les fiches;
  même filtre sur carte, compteurs et liste des correspondances.
- Contrats écrits avant implémentation, tests UI et recette live étendus
  (seuil nul, sous-ensembles, cohérence des trois routes).
- Tentative d'exécution Python bloquée avant collecte : interpréteur absent.
  Node et Docker indisponibles dans le PATH; recette UI/PostgreSQL non exécutée.
  `git diff --check` est le seul contrôle exécuté avec succès.
- Limite : aucune nouvelle paire spatiale n'est créée et aucun statut
  scientifique n'est modifié; la phase reste en cours.

### 21 octobre 2026 — Documentation, accès lecteur et qualification (phases 1 et 2)

- Contrat et procédure regroupés dans
  [WAREHOUSE_ACCESS_QUALIFICATION.md](docs/WAREHOUSE_ACCESS_QUALIFICATION.md) :
  grains, références du dictionnaire, connexion lecteur et recette MCP à effectuer.
- Tests de contrat écrits avant `scripts/audit_warehouse.py` : absence de
  fallback propriétaire, délais et lecture seule, découverte sans scan,
  vues manquantes explicites et restitution des mesures par version.
- Diagnostic ajouté : inventaire des colonnes accessibles puis scan taxonomique
  uniquement avec `--qualify`. Identifiant, libellé, annotation et contrat FILET
  sont distingués; aucun rapprochement scientifique n'est créé.
- Tentative de test : `python -m unittest discover -s tests -p test_warehouse_audit.py`
  échoue avant collecte car Python est absent (raccourci Microsoft Store).
  Aucun résultat rouge/vert TDD exécuté n'est donc revendiqué.
- Limites : ni connexion PostgreSQL live ni configuration DbHub/MCP validée
  dans cet environnement; aucun credential local trouvé ou affiché. « Données
  contrats » reste à clarifier. Phases et use cases restent en cours.

### 8 octobre 2026 - Brouillon PGD/DMP et audit des métadonnées (phases 1 et 2)

- Audit live en lecture seule : métadonnées EcoTaxa et FILET, versions,
  manifestes, empreintes et relations de provenance inventoriés.
- Constats : `dataset_version` conserve source, version, URI et SHA-256; EcoTaxa
  compte 6 137/6 138 samples datés, 3 944 géolocalisés et aucun `instrument`
  ou `annotation_status` chargé; FILET conserve les métadonnées d'échantillon
  mais les deux volumes sont partiels (4 483/6 102 et 2 377/6 102).
- Brouillon ajouté dans [docs/WAREHOUSE_DMP_DRAFT.md](docs/WAREHOUSE_DMP_DRAFT.md)
  avec inventaire, cycle de vie, standards, accès, préservation, décisions et
  proposition de catalogue `dataset_metadata`, `dataset_file`,
  `column_metadata` et `validation_run`.
- Aucune migration scientifique ou publication n'a été exécutée : noms,
  licence, dépôt, rôles et conservation doivent être validés avant publication;
  le contrat SQL additif de catalogue est préparé et appliqué localement dans
  `sql/warehouse_metadata_migration.sql`.
- Les métadonnées sources ont été vérifiées : EcoTaxa conserve 70 noms de
  champs JSON sur 6 118 samples ayant au moins une clé; EcoPart conserve
  59 801 lignes source de bins, 585 lignes `metadata` et 3 535 lignes
  `zooplankton`. Aucun champ EcoTaxa absent n'est complété automatiquement par
  EcoPart sans lien prouvé.
- Sauvegarde opérationnelle vérifiée :
  `data/warehouse_backups/neolab_warehouse_20261008.dump` (format custom
  PostgreSQL 16, environ 243 Mo). Le rôle `warehouse_reader` a été créé et
  testé : lecture des vues `explore.*` uniquement, accès aux tables
  `warehouse.*` et opérations DDL refusés. Les identifiants restent dans le
  fichier local ignoré `data/warehouse_backups/warehouse_reader.env`.

### 7 octobre 2026 - Redémarrage du warehouse local (phase 2)

- Docker Desktop démarré, puis stack reconstruite et lancée avec
  `docker-compose.warehouse.yml` et la configuration locale ignorée par Git.
- PostgreSQL `neolab-warehouse-db` accepte les connexions sur le port hôte
  `55432`; le navigateur `neolab-warehouse-navigator` répond sur
  `http://localhost:8090`, avec `/health` et les routes `/api/options` et
  `/api/coverage` en HTTP 200.
- Contrôle de couverture après démarrage : 585 profils UVP, 10 479 780 objets
  mappés, 380 profils CTD et 6 102 échantillons FILET. Le volume persistant
  existant a été réutilisé; aucune recharge de données ni migration exécutée.
- Limite : ce démarrage local ne valide ni le déploiement VPS, ni la
  restauration, ni l'accès IDEA strictement en lecture seule. La phase 2 reste
  en cours.

### 7 octobre 2026 - Diagramme de classes du warehouse (phases 1 et 2)

- Diagramme de classes consolidé à partir du DDL principal et des migrations
  additives EcoPart et zones FILET : 26 tables persistantes, clés, relations,
  grains métier et inventaire des vues `explore.*`.
- Livrables : `docs/warehouse_class_diagram.mmd` modifiable,
  `docs/WAREHOUSE_CLASS_DIAGRAM.md` et
  `output/pdf/warehouse_database_class_diagram.pdf` en A3 paysage.
- Preuve de livraison : génération PDF reproductible avec ReportLab, rendu des
  sept pages en PNG et inspection visuelle sans texte coupé ni chevauchement.
- Limite : le service PostgreSQL warehouse n'était pas actif pendant la
  génération. Le document représente le schéma versionné dans le dépôt, pas
  une introspection live. La phase 1 reste en cours jusqu'à la revue d'équipe.

### 5 octobre 2026 — Vérification pré-démo des données affichées (phases 2 et 3)

- La chaîne en lecture seule PostgreSQL → API → interface concorde sur la vue globale : 585 profils UVP, dont 386 géolocalisés et 199 sans coordonnées, 10 479 780 objets EcoTaxa associés, 380 profils CTD et 6 102 échantillons FILET. La période combinée des couches visibles est du 9 juillet 2010 au 17 octobre 2025.
- Le scénario « Baie de Baffin, 2024 » a été rejoué dans l’interface et comparé à l’API : 123 profils UVP, 4 279 581 objets, 94 profils CTD et 272 échantillons FILET, du 12 août au 13 octobre 2024. Ce total FILET remplace le chiffre historique de 558 obtenu avant l’application stricte des polygones aux coordonnées.
- Le mode FILET–UVP à 10 h affiche uniquement les paires acceptées cartographiables : 20 profils UVP, 130 échantillons FILET, 12 profils CTD et 554 752 objets EcoTaxa. Les dates affichées combinent correctement les deux couches, du 14 juillet au 18 octobre 2024.
- Preuves automatisées : 68 contrôles live SQL/API réussis, 45 zones GeoJSON hors périmètre canadien ignorées explicitement, et 10 contrats UI réussis. Les 20 zones proposées par l’interface passent un oracle spatial Shapely indépendant ; les années, unions de zones, projets, compteurs, dates et correspondances sont couverts.
- Limite visible et assumée : la vue « Toutes les données » inventorie tout le warehouse, y compris les positions hors Arctique canadien. Les 199 profils UVP sans coordonnées sont comptés globalement mais exclus de tout filtre spatial.
- Correctif UX pré-démo : chaque mise à jour de filtre affiche désormais un indicateur léger sur la carte. Les contours de zones sont recalculés d’après les points des couches visibles ; une zone sans UVP disparaît lorsque FILET est masqué, y compris dans une sélection de plusieurs zones. Le cas Baie d’Hudson confirme 235 FILET et 0 UVP. La recette réelle et 10 contrats UI passent après reconstruction du service local.
- Audit UX documenté dans `docs/WAREHOUSE_NAVIGATOR_UX_AUDIT.md`. Le suivi distingue trois lots : clarté de la démonstration, exploration efficace, puis cartographie arctique et accessibilité. Les cinq priorités immédiates sont les filtres actifs visibles, la légende dynamique, l’accès au résumé à largeur moyenne, les états vides explicites et un modèle unique d’application des filtres. Aucun de ces éléments n’est déclaré terminé avant sa recette dans l’interface.
- Lot A de l’audit exécuté : les filtres année/zone/projet sont préparés puis appliqués en une requête, les pastilles sont supprimables, la légende suit les couches, le résumé compact reste visible à 884 px et les états vides nomment la source concernée. Contrôles : 10 tests UI, 68 contrôles live SQL/API, 45 cas hors périmètre explicitement ignorés et recette navigateur réelle après reconstruction Docker. Les lots B et C restent planifiés.

### 27 septembre 2026 — Recette MVP en cours (contribution à la phase 3)

- Suite opt-in `NAVIGATOR_LIVE=1 pytest -q tests/test_navigator_live.py` : comparaison en lecture seule SQL/API, identité des échantillons par polygone avec un oracle Shapely indépendant, plages temporelles, métadonnées et écarts horaires, paramètres invalides.
- Premier audit exploitable : 27 réussites, 8 échecs spatiaux MEOW, 45 zones hors périmètre ignorées. Exemple : 1 576 FILET géographiquement dans MEOW Baffin Bay–Davis Strait étaient omis malgré la concordance carte/compteur. Cause : les FILET déjà affectés à une zone unique n’étaient pas testés contre les autres polygones.
- Correctif local : appliquer l’intersection géographique à tous les FILET géolocalisés, en conservant les métadonnées d’affectation. Nouvelle exécution en cours. Les couches, dates affichées, mode comparaison et interactions restent à vérifier avant clôture ; aucune validation complète annoncée.
- Décision confirmée : les filtres spatiaux UVP suivent eux aussi uniquement les coordonnées et les polygones du registre. Un profil sans coordonnées reste dans l’inventaire global mais ne peut plus entrer dans une zone via un ancien nom de zone.
- Audit final : 68 contrôles live SQL/API réussis et 45 cas hors périmètre canadien explicitement ignorés ; les 20 zones exposées par le navigateur passent l’oracle géographique indépendant. Les six contrats UI, les 22 tests warehouse et le build Docker du navigateur passent. La recette MVP locale est clôturée ; les validations scientifiques d’équipe et le déploiement VPS restent hors de cette recette.

## Objectif

Centraliser les données NeoLab dans un warehouse SQL mis à jour avec les
nouvelles données et directement interrogeable par IDEA. La V1 doit permettre à
IDEA de sélectionner les données en lecture seule par SQL, puis de réaliser les
analyses et graphiques en Python avec un chemin plus simple et reproductible.

Le périmètre V1 couvre quelques campagnes représentatives et les données
EcoTaxa, EcoPart, CTD, FILET ainsi que leurs métadonnées communes. L’intégration
complète des données historiques du laboratoire reste hors périmètre.

## Résultat attendu au 30 novembre

- warehouse V1 déployé et documenté ;
- accès SQL stable et strictement en lecture seule pour IDEA ;
- campagnes, clés, relations, unités et provenance documentées ;
- scénarios de référence validés de bout en bout ;
- flux et outils devenus inutiles identifiés.

## Règle de suivi

Ce fichier est la source de vérité du calendrier, de l’avancement et des
critères de sortie. Toute intervention doit commencer par identifier la phase et
le résultat attendu auxquels elle contribue. Après chaque travail réellement
exécuté, l’agent met à jour le statut et le journal ci-dessous avec les tests,
scénarios ou limites observés. Une phase passe à **Terminée** uniquement lorsque
son critère de réussite est vérifié. Une modification de code ou un test
unitaire isolé ne suffit pas à valider un scénario conversationnel.

Le suivi opérationnel peut être reproduit dans GitHub Project, mais les statuts
doivent rester synchronisés avec ce fichier versionné.

## Vue d’ensemble

| Phase | Période | Livrable | Critère de réussite | État |
|---|---|---|---|---|
| 1. Cadrage | 14–25 sept. | Schéma V1 et périmètre validés | Revue d’équipe confirmant que les jeux EcoTaxa, EcoPart, CTD et FILET retenus peuvent être reliés | En cours — proposition de schéma rédigée, revue attendue |
| 2. Construction du warehouse V1 | 28 sept.–9 oct. | Warehouse échantillon utilisable en local | Données attendues retrouvées par SQL et jointures de référence cohérentes | En cours - stack locale et API actives; validation des jointures à consolider |
| 3. Validation des données | 12–23 oct. | Jeu de tests et anomalies documentées | Cas de référence conformes aux sources originales | À faire |
| 4. Déploiement | 26 oct.–6 nov. | Warehouse V1 accessible sur le VPS | Connexion stable, restauration testée et aucune écriture possible depuis IDEA | À faire |
| 5. Intégration IDEA | 9–20 nov. | IDEA travaille directement sur le warehouse | Plusieurs scénarios exécutés sans export ni enrichissement externe intermédiaire | À faire |
| 6. Simplification et validation finale | 23–30 nov. | Architecture V1 validée et documentée | Scénarios retenus réussis de bout en bout avec un flux plus simple et reproductible | À faire |

## Phase 1 Cadrage

**Sous-étapes**

- partir du projet IDEA Hawaii et l’adapter use case par use case prioritaire ;
- choisir les campagnes et jeux de données de la V1 ;
- revoir le schéma existant avec Cyril ;
- définir les relations et identifiants communs.

**Validation attendue :** revue avec l’équipe confirmant que les données
EcoTaxa, EcoPart, CTD et FILET sont reliables pour les cas retenus.

## Phase 2 Construction du warehouse V1

**Sous-étapes**

- créer la base SQL ;
- importer EcoTaxa et EcoPart ;
- importer CTD et FILET ;
- documenter les tables, unités, clés et sources.

**Validation attendue :** les données prévues sont retrouvées par SQL et les
jointures de référence produisent les résultats attendus.

## Phase 3 Validation des données

**Sous-étapes**

- comparer les données aux sources originales ;
- vérifier les profils, dates, profondeurs et la taxonomie ;
- tester plusieurs jointures connues ;
- consigner les écarts et leur résolution.

**Validation attendue :** les cas de référence donnent les mêmes informations
que les sources originales, dans les tolérances documentées.

## Phase 4 Déploiement

**Sous-étapes**

- déployer PostgreSQL sur le VPS ;
- configurer les accès, sauvegardes et mesures de sécurité ;
- tester une restauration ;
- donner à IDEA un accès en lecture seule.

**Validation attendue :** la connexion est stable, la restauration est testée
et l’identité utilisée par IDEA ne peut effectuer aucune écriture.

## Phase 5 Intégration IDEA

**Sous-étapes**

- connecter IDEA au warehouse SQL ;
- tester la compréhension du schéma ;
- sauvegarder les sous-ensembles utiles dans le workspace ;
- exécuter les analyses Python et produire les graphiques.

**Validation attendue :** plusieurs scénarios sont exécutés de bout en bout sans
export ni enrichissement externe intermédiaire.

## Phase 6 Simplification et validation finale

**Sous-étapes**

- comparer le nouveau flux au flux actuel ;
- identifier les outils devenus inutiles ;
- tester la non-régression ;
- documenter la V1 et la suite.

**Validation attendue :** les scénarios retenus fonctionnent de bout en bout
avec un flux plus simple, vérifiable et reproductible.

## Journal d’avancement

### 11 septembre 2026 Préparation du socle

- dépôt initialisé depuis IDEA Hawaii `next-dev` au commit
  `5b1322dbe68fefd31fc1de29a076b1746a36c5d7` ;
- ancienne version NeoLab préservée dans l’archive locale
  `../IDEA-archive-20260911` ;
- stack locale macOS ARM64 démarrée avec Open WebUI, LangGraph, LiteLLM,
  Langfuse, PostgreSQL, Redis et sandbox Docker ;
- modèle local configuré sur `gpt-5.5` et Pipe IDEA rendu disponible dans Open
  WebUI ;
- 268 tests de la suite principale et 11 tests du sandbox réussis ;
- exécution Python réelle et persistance d’un DataFrame dans un noyau actif
  vérifiées.
- RAG natif Open WebUI désactivé globalement pour les nouveaux téléversements
  locaux : le client demande `process=false` et le serveur impose ce choix même
  lorsqu’un ancien client demande `process=true` ; test HTTP réussi avec
  réponse `data: {}`, journal serveur `process=False`, sans suivi de traitement
  ni génération d’embeddings ;
- 24 tests ciblés réussis pour la politique sans RAG et le déploiement des
  assistants Open WebUI ;
- observabilité branchée sur le projet Langfuse US Cloud : diagnostic du rejet
  401 causé par l’hôte local et un caractère non ASCII dans la clé secrète,
  correction de la paire, hôte Compose rendu configurable, puis trace d’un
  appel `gpt-5.5` validée par l’API Cloud ;
- suivi utilisateur/session du mode Normal validé de bout en bout via
  Open WebUI/LangGraph/LiteLLM : la trace Cloud contient l’email comme
  `userId` et la conversation comme `sessionId` ; le mode Advanced reste hors
  de ce périmètre tant que son chemin `/v1/responses` ne conserve pas ces
  attributs avec la version LiteLLM épinglée ;
- traitement d’embeddings lancé par l’ancien chemin sur un CSV arrêté avant le
  déploiement du correctif.

### 14 septembre 2026 Rechargement de la clé OpenAI

- `OPENAI_API_KEY` est présente dans `.env` et valide par `curl` ;
- après libération de caches locaux et redémarrage de Docker Desktop, les
  services LangGraph/LiteLLM ont été recréés ;
- les empreintes de la variable dans les deux conteneurs correspondent à `.env`
  et `GET /health` de LangGraph répond correctement.

**Limite :** le test de santé ne remplace pas encore un échange conversationnel
complet avec appel d’outil depuis Open WebUI.

### 21 septembre 2026 Enrichissement spatial FILET

- `warehouse.filet_sample` porte désormais les mêmes métadonnées de zone maritime versionnées que les profils : clé, nom, source, version et statut d’affectation ; migration idempotente dans `sql/warehouse_filet_zone_migration.sql`.
- Les **6 102** échantillons FILET géolocalisés ont été classés avec `shared_data/geo/zones_registry.geojson` (`registry-v1`) : **5 239 assigned**, **863 ambiguous**. Les cas ambigus restent explicites, sans choix arbitraire entre zones qui se chevauchent.
- Le chargeur FILET réapplique cette affectation lors de chaque recharge, et `explore.filet_samples` expose les colonnes.
- Le navigateur filtre maintenant FILET directement sur `filet_sample.marine_zone_name` ; contrôle : la Baie de Baffin retourne **1 467** échantillons FILET à la fois dans la synthèse et sur la carte.

### 18 septembre 2026 Proposition de schéma warehouse

- Proposition documentée dans [docs/WAREHOUSE_PROPOSAL.md](docs/WAREHOUSE_PROPOSAL.md) :
  grains FILET/UVP/CTD, sources EcoTaxa/EcoPart/Amundsen, versions, appariements,
  vues SQL en lecture seule et journal d'exploration séparé.
- Documentation locale et pages officielles des fournisseurs consultées.
- Limites : archive absente au chemin prévu ; aucun export métier inspecté,
  aucune jointure exécutée, aucun test runtime ni validation scientifique.
- Phase 1 en cours, non validée. Prochaine étape : revue des exports et des
  règles d'appariement avec Cyril et l'équipe sur une campagne représentative.
- GitHub Project : aucun identifiant de projet trouvé dans les références
  locales consultées ; synchronisation non effectuée. Aucun push ni publication.

### 18 septembre 2026 Jointures et calculs confiés aux outils

- Cadrage corrigé sur demande : jointures scientifiques et calculs métier
  confiés à des outils déterministes ; exploration par l'agent de relations
  préparées. Appariement FILET/UVP ↔ CTD spatial et temporel, extraction
  verticale séparée.
- [Brouillon SQL pour revue](sql/warehouse_schema_proposal.sql) ajouté :
  données versionnées, unités FILET/UVP/CTD, observations, politiques,
  exécutions, correspondances, résultats et historique d'exploration.
- Limites : DDL non exécuté, outils non implémentés, droits et publication
  immuable à construire ; pas de validation scientifique ni de fin de phase.
  GitHub Project reste non synchronisé, faute d'identifiant identifié.

### 18 septembre 2026 Recentrage sur SQL vers DataFrame

- La correction utilisateur remplace le cadrage précédent : IDEA génère du
  SQL en lecture seule et charge les résultats dans son notebook. `work.*`
  retiré du brouillon ; relations connues et vues simples prioritaires.
- Code public EcoPart consulté au commit
  `4dcd5968bb299b42d2f38406b19b8ca8354503f8` : CTD importée par nom
  d'échantillon dans le projet, export EcoTaxa via projet lié et `orig_id`.
  Ces preuves ne confirment pas la version ni les exports NeoLab.
- Proposition et SQL révisés. Clés FILET et liens avec le catalogue CTD
  Amundsen encore à vérifier sur les données ; aucun appariement, DDL ou
  scénario notebook exécuté. Phase 1 toujours en cours. GitHub Project
  non synchronisé, identifiant toujours non disponible.

### 18 septembre 2026 Vérification des exports FILET réels

- CSV retrouvés sur le Bureau et inspectés en lecture seule : métadonnées
  6 105 lignes, abondances/biomasses 5 047 lignes, dictionnaire de 93 colonnes.
  Empreintes et preuves dans [docs/FILET_EXPORT_REVIEW.md](docs/FILET_EXPORT_REVIEW.md).
- Jointure pandas `many_to_one` sur SAMPLE_ID + ANALYSIS_ID : 4 941 appariés,
  106 non appariés (9 analyses de 2024 absentes des métadonnées), sans
  multiplication des lignes. Aucun écart sur six champs de contexte comparés.
- Schéma FILET corrigé : multiples analyses/filets, valeurs déjà calculées,
  deux volumes, biomasses et stades/agrégats distincts, LEFT JOIN explicite.
- Limites : aucun identifiant CTD/EcoTaxa explicite dans ces exports ; DDL
  non exécuté, scénario IDEA non testé. Phase 1 en cours ; GitHub Project
  non synchronisé, identifiant non disponible. Aucun fichier source modifié.

### 18 septembre 2026 Recherche de l'ancien schéma et exports UVP

- Ancien schéma SQLite non retrouvé ; le dossier `~/PROJET_INFO/IDEA` ne
  contient aucun fichier. Archive attendue toujours absente.
- Exports et script R retrouvés dans Downloads/UVP_metrics_for_MCA : 30 profils
  communs EcoTaxa/EcoPart, clé profil + profondeur EcoPart unique. Jointure
  reproduite en lecture seule : 137 128/137 128 objets appariés sans duplication.
- Preuves dans [docs/UVP_EXPORT_REVIEW.md](docs/UVP_EXPORT_REVIEW.md).
  Champ CTD présent mais partiellement vide ; lien Amundsen non vérifié.
  Aucun changement runtime/DDL, phase 1 non clôturée. GitHub Project reste
  non synchronisé faute de référence identifiée.

### 18 septembre 2026 Ancien schéma retrouvé dans Git

- Ancien code NeoLab retrouvé dans `origin/main` (`475af5d`) et les branches
  EcoPart/comparabilité. Inspection par `git show`, aucun checkout.
- DDL SQLite EcoTaxa et manifeste EcoPart, pont SQL/DataFrame, contrat de
  jointure EcoTaxa/EcoPart et matcher CTD par nom de fichier examinés.
  Références dans docs/LEGACY_WAREHOUSE_REFERENCES.md (archivé depuis, contenu repris dans le schéma et WAREHOUSE_ARCHITECTURE.md).
- La recherche antérieure concernait les fichiers sur disque : le code
  historique est disponible dans Git, les bases de données remplies ne sont
  pas retrouvées. Aucun test historique exécuté, phase 1 toujours en cours.
  GitHub Project non synchronisé faute de référence identifiée.

### 18 septembre 2026 Validation documentaire de la proposition V1

- Contrat V1 récapitulé : métadonnées EcoTaxa conservées, UVP dérivé
  EcoTaxa/EcoPart par bin, FILET importé avec ses abondances normalisées,
  CTD reliée au profil et surface SQL pour DataFrame.
- Diagramme ajouté dans [docs/WAREHOUSE_ARCHITECTURE.md](docs/WAREHOUSE_ARCHITECTURE.md).
- Neuf tests de contrat ajoutés dans `tests/test_warehouse_schema.py` : couches,
  grains, formule UVP, agrégation pondérée, conservation des valeurs FILET,
  liens CTD et conservation des non-appariés. Résultat : 9/9 réussis.
- Cette entrée documente l'état initial de la proposition ; la couche
  `filet_uvp_abundance` et le DDL exécutable sont détaillés dans l'entrée
  suivante. Phase 1 reste en cours ; aucun use case conversationnel déclaré
  validé.

### 18 septembre 2026 Couche d'exploration EcoTaxa/EcoPart/CTD

- Le brouillon SQL expose le parcours direct
  `uvp_projects → uvp_samples → uvp_objects → uvp_taxon_abundance`, avec
  rattachement objet → bin EcoPart, volume échantillonné et métadonnées
  EcoTaxa conservées.
- Les liens `ecotaxa_ctd_profile`/`ecotaxa_ctd` donnent accès au profil puis
  aux mesures CTD sans refaire la jointure dans l'agent. La comparaison FILET
  reste disponible par `filet_uvp_matches` et `filet_uvp_abundance`, avec une
  table de mapping taxonomique explicite.
- Validation : 11 tests de contrat Python réussis, `git diff --check` réussi,
  et exécution complète du DDL dans une base PostgreSQL temporaire réussie.
- Limites : ingestion réelle, cardinalités CTD et taxonomie doivent encore
  être vérifiées sur un jeu de campagne avant de déclarer le use case validé.

### 18 septembre 2026 Premiers cas d'usage UVP

- Cas documentés dans [docs/UVP_USE_CASES_SQL.md](docs/UVP_USE_CASES_SQL.md) :
  projets, zones maritimes, samples, objets, bins, abondances et CTD.
- Le modèle expose désormais la zone maritime, sa source, sa version et son
  statut d'affectation sur les profils/samples, ainsi que `cast_key` et le
  nombre de casts par projet.
- Les frictions sont explicitées : point-dans-polygone, dictionnaire CTD,
  agrégation multi-bins et mapping taxonomique. Le rattachement objet/bin est
  déterministe via `object_depth_min` et la grille de 5 m historique.

### 18 septembre 2026 Intégration du contrat CTD historique

- Le catalogue `warehouse.ctd_variable` reprend les codes Amundsen validés dans
  l'historique Git (`PRES`, `TE90`, `PSAL`, `SIGT`, `OXYM`, `pH`, `NTRA`, `FLOR`).
- La documentation décrit le rattachement par nom de fichier CTD, puis la
  confirmation station/temps/position, ainsi que la distinction entre point
  CTD enrichi et profil vertical complet.
- 14 tests de contrat réussissent et le DDL complet s'exécute dans PostgreSQL
  temporaire.

### 18 septembre 2026 Cas de découverte et diagnostic des lacunes

- `docs/UVP_USE_CASES_SQL.md` couvre désormais l'inventaire des sources, la
  complétude des métadonnées, la couverture CTD, l'audit des jointures
  EcoTaxa/EcoPart, les taxons observés, la couverture spatiale/verticale et la
  table globale destinée aux graphiques.
- Les vues existantes exposent les colonnes nécessaires à ces diagnostics,
  notamment `dataset_version_id`, `ecopart_project_id` et les zones dans
  `explore.uvp_objects`.
- 15 tests de contrat réussissent ; le DDL complet s'exécute dans PostgreSQL
  temporaire.

### 18 septembre 2026 Analyses UVP concrètes par zone

- Les use cases couvrent maintenant les agrégats zone, station, profil,
  sample, bin et objet, avec abondance moyenne par profondeur.
- Des requêtes combinent EcoTaxa, EcoPart et CTD au grain sample, et une vue
  séparée conserve les objets EcoTaxa au grain objet pour l'audit des images et
  des rattachements de bins.
- La moyenne d'abondance est calculée après agrégation objets/volume par profil
  afin de ne pas surpondérer les profils ayant davantage de bins.
- 16 tests de contrat réussissent ; le DDL complet s'exécute dans PostgreSQL
  temporaire.

### 18 septembre 2026 Registre des frictions ouvertes

- Les cas qui n'ont pas encore de solution validée sont suivis dans
  [docs/UVP_FRICTIONS_OPEN.md](docs/UVP_FRICTIONS_OPEN.md) : métadonnées
  manquantes, couverture CTD, unités, taxonomie, versions et grains de
  jointure.
- Chaque entrée précise son statut, la gestion prévue, la preuve attendue et
  les critères de clôture. L'agent doit exposer les statuts au lieu de choisir
  une valeur absente ou ambiguë.

### 18 septembre 2026 Plan de peuplement V1

- Le plan est documenté dans
  [docs/WAREHOUSE_POPULATION_PLAN.md](docs/WAREHOUSE_POPULATION_PLAN.md).
- L'ordre retenu est manifeste → EcoTaxa → EcoPart → CTD → liens → FILET →
  vues et contrôles finaux.
- Le script historique `core/ecotaxa_browser/cache/sync.py` est utilisé comme
  référence d'extraction, de signatures, de retries et de contrôles ; son cache
  SQLite ne remplace pas le warehouse PostgreSQL.

### 18 septembre 2026 Décision de stockage PostgreSQL/PostGIS

- La décision est documentée dans
  [docs/WAREHOUSE_STORAGE_DECISION.md](docs/WAREHOUSE_STORAGE_DECISION.md).
- PostgreSQL devient la source de vérité ; PostGIS calcule l'affectation des
  samples aux zones à l'ingestion. Les fichiers bruts et Parquet restent
  référencés par manifeste et empreinte.
- La prochaine étape est le plan opérationnel d'accès aux sources, de
  téléchargement vérifié, de staging et de chargement.

### 18 septembre 2026 Validation technique du warehouse V1 EcoTaxa/CTD

- PostgreSQL/PostGIS local est opérationnel dans Docker (`neolab-warehouse-db`)
  avec sauvegarde compressée versionnée hors Git.
- EcoTaxa contient 23 projets, 6 138 samples et 15 050 002 objets chargés.
- Amundsen contient 456 profils CTD et 5 130 421 mesures ; 904 samples
  EcoTaxa sont reliés, dont les codes courts 2023/2024 résolus par date et
  position. Les références sans correspondance restent conservées et
  qualifiées.
- Les vues `explore.*` de navigation UVP, EcoTaxa–CTD et FILET–UVP/CTD sont
  créées dans le DDL et présentes dans la base. Les vues UVP/EcoPart restent
  vides jusqu'au prochain chargement EcoPart.
- La couverture et les limites sont détaillées dans
  [docs/WAREHOUSE_ECOTAXA_QA.md](docs/WAREHOUSE_ECOTAXA_QA.md). La prochaine
  étape est l'accès, l'extraction et le chargement EcoPart.

### 21 septembre 2026 Chargement et validation EcoPart

- Les outils historiques EcoPart/EcoTaxa retrouvés dans Git ont été examinés : résolution serveur `filt_proj`, métadonnées du profil, jointure exacte au profil et grille de profondeur de 5 m. L'archive locale reste absente.
- Un chargeur idempotent a téléchargé et conservé les archives originales de 11 projets EcoPart accessibles, avec empreinte, tâche serveur et manifeste local ignoré par Git. Les données sont chargées au grain profil/bin ; les lignes ZOO et métadonnées source restent séparées des particules.
- Le warehouse contient 585 profils EcoPart, 59 801 bins et 10 479 780 objets EcoTaxa reliés à un bin. Les 228 objets sans bin restent explicitement non appariés ; la vue d'objets en expose donc 10 480 008. La couche d'abondance conserve les zéros des bins sans objet dans les dénominateurs.
- Validation réelle : 11 archives comparées aux bins PostgreSQL sans écart ; six audits de jointure, profondeur, cardinalité, formule et provenance CTD retournent 0 anomalie. Les tests ciblés, dont la base PostgreSQL temporaire, réussissent.
- Les sources, limites et commandes de reprise sont documentées dans `docs/WAREHOUSE_ECOPART.md` et `docs/WAREHOUSE_ECOTAXA_QA.md`.
- Après un incident d'espace disque et le redémarrage de Docker le 21 septembre, PostgreSQL accepte de nouveau les requêtes. La migration additive `sql/warehouse_ecopart_migration.sql` a recréé les vues `explore.*` absentes de l'instance restaurée ; une jointure de contrôle donne 36 profils EcoPart/36 samples EcoTaxa pour 417↔5149 et 86 profils/samples pour chacune des politiques 86↔149 et 86↔20880. Pour `de110_001`, `ecotaxa:name:like<Copepoda` donne 308 objets sur 6 121,17 L, soit 50,32 ind/m³ ; aucun lien objet–bin orphelin n'est trouvé.
- **Réparation Docker, 21 septembre :** après les erreurs d'E/S du disque virtuel Docker, le stockage a été recréé puis le dump `data/warehouse_backups/neolab_warehouse_ecopart_20260921.dump` restauré sans erreur. Le contrôle SQL post-restauration retrouve 585 profils EcoPart, 59 801 bins et 10 479 780 objets appariés. Les liens 417↔5149 et 86↔149/20880 donnent respectivement 36/36 et 86/86 profils/samples ; le cas `de110_001`–Copepoda donne 308 objets, 6 121,17 L et 50,32 ind/m³. Les contrôles d'intégrité retournent 0 lien objet–bin orphelin et 0 lien non accepté.
- **Simulation SQL de parcours, 21 septembre :** la requête « profils de la Baie de Baffin en 2024 » retourne 123 profils EcoPart, tous géolocalisés. Pour la carte, le taxon explicite `ecotaxa:name:Copepoda<Multicrustacea` retourne une série d'abondance pour chacun des 123 profils, sans double politique d'annotation ; l'abondance cartographiée est `SUM(objets) / SUM(volume_L) × 1000`, au grain profil. Les autres clés contenant « Copepoda » sont des catégories distinctes et ne sont pas fusionnées implicitement.
- **Validation au grain bin, 21 septembre :** ces 123 profils ont 13 800 bins, tous avec intervalle de profondeur et volume échantillonné valides, sans doublon de profondeur dans un profil. Pour `am_leg3_RA02_1`, la série Copépodes restitue notamment 132 objets sur 64 L entre 20 et 25 m (2 062,50 ind/m³) et des zéros explicites lorsque le bin n'a aucun objet du taxon.
- **Test de rendu Python, 21 septembre :** l'image LangGraph reconstruite contient `psycopg` et Matplotlib. Un script exécuté dans cette image a lu les 95 bins de `am_leg3_RA02_1` via PostgreSQL et produit un PNG Matplotlib. Aucun outil warehouse n'est encore enregistré dans `langgraph/` : cette preuve valide le runtime, pas encore le use case conversationnel d'accès libre aux données.

### 21 septembre 2026 Chargement FILET

- Les trois exports FILET validés du 26 mai 2026 ont été chargés par
  `scripts/populate_filet.py` avec leurs trois empreintes SHA-256 dans une
  version unique `filet/neolab-filet/2026-05-26`. Les fichiers bruts du Bureau
  restent inchangés.
- Le warehouse contient 6 102 échantillons, 1 502 analyses, 6 229 appartenances
  échantillon-filet et 90 780 lignes au grain ligne source × taxon × stade,
  issues de 5 047 lignes larges. Les valeurs explicites à zéro et l'absence de
  biomasse pour nauplii/totaux sont conservées ; aucun volume ni abondance n'a
  été recalculé.
- La jointure interne des métadonnées conserve 4 941 lignes source appariées
  et 106 non appariées (1 908 lignes de stades), comme dans la vérification
  initiale. Aucun orphelin de clé n'est trouvé. Les tables de liens FILET vers
  EcoTaxa, CTD ou UVP restent vides : les exports ne fournissent pas de preuve
  de ces relations.

### 21 septembre 2026 Navigateur de couverture V1

- Un navigateur local, indépendant de l'agent conversationnel, est disponible
  dans `warehouse_navigator/` et exposé par le service Docker
  `warehouse-navigator` sur `http://localhost:8090`. Il lit PostgreSQL en
  lecture seule et ne présente aucun objet individuel.
- Les filtres zone, année, projet EcoTaxa/EcoPart et recherche textuelle
  retournent les couvertures agrégées réelles : profils, bins, volume, objets
  EcoTaxa associés, séries taxonomiques, CTD, FILET et liens prouvés. FILET
  reste explicitement indépendant des filtres spatiaux/projets tant qu'un lien
  externe n'est pas démontré.
- Contrôle réel : « Baie de Baffin, 2024 » retourne 123 profils, 13 800 bins,
  4 279 581 objets associés, 117 séries taxonomiques, 94 profils CTD et 558
  échantillons FILET de 2024. Une recherche `21916` retourne l'échantillon
  FILET correspondant sans lui attribuer de lien UVP.

### 21 septembre 2026 Candidats FILET–UVP par station et temps

- `scripts/populate_filet_uvp_matches.py` crée des correspondances sans utiliser
  les identifiants de projets ou d'échantillons des deux méthodes. Il normalise
  uniquement le libellé de station puis applique une fenêtre temporelle passée
  explicitement par paramètre.
- Première exécution avec une fenêtre de 10 h : 130 liens uniques sont
  `accepted` et 288 lignes restent `ambiguous` lorsqu'un échantillon FILET a
  plusieurs profils UVP candidats. Les preuves stockent stations source et
  normalisée, dates, écart temporel, fenêtre et nombre de candidats. Aucun lien
  chargé ne dépasse 10 h.

**Limites :** EcoPart n'a retourné aucun lien pour dix projets EcoTaxa ; le projet 10101 n'est pas classé car son endpoint a expiré. Aucun use case conversationnel IDEA ni validation scientifique d'équipe n'est déclaré achevé. La prochaine étape reste l'ingestion FILET, puis les jointures FILET–UVP/CTD sur correspondances vérifiées.

**Limites restantes :** aucun schéma warehouse V1 ni jeu de campagnes n’est
encore validé avec l’équipe. Aucun use case scientifique NeoLab n’est encore
déclaré validé sur ce socle. Cette politique globale empêche aussi l’indexation
de nouveaux fichiers dans Open WebUI Knowledge ; le flux PaperQA devra être
validé séparément avant sa réactivation.

### 25 septembre 2026 Recette du navigateur de couverture

- Recette locale du service `warehouse-navigator` : `/health`, options et couvertures agrégées répondent sans erreur. Les contrôles Python ciblés ont réussi (22 tests).
- Les compteurs de la carte suivent les filtres réellement appliqués : toutes données (585 profils UVP, 6 102 échantillons FILET), puis Baie de Baffin (199, 1 467). En mode FILET–UVP, le seuil de 10 h retourne 6 profils UVP et 30 échantillons FILET dans cette zone ; 4 h les réduit à 2 et 4.
- L’interface a été vérifiée avec les couches, la zone, le projet EcoTaxa et le mode de comparaison. Le seuil horaire est masqué hors de ce mode ; le filtre EcoPart est retiré. Les points FILET indiquent désormais qu’ils regroupent des échantillons au même emplacement et présentent une plage temporelle lorsque nécessaire.
- Aucun avertissement ou erreur JavaScript n’a été relevé durant la recette. La carte a été restaurée à son état initial après test.

### 25 septembre 2026 Métadonnées des fiches cartographiques

- Les infobulles de comparaison FILET–UVP affichent désormais le titre du projet UVP/EcoTaxa associé au profil, provenant de `warehouse.ecotaxa_project`.
- Les fiches FILET et les comparaisons présentent les métadonnées d’équipement disponibles au grain échantillon : support, engin, type de trait, maille déclarée et nombre de filets. Elles sont agrégées explicitement lorsqu’un point représente plusieurs échantillons.
- Contrôle réel : la correspondance FILET `39908` ↔ UVP `am_leg2_killinik2` restitue le projet `uvp6_sn000006hf_2024_am_leg2`; les métadonnées FILET retournent notamment `CCGS Amundsen`, `2x1m2`, `O-Tow`, une maille de 50 et un filet.

### 25 septembre 2026 Hiérarchie des fiches de carte

- Les infobulles UVP, FILET et FILET–UVP utilisent désormais la même hiérarchie : titre, résumé, sections, libellés en gras et valeurs en texte normal. La légende suit également ce système typographique.
- Les profondeurs FILET min–max sont affichées dans les fiches, au grain de l’échantillon ou de l’agrégat cartographique. Exemple de recette visuelle : un groupe FILET affiche `0 à 511`; une comparaison affiche `0 à 100`.
- Une régression du mode comparaison a été trouvée puis corrigée : 132 candidats FILET–UVP ne possédaient pas de coordonnées UVP et provoquaient une erreur Leaflet. La vue cartographique exclut désormais ces seules paires non cartographiables ; les 286 paires localisables sont affichables, dont 130 acceptées et 156 ambiguës.

### 25 septembre 2026 Correctif d’affichage des heures FILET–UVP

- La fiche de comparaison affichait les horodatages FILET sans fuseau comme heure locale puis les étiquetait « UTC », créant une incohérence visible avec l’écart calculé. La paire FILET `41471` / UVP `am_leg5_TCA_T3_19_02` est stockée à 07:06:56 contre 04:00 UTC, soit 3 h 07.
- Le formateur de la carte interprète désormais les horodatages FILET sans suffixe comme UTC, conformément au calcul de `filet_uvp_match`. La fiche affiche donc 07 h 06 UTC, ce qui concorde avec l’écart de 3 h 07.

### 25 septembre 2026 Filtres cumulables du navigateur

- Le navigateur accepte une plage d’années « De / À » et plusieurs zones ou projets EcoTaxa par cases à cocher. Les mêmes paramètres sont appliqués aux compteurs, points UVP/FILET, contours de zones et correspondances FILET–UVP.
- Les sélections sont cumulatives ; chaque liste possède son action d’effacement. Une plage inversée est normalisée côté API.
- Recette réelle : deux zones et deux projets sélectionnés en 2024 retournent 39 profils UVP et 7 échantillons FILET ; après effacement, la couverture revient à 585 profils et 6 102 échantillons. La page locale est servie avec `Cache-Control: no-store` pour éviter l’interface périmée après redémarrage.

### 25 septembre 2026 Inclusion des chevauchements FILET dans les filtres de zone

- Les 863 échantillons FILET dont les coordonnées croisent plusieurs polygones restent qualifiés `ambiguous` dans leur provenance ; cette qualification ne les exclut plus d’un filtre spatial.
- Pour chaque zone sélectionnée, le navigateur teste les coordonnées de ces chevauchements contre le registre GeoJSON canonique local et inclut les points qui se trouvent réellement dans le polygone demandé. Aucune zone unique n’est donc assignée arbitrairement.
- Recette réelle : le filtre « Baie d’Hudson », auparavant à 0 à cause de cette politique de provenance, restitue désormais 235 échantillons FILET. Les 20 filtres de zone ont été contrôlés : pour chacun, le total des échantillons agrégés sur la carte égale le compteur de couverture retourné par l’API. Les 22 tests ciblés ont réussi.
