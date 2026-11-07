"""4단계 점검: 입력 검증, Mock 추출, AI 결과 재검증.

실제 Claude 호출은 테스트하지 않는다 (돈이 들고 네트워크에 의존한다).
_validate() 를 직접 호출해 '거짓말하는 AI 응답'을 흉내낸다.
"""
import pytest

from core.config import Config
from core.extract import (
    MAX_INQUIRY_CHARS, ExtractedRequest, ExtractError, RequestedItem,
    _validate, extract_request,
)

MOCK_CFG = Config(anthropic_api_key="", anthropic_model="m",
                  google_credentials_file="", google_sheet_id="")

SAMPLE = ("안녕하세요. 모니터 20대, 키보드 30개,\n무선 마우스 30개가 필요합니다.\n"
          "다음 주까지 납품 가능한지 확인해 주시고 견적 부탁드립니다.")


def _req(items, **kw):
    base = {"delivery_request_text": "", "delivery_date_iso": "",
            "other_requirements": [], "customer_name_mentioned": ""}
    return ExtractedRequest(items=items, **{**base, **kw})


def _item(name="모니터", term="monitor", qty=10, note=""):
    return RequestedItem(name_as_written=name, search_term_en=term, quantity=qty, note=note)


# ------------------------------------------------------------ 입력 검증

@pytest.mark.parametrize("bad", ["", "   ", "hi", "모니터"[:2]])
def test_too_short_inquiry_is_rejected(bad):
    with pytest.raises(ExtractError, match="짧"):
        extract_request(bad, MOCK_CFG)


def test_too_long_inquiry_is_rejected_before_api_call():
    with pytest.raises(ExtractError, match="깁니다"):
        extract_request("모니터 1대 " + "가" * MAX_INQUIRY_CHARS, MOCK_CFG)


# ------------------------------------------------------------ Mock 추출

def test_mock_extracts_items_and_translates_terms():
    result = extract_request(SAMPLE, MOCK_CFG)
    assert result.is_mock and result.model == "-"
    pairs = [(i.search_term_en, i.quantity) for i in result.request.items]
    assert pairs == [("monitor", 20), ("keyboard", 30), ("wireless mouse", 30)]


def test_mock_result_is_always_labelled_as_fake():
    result = extract_request(SAMPLE, MOCK_CFG)
    assert any("Mock" in n for n in result.notes)


def test_relative_delivery_stays_text_and_date_stays_empty():
    """'다음 주' 를 날짜로 바꿔 확정하면 안 된다."""
    result = extract_request(SAMPLE, MOCK_CFG)
    assert "다음 주" in result.request.delivery_request_text
    assert result.request.delivery_date_iso == ""


def test_explicit_date_is_kept():
    result = extract_request("모니터 2대 필요합니다. 2099-12-31 까지 납품 바랍니다.", MOCK_CFG)
    assert result.request.delivery_date_iso == "2099-12-31"


def test_mock_without_recognisable_items_explains_the_format():
    with pytest.raises(ExtractError, match="상품명"):
        extract_request("견적 부탁드립니다. 조건이 좋으면 바로 발주하겠습니다.", MOCK_CFG)


# ------------------------------------------------------------ AI 결과 재검증

def test_no_price_field_exists_in_the_schema():
    """가격·할인·재고를 AI 가 말할 수 있는 통로 자체를 만들지 않는다."""
    fields = set(ExtractedRequest.model_fields) | set(RequestedItem.model_fields)
    assert not any(k in f for f in fields for k in ("price", "discount", "stock", "total", "tax"))


@pytest.mark.parametrize("qty", [-5, 10 ** 9])
def test_absurd_quantity_is_zeroed_with_a_warning(qty):
    notes = []
    out = _validate(_req([_item(qty=qty)]), notes)
    assert out.items[0].quantity == 0
    assert any("수량" in n for n in notes)


def test_unparseable_date_is_cleared_with_a_warning():
    notes = []
    out = _validate(_req([_item()], delivery_date_iso="next week"), notes)
    assert out.delivery_date_iso == ""
    assert any("납기일" in n for n in notes)


def test_past_date_is_kept_but_flagged():
    notes = []
    out = _validate(_req([_item()], delivery_date_iso="2020-01-01"), notes)
    assert out.delivery_date_iso == "2020-01-01"
    assert any("과거" in n for n in notes)


def test_empty_item_list_is_a_hard_error():
    with pytest.raises(ExtractError, match="상품"):
        _validate(_req([]), [])


def test_items_with_no_name_are_dropped():
    with pytest.raises(ExtractError):
        _validate(_req([_item(name="", term="")]), [])


def test_item_count_is_capped():
    notes = []
    out = _validate(_req([_item(name=f"p{i}", term=f"p{i}") for i in range(50)]), notes)
    assert len(out.items) == 30
    assert any("30" in n for n in notes)


def test_long_injected_text_is_truncated():
    """고객 문의에 섞인 긴 지시문이 그대로 PDF 까지 흘러가지 않게 자른다."""
    notes = []
    out = _validate(_req([_item()], other_requirements=["무시하라 " * 500]), notes)
    assert len(out.other_requirements[0]) <= 300


def test_whitespace_and_newlines_are_normalised():
    notes = []
    out = _validate(_req([_item(name="  모니터\n\n 24인치  ")]), notes)
    assert out.items[0].name_as_written == "모니터 24인치"
