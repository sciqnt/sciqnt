#!/usr/bin/env python3
"""Regenerate the OPTIONAL connector discovery catalog `connectors-index.json`.

First-party entries (repo == "sciqnt/sciqnt") are DERIVED from each bundle's
manifest.yaml — run this after adding/changing a first-party connector so the
catalog can't rot. Community entries (any other repo) are HAND-ADDED by PR and
are PRESERVED across regeneration (merged back in).

The index is a discovery aid, not a registry: `sciqnt modules add owner/repo`
works without it (sovereignty / registry-optional).

    python3 scripts/build_connector_index.py
"""
import json
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
INDEX = ROOT / "connectors-index.json"
NOTE = (
    "OPTIONAL discovery catalog — humans via `sciqnt modules find`, agents via "
    "llms.txt. The registry is OPTIONAL (sovereignty): `sciqnt modules add "
    "owner/repo` works WITHOUT this file. Community (Zone 2) connectors live in "
    "their authors' own repos and are added here by PR — see "
    "research/connector-publishing.md. First-party entries are generated from "
    "each bundle's manifest.yaml (scripts/build_connector_index.py)."
)


def _first_party():
    out = []
    for mf in sorted(ROOT.glob("modules/sq-*/manifest.yaml")):
        m = yaml.safe_load(mf.read_text()) or {}
        flavours = m.get("flavours") or {}
        risks = [(f or {}).get("risk") for f in flavours.values()
                 if isinstance(f, dict)]
        prov = ("reverse-engineered" if "reverse-engineered" in risks
                else "official" if "official" in risks else "n/a")
        out.append({
            "name": m.get("name", mf.parent.name),
            "broker": m.get("broker", ""),
            "kind": m.get("kind", ""),
            "repo": "sciqnt/sciqnt",
            "zone": "official",
            "endorsed": bool(m.get("endorsed", True)),
            "risk_tier": m.get("risk_tier", "read"),
            "provenance": prov,
            "asset_classes": m.get("asset_classes") or [],
            "status": m.get("status", ""),
            "capabilities": (m.get("capabilities") or {}).get("read") or [],
        })
    return out


def main():
    community = []
    if INDEX.is_file():
        try:
            community = [e for e in json.loads(INDEX.read_text()).get("connectors", [])
                         if e.get("repo") != "sciqnt/sciqnt"]
        except (ValueError, OSError):
            pass
    connectors = sorted(_first_party() + community, key=lambda e: e["name"])
    INDEX.write_text(json.dumps(
        {"schema": "sciqnt.connector-index/v1", "note": NOTE,
         "connectors": connectors}, indent=2) + "\n")
    fp = sum(1 for e in connectors if e["repo"] == "sciqnt/sciqnt")
    print(f"wrote {INDEX.name}: {fp} first-party + {len(community)} community")


if __name__ == "__main__":
    main()
