---
name: neolab-warehouse
description: Entretien du warehouse NeoLab installé sur ce PC (conteneur Docker neolab-warehouse) — mettre à jour le code, vérifier le serveur MCP, recalculer les liens CTD, publier l'image pour les collègues, diagnostiquer un échec. À utiliser quand on parle de mise à jour, publication, image, registre ghcr.io, conteneur neolab ou serveur MCP qui ne répond pas.
---

# Entretien du warehouse NeoLab (PC Windows du responsable)

Répondre en français, court. Exécuter les commandes soi-même et rapporter le résultat réel (succès ou dernières
lignes d'erreur). Ne jamais annoncer un succès sans l'avoir vu dans la sortie.

## Interdits (demander d'abord, ou ne jamais faire)

- Jamais afficher, copier ni lire à voix haute un jeton ou un secret : `secrets.env`, `credentials.env`,
  `AppData/Local/neolab/github_token`, mots de passe. Ne jamais demander de jeton dans la conversation : si
  GitHub ou ghcr.io refuse l'accès, dire à l'utilisateur de lancer lui-même la commande interactive
  (`update_warehouse_windows.bat` ou `docker login ghcr.io`).
- Jamais `docker volume rm`, `docker rm -f neolab-warehouse`, `-Replace`, `-NewData`, `docker system prune` :
  la base de 8,6 Go est dans le volume. Demander d'abord, en disant ce qui serait perdu.
- Jamais écrire dans la base à la main (INSERT, UPDATE, DELETE, ALTER, migration bricolée) ni modifier les
  fichiers de `/opt/neolab/IDEA` dans le conteneur : seul le code du dépôt, appliqué par la mise à jour, change la
  base. Une migration en échec se signale au développeur avec le message exact; ne pas la « réparer ».
- Jamais `-Branch` autre que `mcp-neolab` (une ancienne branche a déjà effacé des liens CTD).
- Ne rien pousser sur GitHub (code ou données). Les données du labo restent sur ce PC et dans le registre privé.
- Images toujours privées : ne jamais rendre le paquet `neolab-warehouse` public.

## Shell (Claude Code sous Windows = Git Bash)

- Préfixer chaque commande `docker` par `MSYS_NO_PATHCONV=1`, sinon Git Bash change `/opt/...` en chemin
  Windows (`MSYS_NO_PATHCONV=1 docker exec neolab-warehouse neolab-check`).
- Donner aux scripts `.ps1` un chemin Windows complet : `powershell -NoProfile -ExecutionPolicy Bypass -File
  "C:\Users\<nom>\Documents\neolab\update_warehouse_windows.ps1"`. Lancer les `.ps1`, pas les `.bat` (ils
  attendent une touche).

## Trouver les scripts

Chercher `update_warehouse_windows.ps1` dans `~/Documents/neolab`, puis `~`. Prendre le plus récent s'il y en a
plusieurs. S'il manque, le sortir du conteneur (copie de la dernière mise à jour réussie) :

```
MSYS_NO_PATHCONV=1 docker cp neolab-warehouse:/opt/neolab/IDEA/scripts/update_warehouse_windows.ps1 ~/Documents/neolab/
```

## État rapide

```
MSYS_NO_PATHCONV=1 docker ps -a --filter name=neolab-warehouse --format "{{.Status}} {{.Image}}"
MSYS_NO_PATHCONV=1 docker exec neolab-warehouse neolab-status
MSYS_NO_PATHCONV=1 docker exec neolab-warehouse neolab-check
```

`neolab-status` (sans secret) donne la version du code, l'état de la base et du FILET, les liens CTD par méthode.
S'il n'existe pas encore, faire d'abord la mise à jour. `neolab-check` doit afficher PASS. Attendu : des liens
`proximity` côté UVP et côté FILET; zéro d'un côté = liens perdus, voir « Recalculer les liens CTD ».

## Mettre à jour

```
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\<nom>\Documents\neolab\update_warehouse_windows.ps1"
```

- Succès : « À JOUR (xxxxxxx) » ou « Déjà à jour ». Le script remplace aussi ses copies dans son dossier et ce
  skill. Dire à l'utilisateur de rouvrir une conversation dans ses assistants.
- Échec : lire les 40 dernières lignes de `~/AppData/Local/neolab/mise_a_jour.log`, les montrer, et expliquer :
  Docker arrêté (lancer Docker Desktop, relancer), jeton refusé (l'utilisateur relance le `.bat` lui-même),
  « pas plus récente » (refus de revenir en arrière : normal, rien n'a changé), erreur SQL ou « pas prêt »
  (à transmettre au développeur telle quelle; ne rien bricoler).

## Recalculer les liens CTD

La mise à jour le fait seule quand le chargeur change ou que des liens manquent. À la main (quelques minutes si
les profils CTD sont déjà là, Internet nécessaire) :

```
MSYS_NO_PATHCONV=1 docker exec neolab-warehouse neolab-load-ctd
```

Succès : « [neolab] CTD RELIÉES ». Revérifier ensuite `neolab-status` et `neolab-check`.

## Publier l'image pour les collègues

Prérequis, dans l'ordre : mise à jour réussie, `neolab-check` PASS, liens CTD présents des deux côtés, environ
25 Go libres, `docker login ghcr.io` déjà fait par l'utilisateur. Puis, en tâche de fond (une à plusieurs heures :
copie de la base puis envoi de plusieurs Go) :

```
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\<nom>\Documents\neolab\publish_prebuilt_image.ps1" -Owner TidianeCisse777
```

- La base est arrêtée quelques minutes pendant la copie puis redémarre seule.
- Refus « vient déjà d'une image publiée » : le conteneur doit venir de l'installation par zips; ne pas forcer.
- `denied` ou `unauthorized` au push : l'utilisateur refait `docker login ghcr.io` (jeton classique,
  `write:packages`), puis relancer une fois.
- À la fin, rapporter l'étiquette publiée (`ghcr.io/tidianecisse777/neolab-warehouse:<date>-donnees` et
  `:donnees`) et rappeler les deux étapes manuelles : donner l'accès en lecture à chaque collègue
  (github.com > profil > Packages > neolab-warehouse > Package settings > Manage access), puis leur envoyer
  `install_from_registry_windows.bat` et `install_from_registry_windows.ps1` (Mac et Linux :
  `install_from_registry.sh`), à sortir du conteneur :

```
for f in install_from_registry_windows.bat install_from_registry_windows.ps1 install_from_registry.sh; do
  MSYS_NO_PATHCONV=1 docker cp neolab-warehouse:/opt/neolab/IDEA/scripts/$f ~/Desktop/
done
```

Chaque collègue a besoin de Docker Desktop, d'un compte GitHub avec l'accès au paquet et d'un jeton classique
`read:packages` (qu'il colle lui-même quand l'installeur le demande).
