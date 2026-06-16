# Changelog — sciqnt-schema (the canonical contract)

The contract is the hub every connector and consumer pins. It follows semver:
a **breaking** change to any public model (a removed/renamed field, a tightened
type, a changed meaning) is a MAJOR bump; an additive optional field is MINOR.
The committed `contract.schema.json` is the language-agnostic artifact — every
release's diff is visible there.

## 0.1.0 — contract stabilized (Phase 0)

First release with a **committed public-API contract**, in preparation for the
component-world split (the package graduates to `sciqnt/sq-schema`).

- **JSON-Schema artifact.** `sq_schema.contract_json_schema()` + the committed
  golden `contract.schema.json` make the contract inspectable and diffable
  without Python (our `tfplugin5.proto` equivalent). `test_contract_schema.py`
  fails CI if code and golden drift. Regenerate: `python -m sq_schema.json_schema --write`.
- **Single-source version.** `sq_schema.__version__` is the one source; the
  package version is read from it (`pyproject` `dynamic = ["version"]`).
- **Determinism bound.** The golden is reproducible only against a stable
  JSON-Schema generator, so `pydantic` is pinned `>=2.5,<3`. A pydantic MAJOR
  bump may change the serialization and require regenerating the golden (the
  drift test prints the exact command); that is a deliberate, reviewed step.
- **Public surface frozen for downstreams** (`__all__`): `Account`, `Instrument`,
  `Position`, `CashBalance`, `ClosedLot`, `FxRate`, `NewsItem`, `Price`,
  `Transaction`, `PortfolioSnapshot`, the `AssetClass`/`TransactionType` enums,
  the `*Provider` protocols, `Bitemporal`, and `conformance`. Connectors import
  ONLY from this top level (enforced by `test_connector_decoupling.py`).

No behavioural change to the models themselves vs 0.0.x — this release makes the
contract *explicit and enforced*, not different.
