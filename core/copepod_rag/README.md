# Copepod RAG

Index Chroma local pour les connaissances métier copépodes. Embeddings ONNX (`all-MiniLM-L6-v2`, sans PyTorch).

Utilisé par le tool `query_copepod_knowledge_base` (voir `core/tool_registry/tools/copepod_rag.py`), exposé au profil `copepod` uniquement.

---

## Structure

```
core/copepod_rag/
├── docs/             ← sources markdown éditables (7 thèmes, ~2700 lignes)
├── chunks.json       ← chunks générés à partir de docs/ (séparateur '---')
├── chroma_db/        ← index Chroma persistant (binaire — généré)
├── chunk_docs.py     ← docs/*.md → chunks.json
├── build_index.py    ← chunks.json → chroma_db/
└── query.py          ← API Python + CLI
```

---

## Sources (`docs/`)

| Fichier | Sujet |
|---|---|
| `colonnes_sources.md` | Provenance et sémantique des colonnes (EcoTaxa, EcoPart, Bio-Oracle, OGSL) |
| `colonnes_instruments.md` | Colonnes liées aux instruments (UVP, Zooscan, FlowCAM) |
| `colonnes_labo.md` | Colonnes ajoutées en laboratoire (taxonomie, mesures) |
| `methodes_calcul.md` | Formules : biovolume, abondance, biomasse, densité, ESD |
| `taxonomie_worms.md` | Référence WoRMS (Aphia IDs, rangs, hiérarchie) |
| `copepodes_domaine.md` | Vocabulaire métier copépode (groupes, niveaux trophiques) |
| `sources_en_ligne.md` | Catalogues distants : Bio-Oracle layers, ERDDAP OGSL datasets |

---

## Chunking

`chunk_docs.py` split chaque doc sur les lignes `---` autonomes. Chaque chunk hérite :

- `source` — nom du fichier source
- `title` — titre extrait (premier `#` ou fallback 1ère ligne)
- `id` — UUID stable

Sortie : `chunks.json` (utilisé en entrée par `build_index.py`).

```bash
python core/copepod_rag/chunk_docs.py
# Produit chunks.json avec N chunks à partir de docs/*.md
```

---

## Build de l'index

```bash
python core/copepod_rag/build_index.py
# Idempotent : delete + recreate la collection "copepod_rag"
# Embeddings : ChromaDB DefaultEmbeddingFunction (all-MiniLM-L6-v2 via ONNX)
# Pas de PyTorch requis
```

L'index est persisté dans `chroma_db/` (binaire ; n'éditer jamais à la main).

**Quand reconstruire ?**
- Après toute modification d'un fichier dans `docs/`
- Après modification du chunking dans `chunk_docs.py`
- Après changement de modèle d'embedding dans `build_index.py`

Workflow complet :
```bash
python core/copepod_rag/chunk_docs.py && python core/copepod_rag/build_index.py
```

---

## Query

### Python

```python
from core.copepod_rag.query import query_copepod_rag

results = query_copepod_rag("acq_pixel signification", top_k=3)
# → [{"source": "colonnes_instruments.md", "title": "...", "text": "...", "score": 0.87}, ...]
```

### CLI

```bash
python core/copepod_rag/query.py "biovolume ESD calcul"
```

### Via le LLM (sandbox interpreter)

```python
# Le tool est exposé au profil copépode :
query_copepod_knowledge_base("comment calculer le biovolume ?", session_id=session_id, top_k=3)
```

---

## Observabilité

`query.py` :
- Silence les warnings natifs (C-level) d'onnxruntime/chromadb via redirection FD pour ne pas polluer le stream OI
- Émet une span Langfuse si `should_enable_langfuse()` est vrai (voir `core/copepod_observability.py`)

---

## Voir aussi

- `core/tool_registry/tools/copepod_rag.py` — wrapper exposé au LLM
- `core/tool_registry/README.md` — vue d'ensemble des tools
- [`CLAUDE.md`](../../CLAUDE.md) — architecture globale
