"""Parse ECB EUR-cross daily reference rates from XML.

Format (stable since 1999):
  <gesmes:Envelope xmlns:gesmes="..." xmlns="http://www.ecb.int/.../eurofxref">
    <Cube>
      <Cube time="YYYY-MM-DD">
        <Cube currency="USD" rate="1.1652"/>
        <Cube currency="GBP" rate="0.8425"/>
        ...
      </Cube>
      <!-- 90d/history files repeat the inner Cube[time] for each date -->
    </Cube>
  </gesmes:Envelope>

Semantics: 1 EUR = `rate` units of `currency`.
"""
from datetime import date
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

# Outer envelope uses gesmes:; the inner Cube elements live in the eurofxref
# default namespace. ElementTree exposes both as `{namespace}tag`.
ECB_NS = "{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}"


def parse_ecb_xml(xml_bytes: bytes) -> dict[date, dict[str, Decimal]]:
    """Parse ECB XML into `{date: {currency: rate_eur_to_ccy}}`.

    Rate semantics: `1 EUR = rate units of currency`. Caller triangulates
    for non-EUR pairs. Malformed cubes (missing attrs, bad date, unparseable
    rate) are silently skipped — defensive against a future schema tweak."""
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        return {}

    out: dict[date, dict[str, Decimal]] = {}
    # Every Cube element with a `time` attribute is a date-grouping cube;
    # its direct children are per-currency rate cubes.
    for date_cube in root.iter(f"{ECB_NS}Cube"):
        time_str = date_cube.get("time")
        if not time_str:
            continue
        try:
            d = date.fromisoformat(time_str)
        except ValueError:
            continue
        rates: dict[str, Decimal] = {}
        for ccy_cube in date_cube.findall(f"{ECB_NS}Cube"):
            ccy  = ccy_cube.get("currency")
            rate = ccy_cube.get("rate")
            if not (ccy and rate):
                continue
            try:
                rates[ccy] = Decimal(rate)
            except (InvalidOperation, ValueError):
                continue
        if rates:
            out[d] = rates
    return out
