# NeoLab MCP — consignes aux agents de développement

Répondre en français par défaut, court et simple. Ce dépôt contient uniquement le warehouse NeoLab et son
serveur MCP (voir [README.md](README.md)). Lire le README, puis les dernières entrées de
[ROADMAP.md](ROADMAP.md) avant de travailler; y consigner chaque travail réellement exécuté, avec preuves et
limites.

## Données : ne jamais manipuler de données fausses

- Ne rien inventer : valeurs, identifiants, colonnes, unités, liens, provenance. Chaque constat s'appuie sur une
  requête ou un fichier source cité.
- Préserver les données brutes; rendre explicites le grain, les clés et les transformations.
- Inconnu ≠ zéro : une valeur absente reste NULL, jamais 0 dans un calcul ou un filtre.
- Pas de double compte : stades agrégés FILET jamais additionnés à leurs parties; une seule copie EcoTaxa par
  profil UVP; volumes UVP comptés une fois par tranche, tranches vides comprises.
- Garder séparés validé et prédit, volume profondeur et débitmètre FILET; exclure les objets non vivants des
  abondances d'organismes.
- Une vue vide ou un lien manquant est un constat à expliquer (ordre de chargement, chargeur absent), pas une
  absence de données.
- Demander une clarification si un choix change le sens scientifique; aucune interprétation biologique.

## Code

- Opérations scientifiques critiques (jointures, unités, concentrations) dans du code vérifiable, avec test.
- Migrations SQL additives et relançables dans `sql/`, ajoutées à `ALWAYS_FILES` de
  `scripts/deploy_warehouse_postgres.py` et à `docker-compose.warehouse.yml`.
- Toute nouvelle vue `explore.*` a sa fiche dans `scripts/warehouse_context.py` (le déploiement l'exige).
- Avant de pousser : `python -m pytest -q tests/`, puis un déploiement rejoué qui affiche « PRÊT » et une
  vérification avec le compte de lecture (30 s par requête).

## Sécurité

Ne jamais afficher ni commiter de secret. Les données du labo ne quittent pas le dépôt privé et les machines
autorisées. Ne pas pousser sans demande.
