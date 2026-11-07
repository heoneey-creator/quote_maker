"""6단계 점검: 금액 계산. 틀리면 회사가 돈을 잃는 코드이므로 가장 촘촘하게 본다."""
from datetime import date
from decimal import Decimal

import pytest

from core.config import Config
from core.extract import RequestedItem
from core.matching import MATCHED, Candidate, MatchedLine, match_line
from core.pricing import (
    Customer, PricingError, build_quote, customer_from_catalog, format_money,
    new_quote_number, override_quantity, round_money,
)
from core.sheets import load_catalog

CSV_ONLY = Config(anthropic_api_key="", anthropic_model="m",
                  google_credentials_file="", google_sheet_id="")
TODAY = date(2026, 1, 15)


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(CSV_ONLY)


def _line(price, qty, stock=10 ** 6, pid="P001", name="Test Item"):
    item = RequestedItem(name_as_written=name, search_term_en=name, quantity=qty, note="")
    cand = Candidate(product_id=pid, product_name=name, category="X",
                     unit_price=Decimal(str(price)), stock_quantity=stock, score=1.0)
    return MatchedLine(item, MATCHED, [cand], pid, [])


def _customer(rate="0.00"):
    return Customer(customer_id="C001", company_name="Test Co", contact_name="A",
                    email="a@b.com", customer_tier="GOLD", discount_rate=Decimal(rate))


# ------------------------------------------------------------ 계산 정확성

def test_subtotal_is_exact(catalog):
    q = build_quote([_line(7250000, 20), _line(290000, 30, pid="P2", name="B")],
                    _customer(), catalog, today=TODAY)
    assert q.subtotal == Decimal("153700000")


def test_discount_applies_before_tax(catalog):
    """소계 1,000,000 / 할인 10% / 세율 10%
    올바름: (1,000,000 - 100,000) * 1.10 = 990,000
    틀림  : 1,000,000 * 1.10 - 100,000 = 1,000,000"""
    q = build_quote([_line(1000000, 1)], _customer("0.10"), catalog, today=TODAY)
    assert q.discount_amount == Decimal("100000")
    assert q.taxable == Decimal("900000")
    assert q.tax_amount == Decimal("90000")
    assert q.total == Decimal("990000")


def test_totals_are_internally_consistent(catalog):
    q = build_quote([_line(4590000, 7), _line(78000, 13, pid="P2", name="B")],
                    _customer("0.03"), catalog, today=TODAY)
    assert sum(l.line_total for l in q.lines) == q.subtotal
    assert q.taxable == q.subtotal - q.discount_amount
    assert q.total == q.taxable + q.tax_amount


def test_vnd_amounts_are_whole_numbers(catalog):
    """VND 는 보조 단위가 없다. 0.5 동이 적힌 견적서는 나가면 안 된다."""
    q = build_quote([_line(333333, 7)], _customer("0.07"), catalog, today=TODAY)
    for value in (q.subtotal, q.discount_amount, q.taxable, q.tax_amount, q.total):
        assert value == value.to_integral_value(), value
    for line in q.lines:
        assert line.line_total == line.line_total.to_integral_value()


def test_no_float_rounding_drift(catalog):
    """float 로 계산하면 1원씩 어긋나는 금액들."""
    q = build_quote([_line("0.1", 3)], _customer(), catalog, today=TODAY)
    assert q.lines[0].line_total == Decimal("0")  # 0.3 VND -> 0 으로 반올림
    big = build_quote([_line(1234567, 89)], _customer("0.13"), catalog, today=TODAY)
    assert big.subtotal == Decimal("109876463")
    assert big.discount_amount == Decimal("14283940")  # 14,283,940.19 -> 반올림


@pytest.mark.parametrize("amount,expected", [
    ("0.4", "0"), ("0.5", "1"), ("1.5", "2"), ("2.5", "3"), ("-0.5", "-1"),
])
def test_round_money_is_half_up_not_bankers(amount, expected):
    """파이썬 기본 반올림은 2.5 -> 2 (은행가 반올림). 돈에는 쓰지 않는다."""
    assert round_money(Decimal(amount), "VND") == Decimal(expected)


def test_non_vnd_currency_keeps_two_decimals():
    assert round_money(Decimal("1.005"), "USD") == Decimal("1.01")
    assert format_money(Decimal("1.5"), "USD") == "1.50 USD"
    assert format_money(Decimal("1500000"), "VND") == "1,500,000 VND"


# ------------------------------------------------------------ 잘못된 입력

