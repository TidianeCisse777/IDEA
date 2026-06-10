# Skill: ecopart_query

Tu viens d'appeler `query_ecopart` et les données EcoPart sont maintenant chargées dans la session.
Ce skill te donne les règles pour interpréter le résultat et guider l'utilisateur.

---

## Choisir le bon tool

- Pour lister les échantillons disponibles dans un projet : appelle `list_ecopart_samples`.
- Pour afficher le contenu d'un échantillon sans tout charger : appelle `preview_ecopart_sample`.
- Pour charger, exporter ou analyser les données complètes d'un projet : appelle `query_ecopart`.
- Ne lance pas `query_ecopart` pour une simple demande d'aperçu.

---

## Paramètres clés de `query_ecopart`

| Paramètre | Valeur par défaut | Notes |
|---|---|---|
| `project_id` | `105` | EcoPart Amundsen 2018 |
| `ctd_vars` | `["depth", "datetime", "temperature", "practical_salinity"]` | Variables CTD à exporter |
| `gpr_vars` | `["cl6", "cl7", "cl8", "bv6", "bv7", "bv8"]` | Classes de taille UVP (LPM) |

Les valeurs par défaut couvrent l'usage standard Amundsen — ne les modifier que si l'utilisateur demande des variables spécifiques.

---

## Colonnes attendues dans le TSV EcoPart

| Colonne | Contenu |
|---|---|
| `Profile` | Identifiant du profil (ex. `ips_007`) — clé de jointure avec EcoTaxa |
| `Depth [m]` | Profondeur en mètres |
| `Sampled volume [L]` | Volume échantillonné par la caméra UVP |
| `temperature` | Température CTD (°C) |
| `practical_salinity` | Salinité pratique (PSU) |
| `cl6`…`cl8` | Concentrations par classe de taille (LPM, nb/L) |
| `bv6`…`bv8` | Biovolume par classe de taille (mm³/L) |

---

## Après le chargement

1. **Vérifier les colonnes** :
   ```python
   result = df.columns.tolist()
   ```

2. **Inspecter les profils disponibles** :
   ```python
   result = df["Profile"].unique().tolist()
   ```

3. **Si métriques LPM demandées** → charge le skill `uvp_ecopart` pour les méthodes de calcul m1-m3.

---

## Lien de téléchargement

Le résumé retourné par `query_ecopart` contient un lien `http://localhost:8000/downloads/<id>.tsv`.
**Inclure ce lien dans ta réponse à l'utilisateur** — il peut cliquer pour télécharger le fichier complet.

---

## Combiner EcoPart avec EcoTaxa

EcoPart fournit les **profils CTD + particules UVP** ; EcoTaxa fournit la **taxonomie annotée**.
Pour coupler :

1. Charger EcoTaxa : `query_ecotaxa(project_id=1165)`
2. Charger EcoPart : `query_ecopart(project_id=105)`
3. Joindre : `join_ecotaxa_ecopart`

**Clé de jointure :**
`obj_orig_id` dans EcoTaxa (ex. `ips_007_899`) → supprime le suffixe `_NNN` → `profile_id` (`ips_007`) → correspond à la colonne `Profile` d'EcoPart.

```python
df_ecotaxa["profile_id"] = df_ecotaxa["obj_orig_id"].str.replace(r"_\d+$", "", regex=True)
df_joined = df_ecotaxa.merge(df_ecopart, left_on="profile_id", right_on="Profile", how="left")
```

---

## Cas limites

- EcoPart n'a pas de REST API — le client utilise une session cookie. Si l'export échoue avec une erreur HTTP, vérifier que `ECOTAXA_USERNAME`/`ECOTAXA_PASSWORD` sont bien dans le `.env`.
- Si `start_export` retourne une liste de liens vide, le projet n'est pas accessible avec le compte configuré.
- L'export peut prendre 30-60 secondes pour un grand projet — prévenir l'utilisateur.
