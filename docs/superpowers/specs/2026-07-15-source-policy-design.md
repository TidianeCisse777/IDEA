# Source Policy Design — étape 3

**Date :** 15 juillet 2026
**Statut :** design approuvé en conversation, en attente de revue du document
**Portée :** décision de source exécutable et affinité persistante; aucun filtrage dynamique par workflow, aucune confirmation et aucun `source_lock` persistant dans cette étape.

## Objectif

Remplacer la détection EcoTaxa ad hoc par une décision structurée commune aux sources autorisées. Une source externe doit être nommée une première fois pour être activée, puis rester active sur les tours suivants sans obliger l'utilisateur à répéter son nom. Un identifiant numérique seul ne choisit jamais une source lorsqu'aucune affinité ne l'établit déjà.

## Sources reconnues

Le vocabulaire canonique est fermé :

- `file`
- `ecotaxa`
- `ecopart`
- `amundsen`
- `bio_oracle`
- `ogsl`
- `sql`

Les tools communs — géographie, RAG, taxonomie, skills, graphiques et livrables — ne constituent pas des sources sélectionnables. Leur disponibilité continue d'être régie par leurs politiques propres et par les étapes ultérieures du harness.

## Modèle de décision

`SourceDecision` est une valeur immuable calculée pour le tour courant :

- `primary_source: SourceName | None`
- `authorized_sources: tuple[SourceName, ...]`
- `explicit_sources: tuple[SourceName, ...]`
- `evidence: explicit_name | inherited_affinity | loaded_file_default | none`
- `needs_clarification: bool`
- `reason: str`

`SourceAffinity` est la mémoire persistante minimale de la conversation :

- `active_sources: tuple[SourceName, ...]`
- `evidence: explicit_name | file_loaded`
- `origin_user_text: str` tronqué et nettoyé
- `updated_at: str`

L'affinité est enregistrée sous une clé de métadonnées dédiée du session store. Elle ne contient ni DataFrame, ni identifiant découvert, ni contenu de résultat. Elle exprime uniquement le choix de source de l'utilisateur.

## Règles de décision

Les règles sont évaluées dans cet ordre :

1. Une commande explicite de retour au fichier, avec un fichier disponible, remplace l'affinité par `file`.
2. Une commande explicite de bascule (« passe à », « uniquement », « utilise plutôt ») remplace l'affinité par exactement les sources nommées.
3. Une demande explicitement comparative ou d'enrichissement (« compare avec », « enrichis avec », « croise avec ») combine les sources nommées avec l'affinité courante pour cette continuité multi-source.
4. Une source explicitement nommée sans commande de combinaison remplace l'affinité précédente; aucune ancienne source ne reste autorisée silencieusement.
5. Le chargement réussi d'un nouveau fichier remplace l'affinité par `file`.
6. Sans nouvelle sélection explicite, l'affinité existante est héritée.
7. Lorsqu'un fichier est chargé et qu'une affinité externe est héritée pour une comparaison ou un enrichissement, `file` reste la source principale et l'affinité externe reste autorisée comme source secondaire.
8. Sans affinité, un fichier chargé devient la source principale pour les demandes génériques.
9. Sans affinité et sans fichier, aucune source n'est choisie; une demande de données nécessite une clarification.
10. Un `project_id`, `sample_id`, numéro de station ou autre identifiant nu ne crée aucune affinité. Il est utilisable seulement si la source est déjà autorisée et si les contrôles de grounding existants l'acceptent.
11. Une exclusion explicite comme « sans EcoTaxa » ou « n'utilise pas EcoTaxa » retire cette source et ne l'active jamais. Si aucune source ne reste, la décision demande une clarification ou revient au fichier disponible.

Une affinité n'est pas un verrou. L'utilisateur peut changer de source à tout moment en nommant la nouvelle source. Le futur `source_lock` de l'étape 5 couvrira séparément les restrictions persistantes telles que « uniquement ce TSV ».

## Exemples normatifs

