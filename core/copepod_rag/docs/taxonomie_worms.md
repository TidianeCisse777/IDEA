# taxonomie_worms.md
# Classification taxonomique des copépodes et API WoRMS
# Périmètre : espèces du labo Maps, Arctique / Atlantique Nord / Saint-Laurent
# Format RAG — chaque section délimitée par --- est un chunk autonome

---

# Quelle est l'arborescence complète de la classe Copepoda dans WoRMS ?

```
Biota
└── Animalia (Règne)
    └── Arthropoda (Embranchement)
        └── Crustacea (Sous-embranchement)
            └── Multicrustacea (Superclasse)
                └── Copepoda (Classe — AphiaID : 1080)
                    ├── Calanoida (Ordre — AphiaID : 1081)  ← copépodes du labo Maps
                    │   ├── Calanidae (Famille — AphiaID : 106358)
                    │   │   └── Calanus (Genre — AphiaID : 104421)
                    │   │       ├── Calanus finmarchicus   (104464)
                    │   │       ├── Calanus glacialis      (104465)
                    │   │       ├── Calanus helgolandicus  (104466)
                    │   │       └── Calanus hyperboreus    (104467)
                    │   ├── Metridinidae (Famille)
                    │   │   └── Metridia (Genre — AphiaID : 104517)
                    │   │       └── Metridia longa         (104520)
                    │   ├── Pseudocalanidae (Famille)
                    │   │   └── Pseudocalanus (Genre)
                    │   │       └── Pseudocalanus minutus  (104522)
                    │   └── Temoridae (Famille)
                    │       └── Temora (Genre)
                    │           └── Temora longicornis
                    ├── Cyclopoida (Ordre — AphiaID : 1089)  ← Oithona
                    │   └── Oithonidae (Famille)
                    │       └── Oithona (Genre — AphiaID : 106484)
                    │           └── Oithona similis        (106485)
                    └── Harpacticoida (Ordre)  ← hors périmètre labo Maps
```

**Points clés de l'arborescence :**
- Tous les *Calanus* (spp.) appartiennent à l'ordre **Calanoida**, famille **Calanidae**.
- *Oithona similis* est dans un ordre différent (**Cyclopoida**) — distinction importante pour les analyses par groupe fonctionnel.
- Les Harpacticoida sont des copépodes benthiques — absents des données UVP5/LOKI du labo Maps.
- La distinction Calanoida / Cyclopoida est visible dans EcoTaxa via `object_annotation_category`.

---

# Qu'est-ce que WoRMS et pourquoi est-il la référence pour les copépodes marins ?

WoRMS (World Register of Marine Species) est le registre de référence mondial pour la nomenclature des espèces marines. Chaque taxon y est identifié par un **AphiaID** unique et stable.

**Pourquoi utiliser WoRMS plutôt qu'une autre source ?**
- Référence officielle acceptée par EcoTaxa, EcoPart, OBIS et la majorité des bases de données océanographiques.
- EcoTaxa utilise directement les AphiaID WoRMS pour ses annotations taxonomiques.
- Les exports EcoTaxa incluent souvent `object_annotation_category` qui correspond à un nom WoRMS.

**URL de base :** https://www.marinespecies.org
**API REST :** https://www.marinespecies.org/rest/

---

# Quelle est la hiérarchie taxonomique des copépodes dans WoRMS ?

Les copépodes sont un groupe de crustacés de la classe Copepoda. Voici la hiérarchie complète :

```
Règne      : Animalia
  Embranchement : Arthropoda
    Sous-embranchement : Crustacea
      Classe : Copepoda (AphiaID : 1080)
        Ordre : Calanoida  (AphiaID : 1080 → sous-taxon)
          Famille : Calanidae
            Genre : Calanus
              Espèce : Calanus hyperboreus   (AphiaID : 104464)
              Espèce : Calanus glacialis     (AphiaID : 104466)
              Espèce : Calanus finmarchicus  (AphiaID : 104464*)
              Espèce : Calanus helgolandicus (AphiaID : 104467)
          Famille : Metridinidae
            Genre : Metridia
              Espèce : Metridia longa        (AphiaID : 104520)
          Famille : Pseudocalanidae
            Genre : Pseudocalanus
              Espèce : Pseudocalanus minutus  (AphiaID : 104522)
          Famille : Temoridae
            Genre : Temora
              Espèce : Temora longicornis
        Ordre : Cyclopoida
          Famille : Oithonidae
            Genre : Oithona
              Espèce : Oithona similis       (AphiaID : 106485)
```

**Note :** Les Calanoida regroupent la majorité des copépodes d'intérêt au labo Maps. Les Cyclopoida (Oithona) appartiennent à un ordre différent.

---

# Comment accéder à la hiérarchie d'un taxon via l'API WoRMS ?

L'API WoRMS est publique, sans authentification. Elle retourne du JSON ou XML.

## Obtenir la classification complète d'une espèce

```
GET https://www.marinespecies.org/rest/AphiaClassificationByAphiaID/{AphiaID}
```

