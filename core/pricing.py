"""견적 금액 계산. 모든 숫자는 여기서만 만들어진다 — Claude 는 관여하지 않는다.

계산 순서 (바꾸면 금액이 달라지므로 고정):
  1. 줄 합계   = 단가 x 수량            (통화 단위로 반올림)
  2. 소계      = 줄 합계의 합
  3. 할인      = 소계 x 할인율          (통화 단위로 반올림)
  4. 과세대상  = 소계 - 할인
  5. 세금      = 과세대상 x 세율        (통화 단위로 반올림)
  6. 총액      = 과세대상 + 세금

float 을 쓰지 않는다. 0.1 + 0.2 != 0.3 인 세계에서 돈을 세면 안 된다.
VND 는 보조 단위가 없으므로 정수로 반올림한다 (ROUND_HALF_UP).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

from core.matching import (
    AMBIGUOUS, DISCONTINUED, MATCHED, NOT_FOUND, MatchedLine, StockCheck,
    check_stock,
)
from core.sheets import Catalog

MAX_DISCOUNT = Decimal("0.90")
MAX_QUANTITY = 1_000_000

# 베트남은 연중 UTC+7 고정이고 일광절약시간을 쓰지 않는다.
# ZoneInfo 를 쓰면 Windows 에서 tzdata 패키지가 추가로 필요하므로 고정 오프셋을 쓴다.
VN_TZ = timezone(timedelta(hours=7))

# 보조 단위가 없는 통화. 그 외는 소수 2자리.
ZERO_DECIMAL_CURRENCIES = {"VND", "JPY", "KRW"}


class PricingError(Exception):
    """계산을 계속하면 틀린 금액이 나오는 경우. 반드시 사용자에게 보여준다."""


def _step(currency: str) -> Decimal:
    return Decimal("1") if currency.upper() in ZERO_DECIMAL_CURRENCIES else Decimal("0.01")


def round_money(amount: Decimal, currency: str) -> Decimal:
    return Decimal(amount).quantize(_step(currency), rounding=ROUND_HALF_UP)


def format_money(amount: Decimal, currency: str = "VND") -> str:
    if currency.upper() in ZERO_DECIMAL_CURRENCIES:
        return f"{int(amount):,} {currency}"
    return f"{amount:,.2f} {currency}"


@dataclass(frozen=True)
class Customer:
    customer_id: str
    company_name: str
    contact_name: str
    email: str
    customer_tier: str
    discount_rate: Decimal

    @classmethod
    def from_row(cls, row) -> "Customer":
        return cls(customer_id=str(row["customer_id"]), company_name=str(row["company_name"]),
                   contact_name=str(row["contact_name"]), email=str(row["email"]),
                   customer_tier=str(row["customer_tier"]),
                   discount_rate=Decimal(str(row["discount_rate"])))


@dataclass(frozen=True)
class QuoteLine:
    product_id: str
    product_name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    stock: StockCheck


@dataclass
class Quote:
    number: str
    issue_date: date
    valid_until: date
    customer: Customer
    currency: str
    lines: list
    subtotal: Decimal
    discount_rate: Decimal
    discount_amount: Decimal
    taxable: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    total: Decimal
    unresolved: list = field(default_factory=list)
    delivery_note: str = ""
    remarks: str = ""
    warnings: list = field(default_factory=list)
    is_mock_data: bool = False

    @property
    def short_lines(self) -> list:
        return [l for l in self.lines if l.stock.status == "short"]

    @property
    def has_warnings(self) -> bool:
        return bool(self.short_lines or self.unresolved)


def new_quote_number(today: date | None = None) -> str:
    """데모용 견적번호. 2단계에서 DB 시퀀스로 바꾼다.

    shortcut: 난수 4자리라 중복 가능 — DB 도입 시 유일 시퀀스로 교체.
    """
    today = today or datetime.now(VN_TZ).date()
    return "QT-" + today.strftime("%Y%m%d") + "-" + f"{random.randint(0, 9999):04d}"


def _validate_line(line: MatchedLine) -> tuple:
    product = line.selected
    if product is None:
        raise PricingError("상품이 선택되지 않은 줄이 있습니다.")
    qty = line.requested.quantity
    if not isinstance(qty, int) or isinstance(qty, bool):
        raise PricingError(f"'{product.product_name}' 의 수량이 정수가 아닙니다: {qty!r}")
    if qty <= 0:
        raise PricingError(f"'{product.product_name}' 의 수량이 0 이하입니다 ({qty}). "
                           "수량을 입력한 뒤 다시 계산하세요.")
    if qty > MAX_QUANTITY:
        raise PricingError(f"'{product.product_name}' 의 수량이 너무 큽니다 ({qty:,}).")
    if product.unit_price <= 0:
        raise PricingError(f"'{product.product_name}' 의 단가가 0 이하입니다 "
                           f"({product.unit_price}). 시트의 unit_price 를 확인하세요.")
    return product, qty


def build_quote(lines: list, customer: Customer, catalog: Catalog,
                discount_rate: Decimal | None = None,
                valid_days: int | None = None,
                delivery_note: str = "", remarks: str = "",
                quote_number: str = "", today: date | None = None) -> Quote:
    """확정된 줄만 금액을 계산하고, 미확정 줄은 '확인 필요' 로 따로 들고 간다.

    미확정 줄을 조용히 버리면 견적서에서 누락이 보이지 않는다. 그래서 버리지 않는다.
    """
    currency = catalog.currency
    tax_rate = catalog.tax_rate
    rate = customer.discount_rate if discount_rate is None else Decimal(str(discount_rate))
    if not 0 <= rate <= MAX_DISCOUNT:
        raise PricingError(f"할인율이 0~{MAX_DISCOUNT} 범위를 벗어났습니다: {rate}")
    if not 0 <= tax_rate < 1:
        raise PricingError(f"세율이 0~1 범위를 벗어났습니다: {tax_rate}")

    priced, unresolved, warnings = [], [], []
    for line in lines:
        if line.status != MATCHED or line.selected is None:
            unresolved.append(line)
            continue
        product, qty = _validate_line(line)
        priced.append(QuoteLine(
            product_id=product.product_id, product_name=product.product_name,
            quantity=qty, unit_price=round_money(product.unit_price, currency),
            line_total=round_money(product.unit_price * qty, currency),
            stock=check_stock(line)))

    if not priced:
        raise PricingError("견적에 넣을 수 있는 상품이 없습니다. "
                           "상품을 선택하거나 수량을 입력하세요.")

    subtotal = round_money(sum((l.line_total for l in priced), Decimal(0)), currency)
    discount_amount = round_money(subtotal * rate, currency)
    taxable = subtotal - discount_amount
    tax_amount = round_money(taxable * tax_rate, currency)
    total = taxable + tax_amount

    for line in priced:
        if line.stock.status == "short":
            warnings.append(f"{line.product_name}: 주문 {line.stock.ordered:,}개 중 "
                            f"{line.stock.shortage:,}개 재고 부족 "
                            f"(현재 재고 {line.stock.available:,}개)")
    for line in unresolved:
        label = {NOT_FOUND: "카탈로그에 없음", AMBIGUOUS: "상품 미선택",
                 DISCONTINUED: "단종 상품"}.get(line.status, "확인 필요")
        warnings.append(f"{line.requested.name_as_written}: {label} — 견적 금액에 "
                        "포함되지 않았습니다")
    if catalog.is_mock_data:
        warnings.append("상품·가격 데이터가 가상(CSV) 데이터입니다.")

    issued = today or datetime.now(VN_TZ).date()
    days = catalog.valid_days if valid_days is None else int(valid_days)
    if not 1 <= days <= 365:
        raise PricingError(f"견적 유효기간이 1~365일 범위를 벗어났습니다: {days}")

    return Quote(
        number=quote_number or new_quote_number(issued),
        issue_date=issued, valid_until=issued + timedelta(days=days),
        customer=customer, currency=currency, lines=priced,
        subtotal=subtotal, discount_rate=rate, discount_amount=discount_amount,
        taxable=taxable, tax_rate=tax_rate, tax_amount=tax_amount, total=total,
        unresolved=unresolved, delivery_note=delivery_note, remarks=remarks,
        warnings=warnings, is_mock_data=catalog.is_mock_data)


def customer_from_catalog(catalog: Catalog, customer_id: str) -> Customer:
    row = catalog.customers[catalog.customers["customer_id"].astype(str) == str(customer_id)]
    if row.empty:
        raise PricingError("고객 목록에 없는 ID 입니다: " + str(customer_id))
    return Customer.from_row(row.iloc[0])


def override_quantity(line: MatchedLine, quantity: int) -> MatchedLine:
    """검토 화면에서 수량을 바꿀 때. 상품은 그대로 두고 수량만 교체한다."""
    if not isinstance(quantity, int) or isinstance(quantity, bool):
        raise PricingError(f"수량은 정수여야 합니다: {quantity!r}")
    if not 0 < quantity <= MAX_QUANTITY:
        raise PricingError(f"수량은 1 ~ {MAX_QUANTITY:,} 사이여야 합니다: {quantity}")
    item = line.requested.model_copy(update={"quantity": quantity})
    return MatchedLine(item, line.status, line.candidates,
                       line.selected_product_id, line.notes)


def quote_rows(quote: Quote) -> pd.DataFrame:
    """UI 표·PDF 용 공통 표. 금액은 이미 계산된 값을 쓴다."""
    return pd.DataFrame([{
        "상품ID": l.product_id, "상품명": l.product_name,
        "수량": l.quantity,
        "단가": format_money(l.unit_price, quote.currency),
        "금액": format_money(l.line_total, quote.currency),
        "재고": l.stock.label,
        # 열 전체를 문자열로 둔다. int 와 "" 를 섞으면 표 직렬화가 실패한다.
        "부족수량": f"{l.stock.shortage:,}" if l.stock.shortage else "",
    } for l in quote.lines])
