"""PortfolioSnapshot — what a connector returns from a single `live` call.

Cross-entity referential-integrity checks live here (each Position's
account/instrument FK resolves; each CashBalance's account FK resolves).
The connector is responsible for filling these correctly; the snapshot
just refuses to construct if they don't line up.
"""
from pydantic import model_validator

from .account import Account
from .bitemporal import Bitemporal
from .cash import CashBalance
from .instrument import Instrument
from .position import Position


class PortfolioSnapshot(Bitemporal):
    account: Account
    instruments: list[Instrument]
    positions: list[Position]
    cash_balances: list[CashBalance]

    @model_validator(mode="after")
    def _check_fks(self) -> "PortfolioSnapshot":
        acct_id = self.account.account_id
        known_instruments = {i.instrument_id for i in self.instruments}

        for p in self.positions:
            if p.account_id != acct_id:
                raise ValueError(
                    f"Position.account_id={p.account_id!r} does not match "
                    f"Account.account_id={acct_id!r}"
                )
            if p.instrument_id not in known_instruments:
                raise ValueError(
                    f"Position.instrument_id={p.instrument_id!r} "
                    "not present in snapshot.instruments"
                )

        for c in self.cash_balances:
            if c.account_id != acct_id:
                raise ValueError(
                    f"CashBalance.account_id={c.account_id!r} does not match "
                    f"Account.account_id={acct_id!r}"
                )
        return self
