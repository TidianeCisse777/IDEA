# Retry ciblé des rendus graphiques bloqués

## Objectif

Un graphique dont le code est exécutable mais dont le contrat de rendu est
incomplet ou incohérent ne doit pas bloquer immédiatement l’exploration. Le
modèle doit pouvoir corriger le code et relancer le rendu en conservant le
DataFrame actif et l’intention de l’utilisateur.

## Comportement retenu

Lorsqu’un appel `run_graph` retourne un statut `blocked` pour une validation de
contrat graphique ou de qualité de rendu :

1. le résultat bloqué reste visible dans l’historique et la trace;
2. l’agent effectue au maximum une relance ciblée;
3. la relance réutilise le même dataset actif et ne recharge aucune source;
4. le prompt de correction contient le diagnostic exact retourné par le
   validateur;
5. si la relance échoue, l’agent expose le blocage final avec sa cause, sans
   boucle ni tableau de substitution lorsque l’intention était visuelle.

Les erreurs de données, de source, d’autorisation ou de colonnes ne sont pas
converties en retry graphique automatique.

## Contrat graphique

Le code généré doit continuer à déclarer `graph_contract`. Le retry ne
supprime pas la validation : il donne une occasion de corriger les erreurs
mécaniques, notamment un `graph_contract` absent ou un `axis_index` qui ne
correspond pas à l’axe réel d’une figure composite.

## Tests

- test un blocage de contrat suivi d’un succès au second appel;
- test qu’un second blocage s’arrête sans troisième tentative;
- test que le même dataset actif est conservé pendant le retry;
- test qu’un blocage non graphique n’est pas relancé par ce mécanisme.
