# Skill: ecotaxa_query

Tu viens d'appeler `query_ecotaxa` et les données EcoTaxa sont maintenant chargées dans la session.
Ce skill te donne les règles pour interpréter le résultat et guider l'utilisateur.

---

## Découvrir les projets accessibles

La liste des projets dépend du compte EcoTaxa configuré et peut changer.
Appelle `list_ecotaxa_projects` pour obtenir en temps réel les `project_id`
et noms accessibles, puis utilise l'identifiant choisi avec `query_ecotaxa`.
Ne présente jamais une liste de projets codée en dur.

---

## Choisir le bon tool

- Pour présenter un projet, afficher ses métadonnées, ses comptages ou quelques
  objets : appelle `preview_ecotaxa_project`.
- Pour charger, exporter, télécharger ou analyser les données complètes :
  appelle `query_ecotaxa`.
- Ne lance pas `query_ecotaxa` pour une simple demande d'aperçu : cet export
  peut être long et modifie la session d'analyse.

---

## Paramètres clés de `query_ecotaxa`

| Paramètre | Valeur par défaut | Notes |
|---|---|---|
| `project_id` | — | Obligatoire |
| `taxon` | `None` (tous les taxons) | Ex: `"Copepoda"`, `"Calanus"` — filtre côté EcoTaxa |
| `status` | `"V"` | `"V"` = validé uniquement, `"P"` = prédit, `""` = tous |

**Recommandation :** toujours utiliser `status="V"` pour des analyses quantitatives — les objets prédits non validés peuvent contenir des erreurs de classification.

---

## Après le chargement

1. **Vérifier les colonnes** avec `run_pandas` :
   ```python
   result = df.columns.tolist()
   ```

2. **Identifier le schéma** — colonnes `fre_*` (UVP6/LOKI) ou `object_*` (UVP5) :
   ```python
   result = [c for c in df.columns if c.startswith("fre_") or c.startswith("object_")]
   ```

3. **Si colonnes UVP détectées** → charge le skill `uvp_ecotaxa` pour les méthodes de calcul m5/m6.

---

## Lien de téléchargement

Le résumé retourné par `query_ecotaxa` contient un lien `http://localhost:8000/downloads/<id>.tsv`.
**Inclure ce lien dans ta réponse à l'utilisateur** — il peut cliquer pour télécharger le fichier complet.

---

## Combiner EcoTaxa avec EcoPart

EcoPart fournit les **profils CTD + particules UVP** pour les mêmes casts Amundsen.
Pour coupler les données :

1. Charger EcoTaxa : `query_ecotaxa(project_id=1165)`
2. Charger EcoPart : `query_ecopart(project_id=105)`
3. Joindre : `join_ecotaxa_ecopart`

**Clé de jointure :**
`obj_orig_id` dans EcoTaxa (ex. `ips_007_899`) → supprime le suffixe `_NNN` → `profile_id` (`ips_007`) → correspond à l'identifiant sample EcoPart.

```python
# Dériver profile_id depuis obj_orig_id
df["profile_id"] = df["obj_orig_id"].str.replace(r"_\d+$", "", regex=True)
```

Le résultat de la jointure contient à la fois la taxonomie/morphométrie EcoTaxa
et les colonnes CTD (`Depth [m]`, `Sampled volume [L]`, colonnes `LPM`) d'EcoPart.
Voir le skill `uvp_ecopart` pour les métriques m1-m3 calculables depuis EcoPart.

---

## Cas limites

- Si le projet contient >100 000 objets, l'export peut prendre 1-2 minutes — prévenir l'utilisateur.
- Si `taxon` est spécifié mais retourne 0 lignes : vérifier l'orthographe exacte du nom taxonomique (sensible à la casse dans EcoTaxa).
- Sans credentials valides (`ECOTAXA_TOKEN` ou `ECOTAXA_USERNAME`/`ECOTAXA_PASSWORD`), le tool retourne une erreur — demander à l'utilisateur de vérifier son `.env`.
