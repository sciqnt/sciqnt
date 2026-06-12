"""Parse ECB XML → {date: {ccy: Decimal}}.

Fixture XML mirrors the real ECB schema exactly (namespaces, attribute names).
If ECB changes its format, these tests catch it the moment we re-download a
fixture file.
"""
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "modules" / "sq-fx-ecb" / "src"))

from sq_fx_ecb.parser import parse_ecb_xml          # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


class TestParseEcbDaily(unittest.TestCase):
    def setUp(self):
        self.parsed = parse_ecb_xml((FIXTURES / "ecb_daily.xml").read_bytes())

    def test_one_date_in_daily(self):
        self.assertEqual(set(self.parsed.keys()), {date(2026, 5, 30)})

    def test_rates_are_decimal_typed(self):
        for ccy, rate in self.parsed[date(2026, 5, 30)].items():
            self.assertIsInstance(rate, Decimal,
                                  f"{ccy} rate must be Decimal (no float pollution)")

    def test_rate_values_match_fixture(self):
        rates = self.parsed[date(2026, 5, 30)]
        self.assertEqual(rates["USD"], Decimal("1.1652"))
        self.assertEqual(rates["GBP"], Decimal("0.8425"))
        self.assertEqual(rates["JPY"], Decimal("180.45"))


class TestParseEcbHistory(unittest.TestCase):
    def setUp(self):
        self.parsed = parse_ecb_xml((FIXTURES / "ecb_hist90d.xml").read_bytes())

    def test_multiple_dates(self):
        self.assertEqual(
            sorted(self.parsed.keys()),
            [date(2026, 5, 15), date(2026, 5, 29), date(2026, 5, 30)],
        )

    def test_historical_rate_lookup(self):
        self.assertEqual(self.parsed[date(2026, 5, 15)]["USD"], Decimal("1.0950"))


class TestParserDefensive(unittest.TestCase):
    def test_malformed_xml_returns_empty(self):
        self.assertEqual(parse_ecb_xml(b"<not-valid-xml"), {})

    def test_empty_xml_returns_empty(self):
        self.assertEqual(parse_ecb_xml(b""), {})

    def test_skips_cube_with_missing_attrs(self):
        # Date present but no currency cubes inside — should be omitted entirely
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-05-30"></Cube>
  </Cube>
</gesmes:Envelope>"""
        self.assertEqual(parse_ecb_xml(xml), {})


if __name__ == "__main__":
    unittest.main()
