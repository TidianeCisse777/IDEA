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

## Gestion des rôles et des accès

### 1. Création des rôles

Un rôle PostgreSQL est créé **individuellement**, à la demande, pour chaque personne du laboratoire qui doit accéder aux données. Il n'y a pas de rôle générique ou partagé entre plusieurs personnes.

Chaque rôle est créé avec :

- un nom qui identifie la personne (ex. `jdupont`, `tcisse`) ;
- un mot de passe généré automatiquement, transmis une seule fois à la personne concernée ;
- des droits de **lecture seule** uniquement — aucun rôle d'accès aux données ne peut écrire, modifier ou supprimer.

### 2. Rôles attachés à des agents, mais rattachés à de vraies personnes

Certains rôles seront utilisés par des agents IA (assistants comme Claude ou Codex, via une connexion appelée DbHub) pour interroger la base au nom d'un chercheur.

Le principe est le suivant :

- **Chaque agent utilise le rôle d'une personne réelle et identifiée.** Il n'existe aucun rôle anonyme ou partagé utilisé par les agents.
- **L'agent n'a aucun droit propre** : il hérite exactement des droits du rôle auquel il est connecté, ni plus ni moins.
- **Toute action de l'agent est donc traçable jusqu'à une personne précise**, comme si cette personne interrogeait elle-même la base.

### 3. Chaque rôle est limité à son périmètre de données (lecture seule)

Un rôle (humain ou utilisé par un agent) ne voit que les données explicitement autorisées pour lui. Ce périmètre est défini par un administrateur selon :

| Dimension | Exemple |
|---|---|
| Source de données | EcoTaxa, EcoPart, CTD, filets |
| Projet / contrat de recherche | selon l'entente ou le financement |
| Zone géographique | ex. une zone d'étude précise |
| Période (années) | ex. 2022–2024 seulement |

**Un rôle sans autorisation explicite ne voit aucune donnée** — il n'y a pas d'accès par défaut.

### 4. Résumé du principe

```
Base de données (PostgreSQL)
│
├── Rôle administrateur (propriétaire)
│     → seul rôle avec droit d'écriture
│
└── Rôles individuels (un par personne)
      → lecture seule
      → périmètre de données restreint et explicite
      → utilisés directement par la personne,
        ou par un agent IA connecté en son nom
```
