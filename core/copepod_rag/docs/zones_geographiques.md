# Zones géographiques NeoLab — Amundsen et campagnes arctiques

Mots-clés : zones géographiques, baie de Baffin, mer de Beaufort, golfe du Saint-Laurent, baie d'Hudson, détroit de Davis, Arctique canadien, stations, latitude, longitude, filtrage spatial

Ce document liste les zones géographiques couvertes par les campagnes NeoLab et les croisières Amundsen. Pour filtrer les données par zone, utiliser les bornes lat/lon ci-dessous sur les colonnes `latitude`, `longitude` (données labo) ou `obj_latitude`, `obj_longitude` (EcoTaxa).

---

## Baie de Baffin

- **Latitude** : 66°N – 78°N
- **Longitude** : 58°W – 80°W
- **Stations typiques** : FoxSIPP, BB, Baffin
- **Contexte** : Zone de forte concentration de copépodes arctiques (Calanus hyperboreus, C. glacialis). Croisières Amundsen récurrentes.

**Filtre pandas** :
```python
mask = (df['latitude'] >= 66) & (df['latitude'] <= 78) & (df['longitude'] >= -80) & (df['longitude'] <= -58)
```

---

## Mer de Beaufort

- **Latitude** : 68°N – 76°N
- **Longitude** : 120°W – 145°W
- **Stations typiques** : CB, Beaufort, ArcticNet
- **Contexte** : Zone de glace saisonnière, données CTD et zooplancton Amundsen.

**Filtre pandas** :
```python
mask = (df['latitude'] >= 68) & (df['latitude'] <= 76) & (df['longitude'] >= -145) & (df['longitude'] <= -120)
```

---

## Golfe du Saint-Laurent

- **Latitude** : 45°N – 51°N
- **Longitude** : 56°W – 67°W
- **Stations typiques** : GSL, IML, Rimouski
- **Contexte** : Zone côtière et estuarienne, données labo NeoLab et OGSL.

**Filtre pandas** :
```python
mask = (df['latitude'] >= 45) & (df['latitude'] <= 51) & (df['longitude'] >= -67) & (df['longitude'] <= -56)
```

---

## Baie d'Hudson

- **Latitude** : 51°N – 65°N
- **Longitude** : 77°W – 95°W
- **Stations typiques** : HB, Hudson
- **Contexte** : Zone peu profonde, saisonnière. Couverture de glace importante en hiver.

**Filtre pandas** :
```python
mask = (df['latitude'] >= 51) & (df['latitude'] <= 65) & (df['longitude'] >= -95) & (df['longitude'] <= -77)
```

---

## Détroit de Davis

- **Latitude** : 63°N – 70°N
- **Longitude** : 52°W – 68°W
- **Stations typiques** : DS, Davis
- **Contexte** : Passage entre baie de Baffin et Atlantique Nord. Zone de mélange de masses d'eau.

**Filtre pandas** :
```python
mask = (df['latitude'] >= 63) & (df['latitude'] <= 70) & (df['longitude'] >= -68) & (df['longitude'] <= -52)
```

---

## Arctique canadien (général)

Regroupe l'ensemble des zones au nord de 60°N dans les eaux canadiennes.

**Filtre pandas** :
```python
mask = df['latitude'] >= 60
```

---

## Notes d'utilisation

- Les noms de zones peuvent varier selon le fichier : utiliser les bornes lat/lon plutôt que les noms de stations.
- Si le fichier contient `STATION_NAME`, chercher les préfixes associés à la zone (ex. "FoxSIPP" → baie de Baffin).
- Pour une carte, tracer `longitude` en X et `latitude` en Y avec `scatter` ou `folium`.