@pytest.mark.parametrize("qty", [0, -1])
def test_bad_quantity_stops_the_calculation(catalog, qty):
    with pytest.raises(PricingError, match="수량"):
        build_quote([_line(1000, qty)], _customer(), catalog, today=TODAY)


def test_non_integer_quantity_is_rejected(catalog):
    line = _line(1000, 10)
    line.requested.quantity = 2.5
    with pytest.raises(PricingError, match="정수"):
        build_quote([line], _customer(), catalog, today=TODAY)


def test_zero_unit_price_stops_the_calculation(catalog):
    with pytest.raises(PricingError, match="단가"):
        build_quote([_line(0, 5)], _customer(), catalog, today=TODAY)


@pytest.mark.parametrize("rate", ["-0.01", "0.95", "5"])
def test_discount_out_of_range_is_rejected(catalog, rate):
    with pytest.raises(PricingError, match="할인율"):
        build_quote([_line(1000, 1)], _customer(), catalog,
                    discount_rate=Decimal(rate), today=TODAY)


def test_bad_tax_rate_is_rejected(catalog):
    broken = load_catalog(CSV_ONLY)
    broken.settings["tax_rate"] = "1.5"
    with pytest.raises(Exception):  # DataError(상한) 또는 PricingError
        build_quote([_line(1000, 1)], _customer(), broken, today=TODAY)


@pytest.mark.parametrize("days", [0, 400])
def test_bad_validity_period_is_rejected(catalog, days):
    with pytest.raises(PricingError, match="유효기간"):
        build_quote([_line(1000, 1)], _customer(), catalog,
                    valid_days=days, today=TODAY)


def test_empty_quote_is_rejected(catalog):
    with pytest.raises(PricingError, match="넣을 수 있는 상품이 없"):
        build_quote([], _customer(), catalog, today=TODAY)


# ------------------------------------------------------------ 누락 방지

def test_unresolved_lines_are_carried_not_silently_dropped(catalog):
    """금액에 못 들어간 상품이 조용히 사라지면 견적서에서 누락이 안 보인다."""
    missing = match_line(RequestedItem(name_as_written="드론", search_term_en="drone",
                                       quantity=2, note=""), catalog.products)
    q = build_quote([_line(1000, 1), missing], _customer(), catalog, today=TODAY)
    assert len(q.lines) == 1
    assert len(q.unresolved) == 1
    assert q.has_warnings
    assert any("드론" in w and "포함되지 않" in w for w in q.warnings)


def test_stock_shortage_appears_in_warnings(catalog):
    q = build_quote([_line(1000, 20, stock=5, name="Short Item")],
                    _customer(), catalog, today=TODAY)
    assert q.short_lines and q.short_lines[0].stock.shortage == 15
    assert any("15개 재고 부족" in w for w in q.warnings)


def test_mock_data_is_always_disclosed(catalog):
    q = build_quote([_line(1000, 1)], _customer(), catalog, today=TODAY)
    assert q.is_mock_data
    assert any("가상" in w for w in q.warnings)


# ------------------------------------------------------------ 기타

def test_validity_date_comes_from_settings(catalog):
    q = build_quote([_line(1000, 1)], _customer(), catalog, today=TODAY)
    assert q.issue_date == TODAY
    assert q.valid_until == date(2026, 1, 29)  # settings.csv: 14일


def test_quote_number_has_the_issue_date(catalog):
    assert new_quote_number(TODAY).startswith("QT-20260115-")


def test_customer_lookup_rejects_unknown_id(catalog):
    with pytest.raises(PricingError, match="없는 ID"):
        customer_from_catalog(catalog, "C999")


def test_customer_tier_discount_is_used_by_default(catalog):
    cust = customer_from_catalog(catalog, "C004")  # PLATINUM 8%
    q = build_quote([_line(1000000, 1)], cust, catalog, today=TODAY)
    assert q.discount_rate == Decimal("0.08")
    assert q.discount_amount == Decimal("80000")


def test_manual_discount_overrides_the_tier(catalog):
    cust = customer_from_catalog(catalog, "C004")
    q = build_quote([_line(1000000, 1)], cust, catalog,
                    discount_rate=Decimal("0.20"), today=TODAY)
    assert q.discount_amount == Decimal("200000")


def test_quantity_override_recalculates(catalog):
    line = override_quantity(_line(1000, 5), 12)
    q = build_quote([line], _customer(), catalog, today=TODAY)
    assert q.lines[0].quantity == 12 and q.subtotal == Decimal("12000")


@pytest.mark.parametrize("bad", [0, -3, 2.5, True])
def test_quantity_override_validates(bad):
    with pytest.raises(PricingError):
        override_quantity(_line(1000, 5), bad)
