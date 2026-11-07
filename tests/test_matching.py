"""5단계 점검: 상품 매칭, 애매한 경우, 없는 상품, 재고 판정."""
from decimal import Decimal

import pytest

from core.config import Config
from core.extract import RequestedItem
from core.matching import (
    AMBIGUOUS, DISCONTINUED, MATCHED, NOT_FOUND, STOCK_OK, STOCK_SHORT,
    STOCK_UNKNOWN, MatchError, check_stock, match_line, select_product,
)
from core.sheets import load_catalog

CSV_ONLY = Config(anthropic_api_key="", anthropic_model="m",
                  google_credentials_file="", google_sheet_id="")


@pytest.fixture(scope="module")
def products():
    return load_catalog(CSV_ONLY).products


def _item(term, qty=10, name=None):
    return RequestedItem(name_as_written=name or term, search_term_en=term,
                         quantity=qty, note="")


# ------------------------------------------------------------ 매칭 결과

def test_unique_product_is_matched_and_selected(products):
    line = match_line(_item("office chair"), products)
    assert line.status == MATCHED
    assert line.selected.product_id == "P016"
    assert line.selected.unit_price == Decimal("3250000")


def test_generic_word_gives_choices_instead_of_guessing(products):
    """'monitor' 는 여러 상품에 해당한다. 하나를 임의로 고르면 안 된다."""
    line = match_line(_item("monitor"), products)
    assert line.status == AMBIGUOUS
    assert line.selected_product_id == ""
    assert len(line.candidates) > 1
    assert line.needs_attention


def test_unknown_product_is_flagged_not_invented(products):
    line = match_line(_item("드론"), products)
    assert line.status == NOT_FOUND
    assert line.candidates == [] and line.selected is None


def test_inactive_product_is_reported_as_discontinued(products):
    """P022 Dell 22\" E2222H 는 active=FALSE."""
    line = match_line(_item("E2222H"), products)
    assert line.status == DISCONTINUED
    assert any("단종" in n for n in line.notes)
    assert line.selected_product_id == ""


def test_inactive_products_never_appear_as_selectable(products):
    """단종 상품은 '이건 단종입니다' 안내용으로만 등장하고,
    고를 수 있는 후보 목록에는 절대 들어가지 않는다."""
    for term in ("monitor", "Dell Monitor", "22 monitor", "E2222H"):
        line = match_line(_item(term), products)
        ids = [c.product_id for c in line.candidates]
        if line.status == DISCONTINUED:
            assert ids == ["P022"] and line.selected_product_id == ""
        else:
            assert "P022" not in ids, term


def test_korean_term_matches_english_catalog(products):
    """Mock 모드나 오역 대비 — 동의어 사전이 안전망으로 동작하는지."""
    line = match_line(_item("마우스"), products)
    assert line.candidates, "한국어 '마우스' 로도 후보가 나와야 한다"
    assert all("Mouse" in c.product_name or "mouse" in c.product_name.lower()
               or c.category == "Mouse" for c in line.candidates)


def test_typo_still_finds_candidate(products):
    line = match_line(_item("docking station"), products)
    assert "P019" in [c.product_id for c in line.candidates]


def test_zero_quantity_needs_attention(products):
    line = match_line(_item("office chair", qty=0), products)
    assert line.needs_attention
    assert any("수량" in n for n in line.notes)


# ------------------------------------------------------------ 사용자 선택

def test_user_can_pick_from_the_candidates(products):
    line = match_line(_item("monitor", qty=20), products)
    picked = select_product(line, "P001", products)
    assert picked.status == MATCHED
    assert picked.selected.product_id == "P001"
    assert not picked.needs_attention


def test_picking_an_unknown_id_is_rejected(products):
    line = match_line(_item("monitor"), products)
    with pytest.raises(MatchError, match="없는 상품 ID"):
        select_product(line, "P999", products)


def test_picking_a_discontinued_product_is_rejected(products):
    line = match_line(_item("monitor"), products)
    with pytest.raises(MatchError, match="단종"):
        select_product(line, "P022", products)


# ------------------------------------------------------------ 재고

def test_enough_stock_is_ok(products):
    line = select_product(match_line(_item("monitor", qty=10), products), "P001", products)
    stock = check_stock(line)
    assert stock.status == STOCK_OK and stock.shortage == 0


def test_short_stock_reports_the_exact_shortage(products):
    """P003 Samsung 32\" 재고 5개에 20개 주문 -> 15개 부족."""
    line = select_product(match_line(_item("monitor", qty=20), products), "P003", products)
    stock = check_stock(line)
    assert stock.status == STOCK_SHORT
    assert (stock.ordered, stock.available, stock.shortage) == (20, 5, 15)
    assert stock.label == "재고 부족"


def test_zero_stock_is_fully_short(products):
    line = select_product(match_line(_item("monitor arm", qty=3), products), "P021", products)
    stock = check_stock(line)
    assert stock.status == STOCK_SHORT and stock.shortage == 3


def test_unmatched_line_has_unknown_stock(products):
    stock = check_stock(match_line(_item("드론", qty=2), products))
    assert stock.status == STOCK_UNKNOWN and stock.label == "확인 필요"


def test_ambiguous_line_has_unknown_stock(products):
    """상품이 확정되지 않았으면 재고를 '정상' 이라고 말할 수 없다."""
    assert check_stock(match_line(_item("monitor", qty=1), products)).status == STOCK_UNKNOWN