Exemple — hiérarchie de Calanus hyperboreus (AphiaID : 104464) :
```
https://www.marinespecies.org/rest/AphiaClassificationByAphiaID/104464
```

Retourne la chaîne complète du règne jusqu'à l'espèce.

## Obtenir le détail d'un taxon par AphiaID

```
GET https://www.marinespecies.org/rest/AphiaRecordByAphiaID/{AphiaID}
```

Retourne : nom accepté, rang, statut, parent AphiaID, synonymes.

## Trouver l'AphiaID d'une espèce par son nom

```
GET https://www.marinespecies.org/rest/AphiaIDByName/{name}?marine_only=true
```

Exemple :
```
https://www.marinespecies.org/rest/AphiaIDByName/Calanus%20hyperboreus?marine_only=true
```

---

# Comment lister tous les enfants (sous-taxons) d'un groupe dans WoRMS ?

Pour explorer la hiérarchie vers le bas (eg. toutes les espèces du genre Calanus) :

```
GET https://www.marinespecies.org/rest/AphiaChildrenByAphiaID/{AphiaID}
```

Paramètres utiles :
- `marine_only=true` — filtre les taxons marins uniquement
- `offset=0` — pour paginer (100 résultats par appel maximum)

**Exemple — toutes les espèces du genre Calanus :**

L'AphiaID du genre Calanus est 104421.
```
https://www.marinespecies.org/rest/AphiaChildrenByAphiaID/104421?marine_only=true
```

**Exemple — tous les genres de la famille Calanidae :**

L'AphiaID de Calanidae est 106358.
```
https://www.marinespecies.org/rest/AphiaChildrenByAphiaID/106358
```

---

# Comment rechercher un taxon par nom partiel dans WoRMS ?

```
GET https://www.marinespecies.org/rest/AphiaRecordsByName/{name}?like=true&marine_only=true
```

Exemple — toutes les espèces dont le nom contient "Calanus" :
```
https://www.marinespecies.org/rest/AphiaRecordsByName/Calanus?like=true&marine_only=true
```

Retourne une liste de correspondances avec AphiaID, nom accepté, rang et statut (accepté, synonyme, non résolu).

**Champs importants dans la réponse :**
- `AphiaID` : identifiant unique
- `scientificname` : nom scientifique complet
- `status` : `accepted` | `synonym` | `unaccepted`
- `valid_AphiaID` : si synonyme, pointe vers le nom accepté
- `rank` : `Species` | `Genus` | `Family` | etc.
- `phylum`, `class`, `order`, `family`, `genus` : hiérarchie abrégée

---

# AphiaID des taxons clés pour les données du labo Maps

| Taxon | Rang | AphiaID |
|-------|------|---------|
| Copepoda | Classe | 1080 |
| Calanoida | Ordre | 1081 |
| Cyclopoida | Ordre | 1089 |
| Calanidae | Famille | 106358 |
| Calanus | Genre | 104421 |
| Calanus finmarchicus | Espèce | 104464 |
| Calanus glacialis | Espèce | 104465 |
| Calanus helgolandicus | Espèce | 104466 |
| Calanus hyperboreus | Espèce | 104467 |
| Metridia | Genre | 104517 |
| Metridia longa | Espèce | 104520 |
| Pseudocalanus minutus | Espèce | 104522 |
| Oithona | Genre | 106484 |
| Oithona similis | Espèce | 106485 |
| Eurytemora affinis | Espèce | 149081 |

**Note :** L'AphiaID de *Calanus finmarchicus* est à valider — il est distinct de *C. hyperboreus* (104464). Requête recommandée :
```
https://www.marinespecies.org/rest/AphiaIDByName/Calanus%20finmarchicus
```

---

# Comment naviguer la hiérarchie depuis EcoTaxa vers WoRMS ?

Dans un export EcoTaxa, la colonne `object_annotation_category` contient le nom du taxon tel qu'entré par l'annotateur. Ce nom correspond généralement (mais pas toujours) à un nom WoRMS accepté.

**Workflow recommandé :**

1. Extraire les noms uniques d'`object_annotation_category`.
2. Pour chaque nom, appeler :
   ```
   GET /AphiaRecordsByName/{name}?like=false&marine_only=true
   ```
3. Vérifier que `status = "accepted"`.
4. Si `status = "synonym"`, utiliser `valid_AphiaID` pour obtenir le nom accepté.
5. Récupérer la hiérarchie avec `AphiaClassificationByAphiaID`.

**Cas courants dans les données LOKI (EcoTaxa 2331) :**
- `"Calanus"` — genre, pas espèce — hiérarchie possible mais identification incomplète.
- `"Copepoda"` — classe seulement — annotation trop large pour analyse espèce.
- `"Calanus_CV"` — nomenclature labo (stade+genre) — ne correspond pas directement à WoRMS ; séparer le stade du nom scientifique.

---

# Quelles précautions prendre avec la taxonomie WoRMS dans les données historiques ?

