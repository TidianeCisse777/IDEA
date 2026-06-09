"""Shared eval runner — eliminates boilerplate across eval suites."""
from typing import Callable
from langsmith.evaluation import evaluate
from langsmith import Client


def run_eval_suite(
    cases: list[dict],
    run_fn: Callable[[dict], dict],
    evaluators: list,
    dataset_name: str,
    experiment_prefix: str,
    metadata: dict,
) -> list[tuple[str, dict]]:
    """Run an eval suite, push to LangSmith, return scored rows.

    Args:
        cases: List of {id, inputs, outputs} dicts.
        run_fn: Function that takes inputs dict and returns outputs dict.
        evaluators: List of LangSmith-compatible evaluator functions.
        dataset_name: LangSmith dataset name (recreated on each run).
        experiment_prefix: Prefix for the experiment name in LangSmith.
        metadata: Extra metadata attached to the experiment.

    Returns:
        List of (scenario_id, {evaluator_key: score}) sorted by scenario_id.
    """
    client = Client()

    datasets = list(client.list_datasets(dataset_name=dataset_name))
    if datasets:
        client.delete_dataset(dataset_id=datasets[0].id)
    dataset = client.create_dataset(dataset_name=dataset_name)
    for case in cases:
        client.create_example(
            inputs=case["inputs"],
            outputs=case["outputs"],
            dataset_id=dataset.id,
            metadata={"scenario_id": case["id"]},
        )
    print(f"Dataset recréé : {dataset_name} ({len(cases)} exemples)")

    results = evaluate(
        run_fn,
        data=dataset_name,
        evaluators=evaluators,
        experiment_prefix=experiment_prefix,
        metadata=metadata,
        max_concurrency=5,
    )

    rows = []
    for r in results._results:
        example = r["example"]
        sc_id = example.metadata.get("scenario_id", "?") if example.metadata else "?"
        scores = {
            e.key: (e.score or 0.0)
            for e in r["evaluation_results"]["results"]
        }
        comments = {
            e.key: (e.comment or "")
            for e in r["evaluation_results"]["results"]
        }
        rows.append((sc_id, scores, comments))

    rows.sort(key=lambda x: x[0])
    return rows


def print_scores(rows: list[tuple], score_keys: list[str], threshold: float = 0.8) -> bool:
    """Print a score table and return True if all averages are above threshold."""
    if not rows:
        return False

    header = f"  {'ID':<8}" + "".join(f"  {k:>14}" for k in score_keys)
    print(header)
    print("  " + "-" * (8 + 16 * len(score_keys)))

    all_scores = {k: [] for k in score_keys}
    for row in rows:
        sc_id, scores = row[0], row[1]
        comments = row[2] if len(row) > 2 else {}
        line = f"  {sc_id:<8}"
        failures = []
        for k in score_keys:
            s = scores.get(k, 0.0)
            all_scores[k].append(s)
            mark = "✓" if s >= threshold else "✗"
            line += f"  {mark} {s:.2f}        "
            if s < threshold and comments.get(k):
                failures.append(f"    [{k}] {comments[k]}")
        print(line)
        for f in failures:
            print(f)

    print()
    avgs = {k: sum(v) / len(v) for k, v in all_scores.items()}
    avg_line = "  Moyennes  " + "".join(f"  {avgs[k]:>8.2f}      " for k in score_keys)
    print(avg_line)

    passed = all(v >= threshold for v in avgs.values())
    if passed:
        print(f"\n✓ Validé — ok pour continuer.")
    else:
        print(f"\n⚠ Score < {threshold} — corriger avant de continuer.")
    return passed
