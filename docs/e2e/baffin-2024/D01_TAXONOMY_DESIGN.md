# D01 — Résolution hiérarchique stricte de Copepoda

Date : 2026-07-14

## Objectif

Fournir une sélection déterministe des objets appartenant à Copepoda dans une
table EcoTaxa chargée, sans liste manuelle de descendants et sans résolution
réseau implicite.

## Contrat

Une fonction métier pure construit un masque booléen à partir de
`object_annotation_hierarchy`.

- Une ligne est retenue lorsque sa hiérarchie contient le nœud taxonomique exact
  `Copepoda`, sans sensibilité à la casse ni aux espaces périphériques.
- Les descendants comme `Calanoida` sont retenus parce que leur hiérarchie
  contient `Copepoda`, même si leur catégorie terminale ne contient pas le mot
  `copepod`.
- Un taxon hors Copepoda n'est pas retenu.
- Une valeur de hiérarchie absente ou vide n'est pas retenue.
- Si la colonne `object_annotation_hierarchy` est absente de la table, le calcul
  est refusé avec un message indiquant que la hiérarchie taxonomique est requise.
- Aucun fallback par mots-clés, liste de noms, EcoTaxa ou WoRMS n'est autorisé.

## Formats de hiérarchie

Le résolveur accepte les séparateurs textuels usuels observés dans les exports
EcoTaxa (`>`, `|`, `;`, `/`) et compare des nœuds complets. Une sous-chaîne telle
que `NotCopepoda` ne doit pas correspondre.

## Intégration agent

Le helper est importable depuis le code exécuté par l'analyse de données. La
procédure UVP doit demander son utilisation pour toute sélection de Copepoda et
interdire les listes manuelles de catégories. Si la hiérarchie manque, la réponse
finale doit expliquer la limite et proposer un nouvel export contenant cette
colonne.

## Erreurs

L'absence de colonne lève une erreur métier explicite mentionnant
`object_annotation_hierarchy`. Les valeurs manquantes ligne par ligne produisent
simplement `False` dans le masque.

## Validation

### Tests automatisés

1. `Calanoida` avec une hiérarchie contenant Copepoda est inclus.
2. Une catégorie `Copepoda<Multicrustacea` avec hiérarchie Copepoda est incluse.
3. Un taxon hors Copepoda est exclu.
4. `NotCopepoda` est exclu.
5. Une valeur de hiérarchie vide est exclue.
6. Une table sans la colonne requise est refusée.

### Validation E2E par curl

Sur le même type de table EcoTaxa–EcoPart–Amundsen que le scénario Baffin :

- demander un audit du filtre Copepoda fondé exclusivement sur la hiérarchie ;
- vérifier que RA18/Calanoida est compté ;
- vérifier que la réponse ne contient aucune liste manuelle de descendants ;
- demander un essai sur une table sans hiérarchie et vérifier le refus explicite.

## Hors périmètre

- Construction de la table sample–profondeur (D02).
- Calcul des abondances et gestion des bins nuls (D03–D05).
- Résolution réseau d'un nom taxonomique.
- Modification de la taxonomie source EcoTaxa.