| État avant le tour | Message | Décision |
|---|---|---|
| aucune affinité | « résume le projet 17498 » | aucune source; clarification |
| aucune affinité | « dans EcoTaxa, résume le projet 17498 » | `ecotaxa` actif |
| `ecotaxa` actif | « montre les samples du projet 17498 » | `ecotaxa` hérité |
| `ecotaxa` actif | « passe à EcoPart » | `ecopart` remplace EcoTaxa |
| `ecotaxa` actif | « compare avec EcoPart » | `ecotaxa` + `ecopart` actifs |
| `ecotaxa` actif | « compare EcoTaxa et EcoPart » | `ecotaxa` + `ecopart` actifs |
| `ecotaxa` actif | nouveau fichier chargé | `file` remplace EcoTaxa |
| fichier actif | « compare mon fichier avec Bio-ORACLE » | `file` principal, `bio_oracle` autorisé pour le tour et devient l'affinité externe explicite |
| fichier actif | « projet 17498 » | `file`; EcoTaxa reste bloqué |
| `ecotaxa` actif | « sans EcoTaxa, utilise mon fichier » | `file` actif |

Pour le cas fichier + source externe, le fichier reste la donnée principale de l'opération. L'affinité mémorise la source explicitement demandée afin que les tours de suivi de l'enrichissement n'exigent pas de la renommer; la présence du fichier reste visible dans `SourceDecision.primary_source`.

## Flux runtime

1. Le middleware extrait uniquement le dernier message utilisateur.
2. Le parseur déterministe détecte les noms de sources, les exclusions et les commandes de retour au fichier.
3. Le builder lit l'affinité et les métadonnées actives du session store, puis produit `SourceDecision`.
4. Avant le modèle, les tools des sources non autorisées sont retirés.
5. Avant chaque exécution, la même décision est recalculée et l'appel est refusé si sa source n'est pas autorisée. Le contrôle est donc fail-closed même si le modèle fabrique un appel absent de sa liste visible.
6. Une sélection explicite est persistée de façon idempotente. Un chargement de fichier réussi persiste `file`.

Le modèle et le garde d'exécution consomment le même objet de décision. Aucun second parseur ou ensemble de regex ne doit exister dans `agent.py`.

## Alignement du prompt

Le bloc `Source Selection Gateway` est rendu depuis les constantes et règles publiques de la politique, puis injecté dans `COPEPOD_SYSTEM_PROMPT`. Le prompt explique la décision au modèle, mais n'accorde aucune autorisation. Les tests vérifient que les exemples critiques du prompt et la décision Python restent cohérents.

## Refus et clarification

- Un appel de source non autorisée retourne un `ToolMessage` bloqué avec une raison clinique et la source attendue.
- Un ID nu sans source ne déclenche aucun appel externe. La réponse attendue demande à quelle source appartient l'identifiant.
- Une source inconnue n'est jamais transformée en source autorisée par approximation.
- Une affinité corrompue ou contenant une valeur hors enum est ignorée et conduit au comportement sans affinité.
- Aucune erreur interne, regex ou clé du store n'est exposée à l'utilisateur.

## Compatibilité

- `ecotaxa_signal()`, `is_file_scoped_turn()` et `filter_tools_for_scope()` restent temporairement disponibles comme façades compatibles, mais délèguent à la nouvelle politique.
- Les contrôles de grounding de `tools/session_context.py` restent indépendants : une source autorisée ne rend pas automatiquement un identifiant fondé.
- Les politiques `ToolPolicy.source` du catalogue servent à classifier les tools; aucune nouvelle liste parallèle de 62 noms n'est créée.
- Les confirmations des opérations lourdes restent déclaratives jusqu'à l'étape 7.

## Tests et critères d'acceptation

1. Le contrat red-team « projet 17498 » devient vert et perd son `xfail`.
2. Une matrice paramétrée couvre les sept sources, leurs alias explicites, les exclusions et les IDs nus.
3. L'affinité persiste entre deux tours et est remplacée par une nouvelle source ou un fichier chargé.
4. Le filtre pré-modèle et le garde pré-tool produisent la même allowlist de sources.
5. Les tools communs restent disponibles; aucun tool d'une source non autorisée ne traverse le garde.
6. Les contrôles d'identifiants non fondés restent verts.
7. Les scénarios offline existants conservent 100 % aux niveaux 1 et 2; un scénario de continuité EcoTaxa est ajouté.
8. Aucun replay live ni appel OpenRouter n'est lancé pendant l'implémentation.

## Hors portée

- `TurnContext` complet, carte des dérivés et `source_lock` de l'étape 5.
- Sélection de 6 à 12 tools selon l'intention ou le workflow de l'étape 6.
- Grants de confirmation de l'étape 7.
- Classification sémantique par LLM des sources implicites.
- Migration ou refactor sans rapport avec la décision de source.
