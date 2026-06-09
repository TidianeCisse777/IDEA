# Skill: amundsen_ctd_query

Tu viens d'appeler `query_amundsen_ctd`.
Le profil Amundsen CTD vertical est maintenant chargé ou exporté dans la session.

---

## Règle de routage

- Pour voir les datasets disponibles, appelle `list_amundsen_datasets`.
- Pour un aperçu rapide d'un profil, appelle `preview_amundsen_profile`.
- Pour charger, exporter, télécharger ou analyser le profil vertical complet, appelle `query_amundsen_ctd`.

---

## Ce que contient Amundsen CTD

- `amundsen12713` est le dataset vertical CTD principal.
- Les colonnes brutes doivent rester intactes.
- Les alias de jointure ajoutés en sortie servent à préparer les jointures avec le zooplancton.

---

## Après le chargement

1. Inclure le lien de téléchargement fourni par le tool.
2. Utiliser les colonnes de profondeur, de station, de cast et de temps pour les jointures.
3. Ne pas interpréter biologiquement les profils — fournir les données et les comparaisons seulement.

---

## Limites

- Le profil doit rester brut et traçable.
- Les alias sont des aides, pas une substitution aux colonnes d'origine.
