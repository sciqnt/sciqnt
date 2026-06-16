"""The contract's language-agnostic artifact must not drift from the code.

`core/sq_schema/contract.schema.json` is the reviewable, non-Python form of the
canonical contract (the thing a connector in another language, or a reviewer,
reads). It is GENERATED from the pydantic models. These tests make the golden a
hard invariant: if a public model changes and the golden wasn't regenerated, CI
fails with the exact fix command — so a contract change can never land silently.

Regenerate intentionally:  python -m sq_schema.json_schema --write
"""
import json
import sys
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CORE / "sq_schema"))   # import sq_schema standalone
sys.path.insert(0, str(CORE))

import sq_schema
from sq_schema.json_schema import GOLDEN, contract_json_schema, _serialize


class TestContractSchema(unittest.TestCase):

    def test_golden_matches_code(self):
        """The committed golden equals what the models currently emit."""
        self.assertTrue(GOLDEN.exists(), f"missing golden: {GOLDEN}")
        on_disk = GOLDEN.read_text()
        current = _serialize(contract_json_schema())
        self.assertEqual(
            on_disk, current,
            "contract.schema.json is STALE — a public model changed without "
            "regenerating the contract artifact. Run:\n"
            "    python -m sq_schema.json_schema --write\n"
            "and review the JSON diff as part of the PR (it IS the contract change).",
        )

    def test_version_stamp_tracks_package(self):
        """The artifact self-describes with the contract's semver."""
        doc = json.loads(GOLDEN.read_text())
        self.assertEqual(doc["x-sciqnt-contract-version"], sq_schema.__version__)

    def test_every_public_model_is_present(self):
        """Every exported pydantic model appears in the artifact's $defs — the
        contract surface and the export can't silently diverge."""
        from pydantic import BaseModel
        doc = json.loads(GOLDEN.read_text())
        defs = set(doc["$defs"].keys())
        for name in sq_schema.__all__:
            obj = getattr(sq_schema, name)
            if isinstance(obj, type) and issubclass(obj, BaseModel):
                self.assertIn(name, defs, f"{name} missing from the contract artifact")

    def test_is_well_formed_json_schema(self):
        """Minimal structural sanity: draft + $defs present, every $ref resolves."""
        doc = json.loads(GOLDEN.read_text())
        self.assertIn("$schema", doc)
        self.assertIn("$defs", doc)
        defs = doc["$defs"]
        blob = json.dumps(doc)
        # Every "#/$defs/X" reference points at a defined model.
        import re
        for ref in re.findall(r'"#/\$defs/([^"]+)"', blob):
            self.assertIn(ref, defs, f"dangling $ref to {ref}")


if __name__ == "__main__":
    unittest.main()
