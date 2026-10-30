# Warehouse NeoLab — fiche de spécifications

Laboratoire NeoLab, Département de biologie, Université Laval

## Base de données

| Spécification | Valeur |
|---|---|
| Moteur | PostgreSQL 16 |
| Extension requise | PostGIS 3.4+ |
| Stockage | 50 Go |
| Système d'exploitation | Linux |

## Compte requis

| Élément | Détail |
|---|---|
| Type de compte | Propriétaire de la base |
| Droits | `LOGIN`, `CREATEROLE` |
| Extension PostGIS | Activée par un administrateur si le compte n'est pas superuser |

## Réseau

| Élément | Détail |
|---|---|
| Accès | Réseau de l'Université Laval ou VPN |
| Exposition publique | Non requise |
| Chiffrement | TLS si accès distant |

## Sauvegarde

| Élément | Détail |
|---|---|
| Méthode | `pg_dump` (format custom) |
| Fréquence | Quotidienne |
| Responsable | À déterminer avec Valeria |