**Synonymes et révisions taxonomiques :**
- WoRMS est mis à jour régulièrement. Un nom accepté en 2015 peut être devenu synonyme en 2023.
- Toujours vérifier `status` avant d'utiliser un nom dans une analyse comparative.

**Complexes cryptiques :**
- *Calanus glacialis* / *C. finmarchicus* : morphologiquement similaires dans les zones de chevauchement. WoRMS les distingue correctement mais les données d'annotation terrain peuvent les confondre.
- *Eurytemora affinis* / *E. carolleeae* : deux clades récemment séparés. Les données antérieures à ~2015 peuvent regrouper les deux sous *E. affinis*.

**Données OBIS et WoRMS :**
OBIS utilise WoRMS comme taxonomie de référence. Une requête OBIS filtrée par AphiaID est plus fiable qu'une requête par nom texte.

---

# Quelles sont toutes les espèces du genre Calanus reconnues dans WoRMS ?

Le genre Calanus (AphiaID : 104421, famille Calanidae) contient plusieurs dizaines d'espèces. Espèces présentes dans les données du labo Maps ou dans les zones d'intérêt (Arctique, Atlantique Nord, golfe du Saint-Laurent) :

| Espèce | AphiaID | Zones principales | Notes |
|--------|---------|-------------------|-------|
| *Calanus finmarchicus* | 104464 | Atlantique Nord, mer du Labrador, golfe du Saint-Laurent | Espèce boréale dominante |
| *Calanus glacialis* | 104465 | Plateaux arctiques, baie de Baffin, golfe du Saint-Laurent | Espèce de glace, confusion avec *C. finmarchicus* |
| *Calanus helgolandicus* | 104466 | Atlantique Nord-Est, mer du Nord | Rare dans les données du labo |
| *Calanus hyperboreus* | 104467 | Arctique central, baie de Baffin, mer du Labrador, golfe du Saint-Laurent | Plus grande espèce, diapause la plus longue |
| *Calanus marshallae* | — | Pacifique Nord-Est | Hors périmètre labo Maps |
| *Calanus pacificus* | — | Pacifique Nord | Hors périmètre labo Maps |
| *Calanus sinicus* | — | Pacifique Nord-Ouest | Hors périmètre labo Maps |

**Pour obtenir la liste complète et à jour des espèces Calanus :**
```
GET https://www.marinespecies.org/rest/AphiaChildrenByAphiaID/104421?marine_only=true
```
→ Utiliser le tool `lookup_worms_taxonomy("Calanus", include_children=True)` pour une réponse live.

---

# Comment interpréter les annotations EcoTaxa pour les stades de Calanus ?

Dans les exports EcoTaxa (colonne `object_annotation_category`), les annotations de copépodes mélangent souvent le nom du taxon WoRMS et le stade de développement. Ces noms composites ne correspondent PAS directement à des entrées WoRMS.

**Règle de décodage :**

| Annotation EcoTaxa | Genre WoRMS | Stade | AphiaID applicable |
|--------------------|-------------|-------|-------------------|
| `Calanus` | Calanus | indéterminé | 104421 (genre) |
| `Calanus_CV` | Calanus | Copépodite stade V | 104421 (genre seulement) |
| `Calanus_CIII` | Calanus | Copépodite stade III | 104421 |
| `Calanus_CIV` | Calanus | Copépodite stade IV | 104421 |
| `Calanus_AF` | Calanus | Adulte femelle | 104421 |
| `Calanus_hyperboreus` | *C. hyperboreus* | indéterminé | 104464 |
| `Calanus_glacialis_CV` | *C. glacialis* | CV | 104466 |
| `Copepoda` | Copepoda | indéterminé | 1080 (classe) |

**Règles importantes :**
- Un stade (CV, CIII, AF) n'est PAS un taxon WoRMS — il doit être extrait séparément.
- Si le genre seul est annoté (sans espèce), l'AphiaID applicable est celui du genre (104421), pas d'une espèce.
- Pour les analyses nécessitant une espèce précise, vérifier si la méthode d'identification de l'annotateur discrimine *C. glacialis* et *C. finmarchicus*.

---

# Quand utiliser le RAG et quand utiliser le tool WoRMS ?

| Situation | Source recommandée |
|-----------|-------------------|
| Espèces documentées : *C. hyperboreus*, *C. glacialis*, *C. finmarchicus*, *Oithona similis*, *Metridia longa*, *Pseudocalanus minutus* | RAG (`query_copepod_knowledge_base`) |
| Hiérarchie des taxons courants du labo | RAG |
| Décoder une annotation EcoTaxa (Calanus_CV) | RAG |
| Espèce non documentée dans le RAG | Tool WoRMS (`lookup_worms_taxonomy`) |
| Liste live de toutes les espèces d'un genre | Tool WoRMS avec `include_children=True` |
| Vérifier si un nom est accepté ou synonyme | Tool WoRMS |
| AphiaID d'une espèce rare ou nouvelle | Tool WoRMS |

*Dernière mise à jour : mai 2026*
