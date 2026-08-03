"""Teste la rétention Cloud sans imposer de ``num_ctx`` au fournisseur Ollama."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGNS = (ROOT / "benchmarks" / "windows-operator" / "campaigns").resolve()


def _prompt(target_characters: int, sentinel: str) -> str:
    lines = [f"JETON À CONSERVER : {sentinel}", "Ignore les lignes de remplissage suivantes."]
    index = 0
    current_length = sum(map(len, lines))
    while current_length < target_characters:
        digest = hashlib.sha256(f"marvin-cloud-context-{index}".encode()).hexdigest()
        line = f"ligne-{index:06d} {digest}"
        lines.append(line)
        current_length += len(line)
        index += 1
    lines.append(f"Quel était le JETON À CONSERVER ? Réponds uniquement par {sentinel}.")
    return "\n".join(lines)


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--ollama-url", default=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--minimum-prompt-tokens", type=int, default=32_768)
    parser.add_argument("--target-characters", type=int, default=180_000)
    args = parser.parse_args()
    if not (args.model.endswith(":cloud") or args.model.endswith("-cloud")):
        parser.error("Le modèle doit être un tag Ollama Cloud exact.")
    if args.minimum_prompt_tokens < 8_192 or not 50_000 <= args.target_characters <= 4_000_000:
        parser.error("Profondeur de sonde hors limites.")
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output = output.resolve()
    if CAMPAIGNS not in output.parents or output.suffix.casefold() != ".json":
        parser.error("La preuve doit rester sous benchmarks/windows-operator/campaigns.")

    sentinel = "MARVIN_CTX_" + hashlib.sha256(args.model.encode()).hexdigest()[:20].upper()
    body = json.dumps(
        {
            "model": args.model,
            "prompt": _prompt(args.target_characters, sentinel),
            "stream": False,
            "think": False,
            "keep_alive": 0,
            "options": {"temperature": 0, "num_predict": 64},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{args.ollama_url.rstrip('/')}/api/generate",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=900) as response:
        result = json.load(response)
    prompt_tokens = int(result.get("prompt_eval_count") or 0)
    answer = str(result.get("response") or "")
    passed = prompt_tokens >= args.minimum_prompt_tokens and sentinel in answer
    evidence = {
        "schema": "marvin.ollama-cloud-context-behavior/1.0",
        "captured_at": datetime.now(UTC).isoformat(),
        "model": args.model,
        "status": "verified_at_tested_depth" if passed else "failed",
        "client_context_override": None,
        "minimum_prompt_tokens": args.minimum_prompt_tokens,
        "observed_prompt_tokens": prompt_tokens,
        "sentinel_sha256": hashlib.sha256(sentinel.encode()).hexdigest(),
        "sentinel_retrieved": sentinel in answer,
        "provider_maximum_proven": False,
        "note": "La sonde prouve la rétention à la profondeur observée, pas l'allocation maximale interne du fournisseur.",
    }
    _atomic_write(output, evidence)
    print(json.dumps({"output": str(output), "status": evidence["status"], "observed_prompt_tokens": prompt_tokens}))
    return 0 if passed else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"Sonde Cloud impossible : {exc}", file=sys.stderr)
        raise SystemExit(2)
