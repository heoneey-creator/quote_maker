"""7단계 점검: Streamlit UI 를 실제로 실행한다 (streamlit.testing.AppTest).

API 키와 시트 설정을 비워 CSV + Mock 모드로 돌린다. 네트워크도 돈도 쓰지 않는다.
"""
import os

import pytest
from streamlit.testing.v1 import AppTest

import core.config  # noqa: F401  (.env 로딩을 먼저 일으킨다)

PROJECT_ROOT = core.config.PROJECT_ROOT


@pytest.fixture(autouse=True)
def mock_mode(monkeypatch):
    """UI 테스트는 항상 가상 데이터 + Mock AI 로 돌린다."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("GOOGLE_SHEET_ID", "")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")


def _app():
    at = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    return at


def _goto(at, page):
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, at.exception
    return at


def _texts(elements):
    return " ".join(e.value for e in elements)


# ------------------------------------------------------------ 각 화면이 뜨는지

@pytest.mark.parametrize("page", ["Dashboard", "New Quotation", "Product Search",
                                  "Quotation Preview", "Settings / Connection"])
def test_every_page_renders_without_exception(page):
    at = _goto(_app(), page)
    assert len(at.header) == 1
    assert at.header[0].value.startswith(page.split(" /")[0])


def test_dashboard_reports_the_data_source_and_counts():
    at = _app()
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["데이터 소스"] == "CSV"
    assert metrics["판매 가능 상품"] == "21종"   # 22종 중 P022 는 단종
    assert metrics["등록 고객"] == "6곳"
    assert metrics["AI"] == "MOCK"


def test_mock_mode_is_announced_on_every_screen():
    """사용자가 가짜 데이터를 실제라고 착각하면 안 된다."""
    for page in ("Dashboard", "New Quotation", "Product Search"):
        at = _goto(_app(), page)
        assert "MOCK" in _texts(at.sidebar.warning) or "가상" in _texts(at.sidebar.warning)


def test_product_search_hides_cost_price():
    at = _goto(_app(), "Product Search")
    assert "cost_price" not in at.dataframe[0].value.columns


# ------------------------------------------------------------ 견적 작성 흐름

def _analysed():
    at = _goto(_app(), "New Quotation")
    at.button[0].click().run()          # 🤖 AI 로 요청 분석
    assert not at.exception, at.exception
    return at


def test_analysis_extracts_the_sample_inquiry():
    at = _analysed()
    assert "2. AI 요청 분석 결과" in [s.value for s in at.subheader]
    items = at.dataframe[0].value
    assert list(items["수량"]) == [20, 30, 30]
    assert list(items["검색어(영문)"]) == ["monitor", "keyboard", "wireless mouse"]


def test_mock_analysis_is_labelled_as_fake():
    at = _analysed()
    assert "MOCK 결과입니다" in _texts(at.warning)


def test_relative_delivery_is_not_turned_into_a_date():
    at = _analysed()
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["확정 납기일"] == "미확정"
    assert "다음 주" in metrics["요청 납기(원문)"]


def test_ambiguous_items_are_not_auto_picked():
    """'모니터' 는 후보가 여럿이다. UI 가 조용히 하나를 고르면 안 된다."""
    at = _analysed()
    assert all(sb.value == "" for sb in at.selectbox[1:]), \
        "애매한 상품이 자동 선택되었습니다"
    assert "상품을 하나 이상 선택하면" in _texts(at.info)
    assert not at.metric or "합계 (세금 포함)" not in [m.label for m in at.metric]


def _picked():
    """모니터·키보드·마우스를 직접 골라 견적을 완성한다."""
    at = _analysed()
    for sb, pid in zip(at.selectbox[1:4], ["P001", "P004", "P007"]):
        sb.set_value(pid)
    at.run()
    assert not at.exception, at.exception
    return at


def test_picking_products_produces_a_quote():
    at = _picked()
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["견적 포함 품목"] == "3건"
    # 4,590,000x20 + 290,000x30 + 265,000x30 = 108,450,000
    # GOLD 5% 할인 -> 103,027,500, VAT 10% -> 113,330,250
    assert metrics["합계 (세금 포함)"] == "113,330,250 VND"


def test_quote_table_has_every_picked_line():
    at = _picked()
    rows = at.dataframe[-1].value
    assert list(rows["상품ID"]) == ["P001", "P004", "P007"]
    assert list(rows["수량"]) == [20, 30, 30]


def test_changing_quantity_recalculates_the_total():
    at = _picked()
    before = {m.label: m.value for m in at.metric}["합계 (세금 포함)"]
    at.number_input[0].set_value(10).run()   # 모니터 20 -> 10
    after = {m.label: m.value for m in at.metric}["합계 (세금 포함)"]
    assert after != before
    # (4,590,000x10 + 290,000x30 + 265,000x30) = 62,550,000 -> x0.95 -> x1.1
    assert after == "65,364,750 VND"


def test_changing_discount_recalculates_the_total():
    at = _picked()
    discount = next(n for n in at.number_input if n.label == "할인율 (%)")
    discount.set_value(20.0).run()
    total = {m.label: m.value for m in at.metric}["합계 (세금 포함)"]
    assert total == "95,436,000 VND"          # 108,450,000 x0.8 x1.1


def test_stock_shortage_is_surfaced_in_the_ui():
    at = _analysed()
    at.selectbox[1].set_value("P003").run()   # 재고 5개 / 20개 주문
    assert "5개 부족" in _texts(at.error) or "15개 부족" in _texts(at.error)
    assert any("재고 부족" in w.value for w in at.warning)


def test_unknown_product_is_carried_as_needs_check():
    at = _goto(_app(), "New Quotation")
    at.text_area[0].set_value("모니터 5대, 드론 2대 필요합니다.").run()
    at.button[0].click().run()
    at.selectbox[1].set_value("P001").run()
    assert not at.exception, at.exception
    assert "드론" in _texts(at.warning)
    assert {m.label: m.value for m in at.metric}["확인 필요"] == "1건"


def test_pdf_can_be_generated_from_the_ui():
    at = _picked()
    pdf_button = next(b for b in at.button if "PDF 생성" in b.label)
    pdf_button.click().run()
    assert not at.exception, at.exception
    assert any("PDF 다운로드" in b.label for b in at.download_button)


def test_email_draft_can_be_generated_from_the_ui():
    at = _picked()
    next(b for b in at.button if "이메일 초안" in b.label).click().run()
    assert not at.exception, at.exception
    body = next(t for t in at.text_area if t.label == "본문").value
    assert "113,330,250 VND" in body
    assert "QT-" in body


def test_empty_inquiry_shows_a_friendly_error():
    at = _goto(_app(), "New Quotation")
    at.text_area[0].set_value("ㅇ").run()
    at.button[0].click().run()
    assert not at.exception, at.exception
    assert "짧" in _texts(at.error)


def test_unparseable_inquiry_shows_the_expected_format():
    at = _goto(_app(), "New Quotation")
    at.text_area[0].set_value("견적 부탁드립니다. 조건 좋으면 바로 발주합니다.").run()
    at.button[0].click().run()
    assert "상품명" in _texts(at.error)


# ------------------------------------------------------------ 설정 화면

def test_settings_never_shows_the_full_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-SECRETVALUE-1234567890")
    at = _goto(_app(), "Settings / Connection")
    page_text = _texts(at.markdown) + _texts(at.caption) + _texts(at.error)
    assert "SECRETVALUE" not in page_text
    assert "sk-ant-" in page_text


def test_settings_reports_font_status():
    at = _goto(_app(), "Settings / Connection")
    assert "PDF 폰트" in [s.value for s in at.subheader]
