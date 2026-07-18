#!/usr/bin/env python3
"""Exécute le parcours E2E Baie de Baffin 2024 et archive ses artefacts.

Le runner appelle directement l'API SSE de l'agent avec un ``chat_id`` stable.
Il conserve chaque input utilisateur, chaque réponse, les validations, les
graphiques référencés et le livrable PDF final dans ``logs/e2e/``.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ParsedSSE:
    content: str
    usage: dict[str, Any]


@dataclass(frozen=True)
class TurnSpec:
    name: str
    prompt: str
    timeout: int = 300


@dataclass(frozen=True)
class TurnRecord:
    index: int
    name: str
    user: str
    assistant: str
    status: str
    usage: dict[str, Any]


SCENARIO_TURNS: tuple[TurnSpec, ...] = (
    TurnSpec(
        "exploration",
        "Regroupe uniquement les samples EcoTaxa de la baie de Baffin par année "
        "depuis le cache. Recherche légère seulement : ne résume pas les objets, "
        "ne recherche pas les observations et ne lance aucun export.",
    ),
    TurnSpec(
        "selection",
        "Pour le parcours E2E, retiens les samples 14859000001, 14859000002 et "
        "14859000003 du projet EcoTaxa 14859. Scanne uniquement leurs métadonnées "
        "et confirme leurs dates, coordonnées et instrument, sans export.",
    ),
    TurnSpec(
        "export_plan",
        "Prépare l'export des copépodes validés des samples 14859000001, "
        "14859000002 et 14859000003 du projet 14859. Montre le plan et demande "
        "confirmation avant le téléchargement.",
    ),
    TurnSpec(
        "export_confirm",
        "Oui, confirme et lance exactement cet export des trois samples avec le "
        "filtre Copepoda validé.",
        timeout=600,
    ),
    TurnSpec(
        "ecopart_plan",
        "Prépare l'enrichissement du dataset EcoTaxa du projet 14859 avec le "
        "projet EcoPart correspondant. Fais le dry-run et demande confirmation.",
    ),
    TurnSpec(
        "ecopart_confirm",
        "Confirmation explicite : enrichis maintenant EcoTaxa 14859 avec EcoPart "
        "1064, confirmed=true. Utilise le dataset persistant du projet 14859 et "
        "rapporte la couverture exacte.",
        timeout=600,
    ),
    TurnSpec(
        "amundsen_enrichment",
        "Enrichis ensuite le dataset EcoTaxa 14859 avec Amundsen CTD en utilisant "
        "object_lat, object_lon, object_date et object_depth_min. Utilise les "
        "tolérances par défaut et rapporte la couverture exacte.",
        timeout=600,
    ),
    TurnSpec(
        "analysis",
        "Produis une analyse descriptive détaillée des données et des deux "
        "enrichissements : nombre de lignes et samples, période, profondeur, "
        "couverture EcoPart, couverture Amundsen et statistiques descriptives des "
        "variables environnementales disponibles. Aucun commentaire écologique.",
    ),
    TurnSpec(
        "graph",
        "Produis des graphiques descriptifs pertinents à partir des tables enrichies : "
        "répartition par profondeur et profils des variables environnementales "
        "disponibles. Applique le workflow graphique complet, les titres descriptifs, "
        "les sources et les indicateurs de confiance requis.",
        timeout=600,
    ),
    TurnSpec(
        "deliverable",
        "Génère maintenant le livrable PDF détaillé de toute cette conversation. "
        "Il doit résumer le contexte Baie de Baffin 2024, la sélection des samples, "
        "les recherches EcoTaxa, l'export, les enrichissements EcoPart et Amundsen "
        "avec leur état et leur couverture, toutes les analyses, les tableaux, les "
        "graphiques, les limites et uniquement les sources réellement utilisées.",
        timeout=600,
    ),
)


def parse_sse(raw: str) -> ParsedSSE:
    parts: list[str] = []
    usage: dict[str, Any] = {}
    for line in raw.splitlines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        try:
            payload = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        content = payload.get("choices", [{}])[0].get("delta", {}).get("content")
        if content:
            parts.append(content)
        if isinstance(payload.get("usage"), dict):
            usage = payload["usage"]
    return ParsedSSE("".join(parts), usage)


_ERROR_PATTERNS = (
    re.compile(r"\[Erreur\s*:", re.IGNORECASE),
    re.compile(r"\bErreur (?:EcoTaxa|EcoPart|Amundsen|Bio-ORACLE|OGSL)\s*:", re.IGNORECASE),
    re.compile(r"tool_calls.*tool_call_id", re.IGNORECASE | re.DOTALL),
)


def classify_turn(content: str) -> str:
    if not content.strip() or any(pattern.search(content) for pattern in _ERROR_PATTERNS):
        return "failed"
    return "passed"


def is_retryable_turn(content: str) -> bool:
    """Indique si un échec est vraisemblablement transitoire."""
    lowered = content.lower()
    return any(marker in lowered for marker in ("429", "rate_limit", "rate limit"))


def extract_asset_urls(text: str) -> list[str]:
    urls = re.findall(
        r"https?://[^\s<>\])]+/(?:graphs/[^\s<>\])]+\.png|downloads/[^\s<>\])]+\.pdf)",
        text,
    )
    return list(dict.fromkeys(url.rstrip(".,;") for url in urls))


def write_artifacts(output_dir: Path, chat_id: str, records: list[TurnRecord]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    transcript = [f"# Conversation E2E — `{chat_id}`", ""]
    for record in records:
        transcript.extend([
            f"## Tour {record.index} — {record.name}",
            "",
            f"**Statut :** {record.status}",
            "",
            "### Utilisateur",
            "",
            record.user,
            "",
            "### Assistant",
            "",
            record.assistant,
            "",
        ])
    (output_dir / "conversation.md").write_text("\n".join(transcript), encoding="utf-8")
    (output_dir / "transcript.json").write_text(
        json.dumps(
            {"chat_id": chat_id, "turns": [asdict(record) for record in records]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    validation = {
        "chat_id": chat_id,
        "status": "failed" if any(r.status == "failed" for r in records) else "passed",
        "completed_turns": len(records),
        "failed_turns": [r.name for r in records if r.status == "failed"],
    }
    (output_dir / "validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_existing_records(output_dir: Path) -> tuple[str | None, list[TurnRecord]]:
    """Recharge un transcript existant pour reprendre le même fil agent."""
    transcript_path = output_dir / "transcript.json"
    if not transcript_path.exists():
        return None, []
    payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    records = [TurnRecord(**turn) for turn in payload.get("turns", [])]
    return payload.get("chat_id"), records


def post_turn(base_url: str, chat_id: str, prompt: str, timeout: int) -> tuple[str, ParsedSSE]:
    body = json.dumps({
        "model": "copepod-agent",
        "stream": True,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "X-OpenWebUI-Chat-Id": chat_id,
            "X-OpenWebUI-User-Id": "e2e-baffin-runner",
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    return raw, parse_sse(raw)


def download_assets(output_dir: Path, records: list[TurnRecord]) -> list[Path]:
    urls = extract_asset_urls("\n".join(record.assistant for record in records))
    downloaded: list[Path] = []
    for url in urls:
        folder = output_dir / ("figures" if "/graphs/" in url else "")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / url.rsplit("/", 1)[-1]
        try:
            with urlopen(url, timeout=120) as response:
                target.write_bytes(response.read())
        except (HTTPError, URLError, TimeoutError):
            continue
        downloaded.append(target)
    return downloaded


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--chat-id")
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--retry-delay", type=float, default=5.0)
    parser.add_argument("--from-turn", type=int, default=1)
    parser.add_argument("--to-turn", type=int, default=len(SCENARIO_TURNS))
    parser.add_argument(
        "--fresh", action="store_true",
        help="Ignorer le transcript existant et forcer un nouveau thread (évite l'accumulation d'historique entre runs)",
    )
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = args.output_dir or Path("logs/e2e") / f"baffin-2024-{stamp}"
    raw_dir = output_dir / "raw_sse"
    raw_dir.mkdir(parents=True, exist_ok=True)
    existing_chat_id, existing_records = load_existing_records(output_dir)
    if args.fresh:
        existing_chat_id, existing_records = None, []
    if args.chat_id and existing_chat_id and args.chat_id != existing_chat_id:
        parser.error("--chat-id ne correspond pas au transcript existant")
    chat_id = args.chat_id or existing_chat_id or str(uuid.uuid4())
    records = [record for record in existing_records if record.index < args.from_turn]
    started = time.time()

    selected = SCENARIO_TURNS[args.from_turn - 1 : args.to_turn]
    for index, turn in enumerate(selected, start=args.from_turn):
        print(f"[RUN] {index}/{len(SCENARIO_TURNS)} {turn.name}", flush=True)
        for attempt in range(args.max_retries + 1):
            try:
                raw, parsed = post_turn(args.base_url, chat_id, turn.prompt, turn.timeout)
                status = classify_turn(parsed.content)
                assistant = parsed.content
                usage = parsed.usage
            except (HTTPError, URLError, TimeoutError) as exc:
                raw = ""
                assistant = f"[Erreur transport : {exc}]"
                usage = {}
                status = "failed"
            suffix = "" if attempt == 0 else f"_attempt_{attempt + 1}"
            (raw_dir / f"turn_{index:02d}_{turn.name}{suffix}.sse").write_text(
                raw, encoding="utf-8"
            )
            if status != "failed" or not is_retryable_turn(assistant) or attempt >= args.max_retries:
                break
            delay = args.retry_delay * (attempt + 1)
            print(f"[RETRY] {turn.name} dans {delay:.1f}s", flush=True)
            time.sleep(delay)
        records.append(TurnRecord(index, turn.name, turn.prompt, assistant, status, usage))
        write_artifacts(output_dir, chat_id, records)
        print(f"[{status.upper()}] {turn.name} — {len(assistant)} caractères", flush=True)
        if status == "failed" and not args.continue_on_error:
            break

    downloaded = download_assets(output_dir, records)
    elapsed = time.time() - started
    final_status = "failed" if any(r.status == "failed" for r in records) else "passed"
    print(f"[{final_status.upper()}] {len(records)} tour(s), {elapsed:.1f}s")
    print(f"Artefacts : {output_dir.resolve()}")
    if downloaded:
        print("Fichiers : " + ", ".join(str(path) for path in downloaded))
    return 1 if final_status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
