"""sq-polymarket on-chain USDC read — pure-decode + fetch fallback (no network)."""
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-polymarket" / "src"))

from sq_polymarket import onchain                                    # noqa: E402


class TestDecodeBalance(unittest.TestCase):
    def test_zero_x_is_zero(self):
        self.assertEqual(onchain.decode_balance("0x"), Decimal("0"))

    def test_none_is_zero(self):
        self.assertEqual(onchain.decode_balance(None), Decimal("0"))

    def test_one_usdc_six_decimals(self):
        # 1_000_000 (6dp) = 1.0 USDC
        self.assertEqual(onchain.decode_balance(hex(1_000_000)), Decimal("1"))

    def test_realistic_balance(self):
        # 0.952956 USDC = 952956 raw
        self.assertEqual(onchain.decode_balance(hex(952956)), Decimal("0.952956"))

    def test_junk_is_zero(self):
        self.assertEqual(onchain.decode_balance("not-hex"), Decimal("0"))


class TestCalldata(unittest.TestCase):
    def test_balanceof_calldata_shape(self):
        # Obviously-synthetic address — fixtures never carry real wallets,
        # even public ones (conformance fixtures are SYNTHETIC by contract).
        cd = onchain._balanceof_calldata("0x00000000000000000000000000000000deadbeef")
        self.assertTrue(cd.startswith("0x70a08231"))
        # selector (10 chars incl 0x) + 64 hex chars of padded address
        self.assertEqual(len(cd), 10 + 64)
        self.assertTrue(cd.endswith("00000000000000000000000000000000deadbeef"))


class TestFetchFallback(unittest.TestCase):
    def test_sums_native_and_bridged(self):
        # Stub _eth_call: native=2 USDC, bridged=3 USDC → 5 total
        def fake_call(rpc, to, data):
            return hex(2_000_000) if to == onchain.USDC_NATIVE else hex(3_000_000)
        with mock.patch.object(onchain, "_eth_call", side_effect=fake_call):
            bal = onchain.fetch_usdc_balance("0xabc")
        self.assertEqual(bal, Decimal("5"))

    def test_all_rpcs_fail_returns_none(self):
        def boom(rpc, to, data):
            raise OSError("network down")
        with mock.patch.object(onchain, "_eth_call", side_effect=boom):
            self.assertIsNone(onchain.fetch_usdc_balance("0xabc"))

    def test_empty_address_returns_none(self):
        self.assertIsNone(onchain.fetch_usdc_balance(""))

    def test_falls_through_to_second_rpc(self):
        calls = []
        def flaky(rpc, to, data):
            calls.append(rpc)
            if rpc == onchain._DEFAULT_RPCS[0]:
                raise OSError("first rpc down")
            return hex(1_000_000)
        with mock.patch.object(onchain, "_eth_call", side_effect=flaky):
            bal = onchain.fetch_usdc_balance("0xabc")
        self.assertEqual(bal, Decimal("2"))     # 1 native + 1 bridged on 2nd rpc
        self.assertIn(onchain._DEFAULT_RPCS[1], calls)


if __name__ == "__main__":
    unittest.main()
