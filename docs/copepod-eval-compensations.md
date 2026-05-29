# Compensations dans le harness d'eval copépode

À lire si tu n'es pas sûr de ce que mesure vraiment `--live`.

---

## TL;DR

Le harness eval ne se contente pas d'appeler le LLM et de regarder le résultat. **Entre le moment où le LLM produit un tool_call et le moment où le tool s'exécute, du code dans `llm_driver.py` réécrit silencieusement les arguments**.

Ces réécritures s'appellent des **compensations**. Elles existent pour rattraper un LLM qui n'a pas suivi le protocole exactement. Tant qu'elles sont actives, **un test vert peut être vert parce que le LLM a fait juste, OU parce que le harness l'a rattrapé**. Tu ne peux pas distinguer les deux cas.

Le flag `--no-compensations` désactive ces réécritures. Le compteur dans le rapport te dit combien de fois chaque compensation a tiré pendant un run.

---

## Pourquoi c'est un problème

Imagine que tu lances `--live` et obtiens `12/14`. Tu corriges le system prompt, tu relances, tu obtiens `13/14`. Tu penses : "ma correction a amélioré le LLM".

Mais en réalité, peut-être que :

- Au run 1, le LLM a raté sa Phase 1 → le harness a rattrapé → le test est passé "par chance"
- Au run 2, ta correction n'a rien fait au LLM, mais a déclenché une autre branche du harness qui rattrape mieux

**Tu n'as pas amélioré le LLM. Tu as déplacé le rattrapage.** Et tu ne le sais pas, parce que le score est ton seul signal.

C'est exactement la situation actuelle du sprint : `--live` à 7/14, on corrige des trucs, le score bouge, mais on ne sait pas si on corrige le LLM ou si on corrige le harness.

---

## Les 3 compensations concrètes

### 1. `rewrite_synthesize_summaries`

**Où** : `llm_driver.py` dans `_live_tool_impls.call_tool`

**Quoi** : quand le LLM appelle `synthesize_file_understanding(file_summaries=[...])`, le harness regarde combien de fichiers tu as chargés. Si le LLM en a passé moins, ou si ses `file_summaries` n'ont pas tous un `column_catalogue`, le harness **remplace ses arguments** par les vrais `summarize_understanding` qu'il a cachés au passage.

**Exemple concret** : tu charges EcoTaxa + EcoPart. Le LLM appelle `synthesize_file_understanding(file_summaries=[ecotaxa_summary])` — il a oublié EcoPart. Sans compensation : la synthèse globale n'a qu'un fichier, le test `du_multi_*_payload_has_n_files` échoue. Avec compensation : le harness remplace silencieusement par `[ecotaxa_summary, ecopart_summary]`, le test passe.

### 2. `patch_du_artifact_from_cache`

**Où** : `llm_driver.py` dans `_live_tool_impls.call_tool`

**Quoi** : quand le LLM appelle `create_data_understanding_draft(artifact={...})`, le harness fusionne dans cet `artifact` toutes les clés du dernier `summarize_understanding` caché qui manquaient.

**Exemple concret** : le LLM crée son artifact avec juste `{"files": [...]}` mais oublie `column_catalogue` et `coverage_assessment`. Sans compensation : le test `live_du_payload_has_column_catalogue` échoue. Avec compensation : le harness recolle les champs depuis le cache, le test passe.

### 3. `block_repeat_describe_column`

**Où** : `llm_driver.py` dans `_run_llm_turn`

**Quoi** : si le LLM appelle `describe_column` dans deux tours consécutifs au sein d'une phase, le harness **n'exécute pas** ses appels et lui renvoie un faux tool-error `"describe_column already used... You MUST call summarize_understanding now."`.

**Exemple concret** : le LLM part en boucle sur describe_column (souvent vu en pratique). Sans compensation : il consomme des tokens, atteint `max_tool_rounds=40`, la phase 1 échoue. Avec compensation : il est forcé de passer à `summarize_understanding` au tour suivant.

---

## Ce qui a changé dans le code

### Avant

```python
# llm_driver.py
def _live_tool_impls(tools, session_key):
    _cache = {}
    def call_tool(name, arguments):
        if name == "synthesize_file_understanding":
            # rewrite happens here, silently
            if cached_summaries and ...:
                arguments = {**arguments, "file_summaries": cached_summaries}
        ...
```

