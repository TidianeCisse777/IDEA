# Architecture du warehouse NeoLab V1

```mermaid
flowchart TD
    ET[EcoTaxa : samples et objets] --> I[Ingestion versionnée]
    EP[EcoPart : profils, bins, volumes, LPM] --> I
    AS[Amundsen : profils et mesures CTD] --> I
    NF[FILET : samples, analyses, abondances] --> I

    I --> V[(warehouse.dataset_version)]
    I --> UVP[warehouse.uvp_*\nEcoTaxa + EcoPart joints]
    I --> CTD[warehouse.ctd_*]
    I --> NET[warehouse.filet_*]
    CTD --> L[Liens vérifiés\nuvp_ctd, ecotaxa_ctd, filet_ctd]
    UVP --> L
    NET --> L

    UVP --> UTA[uvp_taxon_abundance\ncalculée par bin]
    UTA --> EV[explore.uvp*]
    NET --> EF[explore.filet*\nvaleurs NeoLab conservées]
    L --> M[Match FILET–UVP\nstation + écart temporel]
    UTA --> C[explore.filet_uvp_abundance]
    NET --> C
    M --> C
    EV --> SQL[SQL généré par IDEA]
    EF --> SQL
    C --> SQL
    SQL --> DF[DataFrame du notebook]
    DF --> P[Graphiques et analyses]
```

Le warehouse conserve les données sources et leurs clés natives. Les tables
`explore` sont la surface de lecture de l'agent : elles portent aussi les
métadonnées nécessaires (campagne, station, date, position, instrument et
profondeur) pour éviter des tours de jointure dans le notebook.

L'abondance UVP taxonomique est dérivée de `COUNT(EcoTaxa objects)` et du
`Sampled volume [L]` EcoPart. L'abondance FILET est importée depuis les colonnes
NeoLab déjà normalisées. Les filtres de taxon, stade, profondeur et fenêtre
temporelle restent dans le SQL de l'agent ; les relations de provenance sont
résolues à l'ingestion.

Cette V1 est un contrat logique à valider sur les exports retenus. Le DDL est
un brouillon non déployé ; la vue finale de comparaison doit encore être
implémentée après validation des colonnes CTD et des règles de support vertical.
