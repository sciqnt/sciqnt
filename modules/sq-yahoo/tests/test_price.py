"""sq-yahoo conformance test — offline (network mocked)."""
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from sq_yahoo import fetch_quote  # noqa: E402


class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self, *a):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestFetchQuote(unittest.TestCase):
    def test_parses_price_and_currency(self):
        payload = {"chart": {"result": [{"meta": {
            "regularMarketPrice": 120.52, "currency": "USD",
            "fullExchangeName": "LSE"}}]}}
        with mock.patch("urllib.request.urlopen", return_value=_FakeResp(payload)):
            q = fetch_quote("IB01.L")
        self.assertEqual(q["ticker"], "IB01.L")
        self.assertEqual(q["price"], Decimal("120.52"))
        self.assertEqual(q["currency"], "USD")
        self.assertIsInstance(q["price"], Decimal)  # money is Decimal, never float


if __name__ == "__main__":
    unittest.main()
