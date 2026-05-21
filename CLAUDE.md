# CLAUDE.md — IDEA · Assistant copépodes · NeoLab, Université Laval

## Ce projet en deux mots

IDEA est une plateforme web FastAPI + OpenInterpreter forquée et spécialisée pour l'exploration de données de copépodes marins (EcoTaxa / EcoPart / Amundsen CTD). L'utilisateur pose des questions en langage naturel, IDEA exécute du code Python et répond avec des analyses, des graphiques et des sources citées.

---

## Architecture des deux repos

```
PROJET_INFO/
  assistant-copepodes-specs/   ← specs, TDD, package Python
    polar_data_tools/          ← tools testés (pytest, TDD)
    tests/                     ← suite de tests
    TOOLS_SPEC.js              ← 22 tools spécifiés
    TEST_SCENARIOS.md          ← 17 scénarios comportementaux
    IMPLEMENTATION_ORDER.md    ← 8 phases, Sprint 1 = Phase 0–3

  IDEA/                        ← ce repo — runtime web
    utils/
      custom_functions.py      ← tools géoscience génériques (ne pas modifier)
      copepod_functions.py     ← NOUVEAU : tools copépodes (à créer)
      custom_instructions.py   ← instructions LLM (à étendre)
    app.py                     ← point d'entrée FastAPI
    pyproject.toml             ← dépend de polar-data-tools (local)
```

**Règle :** on implémente et on teste dans `assistant-copepodes-specs/polar_data_tools/`. On expose dans IDEA via `copepod_functions.py`. On ne touche pas à `custom_functions.py`.

---

## Comment les tools sont injectés dans OpenInterpreter

`utils/custom_functions.py` définit une chaîne Python `custom_tool`. À l'initialisation de chaque session (`app.py` ligne ~1117) :

```python
interpreter.computer.run("python", custom_tool)
```

Toutes les fonctions définies dans cette chaîne deviennent disponibles pour le LLM pendant l'exécution de code. `copepod_functions.py` suivra exactement le même pattern :

```python
# utils/copepod_functions.py
copepod_tool = """
from polar_data_tools import session, context, data, columns, sources, ...

def polar_set_mode(mode): ...
def polar_inspect_data(path): ...
"""
```

Et dans `app.py`, après la ligne existante :
```python
interpreter.computer.run("python", custom_tool)
interpreter.computer.run("python", copepod_tool)   # ← à ajouter
```

---

## Dépendance locale polar-data-tools

`polar_data_tools` est développé dans `../assistant-copepodes-specs`. Pour l'installer dans IDEA :

```bash
uv add "polar-data-tools @ file://../assistant-copepodes-specs"
```

Après chaque modification du package, relancer `uv sync` dans IDEA.

---

## Sprint 1 — ce qui est à implémenter maintenant

Suivre `../assistant-copepodes-specs/IMPLEMENTATION_ORDER.md`.

| Phase | Contenu | Repo où coder |
|---|---|---|
| 0 | `session.set_mode`, `session.get_mode`, `context.get_required_fields` | `assistant-copepodes-specs` |
| 0.5 | Index RAG ChromaDB (5 docs) | `assistant-copepodes-specs` |
| 1 | `data.inspect`, `data.validate`, `data.profile_missing` | `assistant-copepodes-specs` |
| 2 | `columns.describe`, `columns.check_for_calculation` | `assistant-copepodes-specs` |
| 3 | `context.validate_species` | `assistant-copepodes-specs` |

Une fois une phase validée par les tests pytest, on l'expose dans IDEA via `copepod_functions.py`.

---

## Sources de données copépodes

| Source | ID | Contenu |
|---|---|---|
| EcoTaxa UVP5 | `1165` | UVP5 Amundsen 2018, objets + morphométrie |
| EcoPart | `105` | UVP5 Amundsen 2018, profils CTD + particules |
| Amundsen CTD | `ca-cioos_ccin-12713` | CTD-Rosette officielle via ERDDAP |
| EcoTaxa LOKI | `2331` | Copépodes lipides, taxonomie annotée |

Credentials EcoTaxa/EcoPart dans `.env` — jamais commités.

---

## Architecture IDEA (original)

- **Backend** : FastAPI (`app.py`, 1 816 lignes)
- **Exécution de code** : OpenInterpreter (fork `M-J-W1/open-interpreter@responses_v3.0.4`)
- **LLM** : LiteLLM — supporte OpenAI, Anthropic, Jetstream2
- **Base de données** : PostgreSQL + pgvector, SQLModel ORM, Alembic migrations
- **Cache/sessions** : Redis
- **Littérature RAG** : PaperQA2 — indexe les PDF dans `data/papers/`
- **Frontend** : HTML/CSS/JS vanilla, servi par NGINX

---

## Démarrage local

```bash
# Copier et remplir les variables d'environnement
cp example.env .env
cp frontend/config.example.js frontend/config.js

# Démarrer (Docker requis)
./local_start.sh
# → http://localhost
```

Variables `.env` minimum :
- `OPENAI_API_KEY` ou `ANTHROPIC_API_KEY`
- `FIRST_SUPERUSER` + `FIRST_SUPERUSER_PASSWORD`
- `LOCAL_DEV=1`

---

## Ajouter un tool copépode (checklist)

1. Implémenter la fonction dans `../assistant-copepodes-specs/polar_data_tools/`
2. Écrire le test pytest dans `../assistant-copepodes-specs/tests/`
3. Vérifier que le test passe (`uv run pytest tests/test_xxx.py`)
4. Exposer la fonction dans `utils/copepod_functions.py` (chaîne Python)
5. Étendre `utils/custom_instructions.py` si nécessaire
6. Tester dans IDEA via `./local_start.sh`

---

## Fichiers à ne pas modifier

| Fichier | Raison |
|---|---|
| `utils/custom_functions.py` | Tools géoscience génériques — upstream IDEA |
| `utils/system_prompt.py` | Prompt de base — upstream IDEA |
| `alembic/` | Migrations DB — ne pas altérer sans raison |

---

## Pas de suite de tests dans IDEA

Les tests vivent dans `assistant-copepodes-specs/tests/`. IDEA n'a pas de suite pytest — les tools sont testés avant d'être intégrés.
