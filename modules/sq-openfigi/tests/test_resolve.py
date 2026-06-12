"""sq-openfigi conformance test — offline (network mocked)."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from sq_openfigi import resolve_isin, yahoo_candidates  # noqa: E402


class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self, *a):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


PAYLOAD = [{"data": [
    {"ticker": "IB01", "exchCode": "LN", "name": "iShares Tsy", "securityType": "ETP"},
    {"ticker": "IB01", "exchCode": "LN", "name": "iShares Tsy"},   # duplicate -> dedup
    {"ticker": "IB01", "exchCode": "GY", "name": "iShares Tsy"},   # Xetra -> .DE
    {"ticker": "ZZZ", "exchCode": "UNKNOWNXX", "name": "x"},        # unmapped -> yahoo None
]}]


class TestResolve(unittest.TestCase):
    def test_resolve_maps_exchanges(self):
        with mock.patch("urllib.request.urlopen", return_value=_FakeResp(PAYLOAD)):
            cands = resolve_isin("IE00BGSF1X88")
        yahoos = [c["yahoo"] for c in cands]
        self.assertIn("IB01.L", yahoos)
        self.assertIn("IB01.DE", yahoos)
        self.assertIn(None, yahoos)  # unmapped exchange

    def test_yahoo_candidates_prefer_dedup(self):
        with mock.patch("urllib.request.urlopen", return_value=_FakeResp(PAYLOAD)):
            out = yahoo_candidates("IE00BGSF1X88", prefer_suffix=".L")
        self.assertEqual(out[0], "IB01.L")          # preferred venue first
        self.assertEqual(len(out), len(set(out)))   # de-duped
        self.assertNotIn(None, out)                 # unmapped filtered out


if __name__ == "__main__":
    unittest.main()
