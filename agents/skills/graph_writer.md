# Skill : graph_writer

Tu dois écrire du code matplotlib correct et complet.

## Template de base

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(10, 6))

# --- ton code ici ---

ax.set_title("<titre descriptif>")
ax.set_xlabel("<label axe X>")
ax.set_ylabel("<label axe Y>")
plt.tight_layout()
```

## Règles obligatoires

- Toujours utiliser `matplotlib.use("Agg")` — pas d'affichage interactif
- Toujours utiliser `fig, ax = plt.subplots()` — ne jamais appeler `plt.show()`
- Toujours définir `title`, `xlabel`, `ylabel`
- Pour les labels longs (noms de taxons) : `ax.tick_params(axis='x', rotation=45)`
- Pour les bar charts horizontaux si les labels sont nombreux (> 10) : utiliser `ax.barh()`
- Ne jamais appeler `plt.savefig()` — le système capture automatiquement la figure

## Gestion des données

- Trier les valeurs avant de tracer (ex. `.sort_values(ascending=False)`)
- Limiter à 20 éléments max si la colonne catégorielle a beaucoup de valeurs
- Supprimer les NaN avant de tracer : `.dropna()`
