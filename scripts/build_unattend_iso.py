"""Build and verify the transient Windows Autounattend ISO deterministically."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pycdlib


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--answer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    answer = args.answer.resolve(strict=True)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".new")
    temporary.unlink(missing_ok=True)

    iso = pycdlib.PyCdlib()
    try:
        iso.new(interchange_level=3, joliet=3, vol_ident="MARVIN_UNATTEND")
        iso.add_file(str(answer), iso_path="/AUTOUNAT.XML;1", joliet_path="/Autounattend.xml")
        iso.write(str(temporary))
    finally:
        iso.close()
    temporary.replace(output)

    extracted = output.with_suffix(output.suffix + ".verify")
    extracted.unlink(missing_ok=True)
    check = pycdlib.PyCdlib()
    try:
        check.open(str(output))
        with extracted.open("wb") as stream:
            check.get_file_from_iso_fp(stream, joliet_path="/Autounattend.xml")
    finally:
        check.close()
    try:
        if sha256(answer) != sha256(extracted):
            raise RuntimeError("Le fichier Autounattend relu diffère de la source.")
    finally:
        extracted.unlink(missing_ok=True)
    print(json.dumps({
        "output_iso": str(output),
        "output_sha256": sha256(output),
        "answer_sha256": sha256(answer),
        "builder": "pycdlib-1.22.0",
        "builder_network_during_secret_processing": False,
        "contains_transient_secret": True,
        "must_destroy_after_installation": True,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