Les réécritures étaient toujours actives, jamais comptées, invisibles dans le rapport.

### Après

```python
# llm_driver.py
@dataclass
class CompensationLayer:
    rewrite_synthesize_summaries: bool = True
    patch_du_artifact_from_cache: bool = True
    block_repeat_describe_column: bool = True
    counts: dict[str, int] = field(default_factory=dict)

    def record(self, name): self.counts[name] = self.counts.get(name, 0) + 1

    @classmethod
    def all_off(cls): return cls(False, False, False)


def _live_tool_impls(tools, session_key, *, compensations=None):
    comp = compensations or CompensationLayer()
    def call_tool(name, arguments):
        if name == "synthesize_file_understanding" and comp.rewrite_synthesize_summaries:
            if cached_summaries and ...:
                arguments = {**arguments, "file_summaries": cached_summaries}
                comp.record("rewrite_synthesize_summaries")  # ← visible
```

Et `EvalHarness` choisit :

```python
# harness.py
self.compensations = (
    CompensationLayer.all_off() if self._disable_compensations
    else CompensationLayer()
)
```

Le rapport eval contient maintenant :

```python
{
  "passed": True,
  "passed_count": 14,
  "compensations_disabled": False,
  "compensations_applied": {
    "rewrite_synthesize_summaries": 1,
    "patch_du_artifact_from_cache": 3
  }
}
```

Le log file finit par :

```
=== COMPENSATIONS applied=4 disabled=False ===
  patch_du_artifact_from_cache: 3
  rewrite_synthesize_summaries: 1
```

---

## Comment t'en sers

### Run normal (default, comme avant)

```bash
docker exec -it idea-app python scripts/evals/run_copepod_plan_mode_eval.py --live
```

Mêmes scores qu'avant le refactor. Mais à la fin tu vois :

```
12/14 passed
compensations applied=4 disabled=False
  patch_du_artifact_from_cache: 3
  rewrite_synthesize_summaries: 1
```

→ Tu sais que 4 fois le harness a rattrapé le LLM. Si ta correction réduit ce nombre, c'est que le LLM s'améliore vraiment.

### Run "baseline LLM nu"

```bash
docker exec -it idea-app python scripts/evals/run_copepod_plan_mode_eval.py --live --no-compensations
```

Le harness ne rattrape rien. Le score reflète **exactement** ce que ferait le LLM en prod.

```
8/14 passed
compensations applied=0 disabled=True
```

→ 4 tests étaient verts uniquement grâce au harness. Ces 4-là sont tes prochains tickets : prompt à durcir ou tool spec à corriger.

### Workflow type

1. Lance `--live` normal pour mesurer la régression vs avant.
2. Lance `--live --no-compensations` pour mesurer le LLM nu.
3. Le delta = "ce que je dois corriger côté production".
4. Quand le delta tombe à 0, tu peux supprimer les compensations du code et l'eval mesure le LLM directement.

---

## Ce que ça ne fait pas

- **Ça ne change pas le LLM**. Le system prompt, les tools, les schémas — rien n'a bougé côté production.
- **Ça ne change pas les scores par défaut**. `--live` sans flag = même comportement qu'avant.
- **Ça ne supprime pas la couche de normalisation** dans `copepod_session_artifacts.py` (`_normalize_data_understanding_payload`). Cette couche existe côté tool, pas côté harness, et reste active dans les deux modes. C'est un refactor séparé (#1 dans la critique d'archi).

---

## Quand c'est inutile

- Sur `--mock` : le mock n'utilise pas `_live_tool_impls` ni `_run_llm_turn`, donc `compensations applied=0` toujours. Le flag est ignoré.
- Sur les evals direct-analysis / offtopic / rejection : non scopés dans le sprint actif, gardent le comportement par défaut.

---

## Pourquoi ne pas tout désactiver tout de suite ?

Parce que le sprint actif est "passer `--live` à 14/14". Si on désactive par défaut, on casse `--live-du-only` et `--live-gc-only` qui sont actuellement verts — pas parce qu'ils sont mauvais, mais parce qu'ils dépendaient en partie du rattrapage. On veut un signal honnête, pas un score qui tombe sans contexte.

L'idée : un sprint pour réduire `compensations_applied` à 0 sur tous les modes. Quand c'est fait, on supprime le code des compensations et `_live_tool_impls` redevient un dumb passthrough. C'est le vrai état "deep" du harness.
