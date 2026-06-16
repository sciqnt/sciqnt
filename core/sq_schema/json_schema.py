"""Language-agnostic export of the canonical contract as JSON Schema.

The sciqnt contract is *authored* in Python (pydantic models), but the contract
ITSELF must be inspectable without Python — so a connector in any language, a
reviewer, and the contract-conformance / principle-review agents can read and
**diff** it. This module emits one combined JSON Schema document (a shared
`$defs` block) covering every public entity.

The committed golden — `contract.schema.json` — is the reviewable artifact:
any change to a public model surfaces as a JSON diff in the PR (our
`tfplugin5.proto` equivalent), and `tests/test_contract_schema.py` fails if the
code and the golden drift. Regenerate it *intentionally* when you mean to change
the contract:

    python -m sq_schema.json_schema --write     # rewrite the golden
    python -m sq_schema.json_schema             # print to stdout (CI diff)

The public-model set is DERIVED from `sq_schema.__all__` (every exported pydantic
model), so adding a model to the public surface automatically adds it to the
contract artifact — no second list to keep in sync.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

import sq_schema as _S
from . import __version__

GOLDEN = Path(__file__).resolve().parent / "contract.schema.json"


def _public_models() -> list[type[BaseModel]]:
    """Every pydantic model in the package's public surface (`__all__`),
    name-sorted for a deterministic, diff-stable artifact. Enums, Protocols
    (the `*Provider`s) and the `conformance` module are not models, so they
    fall out naturally."""
    models = []
    for name in _S.__all__:
        obj = getattr(_S, name)
        if isinstance(obj, type) and issubclass(obj, BaseModel):
            models.append(obj)
    return sorted(models, key=lambda m: m.__name__)


def contract_json_schema() -> dict:
    """The whole canonical contract as one JSON Schema document.

    Deterministic for a given (pydantic version, model set, contract version):
    the same inputs always produce byte-identical output, which is what makes
    the golden-file drift test meaningful. The contract's own semver is stamped
    in so the artifact self-describes."""
    _map, top = models_json_schema(
        [(m, "validation") for m in _public_models()],
        ref_template="#/$defs/{model}",
        title="sciqnt canonical contract",
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "x-sciqnt-contract-version": __version__,
        **top,
    }


def _serialize(doc: dict) -> str:
    """Canonical on-disk form: sorted keys + trailing newline, so the golden
    is stable across machines and the diff is minimal."""
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def write_golden() -> Path:
    GOLDEN.write_text(_serialize(contract_json_schema()))
    return GOLDEN


if __name__ == "__main__":
    import sys

    if "--write" in sys.argv[1:]:
        path = write_golden()
        print(f"wrote {path} (contract v{__version__})")
    else:
        sys.stdout.write(_serialize(contract_json_schema()))
