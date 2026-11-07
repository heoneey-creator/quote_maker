"""8단계 점검: PDF 와 이메일 초안.

PDF 는 bytes 만 보고 '만들어졌다' 고 하면 안 된다. 텍스트를 다시 꺼내서
재고 부족과 미확인 품목이 정말 인쇄됐는지 확인한다 (숨겨지면 안 되는 정보).
실제 Claude 호출은 하지 않는다.
"""
from decimal import Decimal

import pytest
from pypdf import PdfReader

from core.config import Config
from core.email_draft import LANGUAGES, EmailError, draft_email
from core.extract import RequestedItem
from core.matching import MATCHED, Candidate, MatchedLine, match_line
from core.pdf import COVERAGE_PROBE, FALLBACK_FONT, register_font, render_quote_pdf
from core.pricing import Customer, build_quote
from core.sheets import load_catalog

MOCK_CFG = Config(anthropic_api_key="", anthropic_model="m",
                  google_credentials_file="", google_sheet_id="")


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(MOCK_CFG)


def _line(price, qty, stock=10 ** 6, pid="P001", name="Test Item"):
    item = RequestedItem(name_as_written=name, search_term_en=name, quantity=qty, note="")
    cand = Candidate(product_id=pid, product_name=name, category="X",
                     unit_price=Decimal(str(price)), stock_quantity=stock, score=1.0)
    return MatchedLine(item, MATCHED, [cand], pid, [])


@pytest.fixture(scope="module")
def quote(catalog):
    """재고 부족 1건 + 카탈로그 미확인 1건이 있는 견적."""
    missing = match_line(RequestedItem(name_as_written="드론", search_term_en="drone",
                                       quantity=2, note=""), catalog.products)
    customer = Customer(customer_id="C001", company_name="Saigon Tech Co., Ltd.",
                        contact_name="Nguyễn Văn Minh", email="minh@example.com",
                        customer_tier="GOLD", discount_rate=Decimal("0.05"))
    return build_quote(
        [_line(7250000, 20, stock=5, pid="P003", name='Samsung 32" Monitor LS32A600'),
         _line(290000, 30, pid="P004", name="Logitech K120 Wired Keyboard"),
         missing],
        customer, catalog, delivery_note="다음 주까지 납품 요청",
        remarks="베트남어 확인: Nguyễn Huệ, Đống Đa")


def _pdf_text(pdf_bytes) -> str:
    import io
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf_bytes)).pages)


# ------------------------------------------------------------ 폰트

def test_font_covers_korean_vietnamese_and_dong_sign():
    """윈도 기본 malgun.ttf 는 베트남어 성조가 없다. 통과하는 폰트를 골라야 한다."""
    font = register_font()
    if font.name == FALLBACK_FONT:
        pytest.skip("지원 폰트 미설치 — README 의 폰트 안내 참고: " + font.warning)
    from reportlab.pdfbase import pdfmetrics
    face = pdfmetrics.getFont(font.name).face
    missing = [c for c in COVERAGE_PROBE if c != " " and not face.charToGlyph.get(ord(c))]
    assert not missing, "폰트에 없는 글자: " + "".join(missing)


def test_missing_font_is_reported_loudly_not_silently():
    font = register_font()
    assert font.ok or "깨집니다" in font.warning


# ------------------------------------------------------------ PDF 내용

def test_pdf_is_a_valid_single_page_document(quote, catalog):
    import io
    reader = PdfReader(io.BytesIO(render_quote_pdf(quote, catalog.settings)))
    assert len(reader.pages) == 1


def test_pdf_contains_the_required_sections(quote, catalog):
    text = _pdf_text(render_quote_pdf(quote, catalog.settings))
    for needed in ["QUOTATION", quote.number, quote.issue_date.isoformat(),
                   quote.valid_until.isoformat(), quote.customer.company_name,
                   "Logitech K120 Wired Keyboard", "소계", "할인", "부가세", "합계",
                   "납기", str(catalog.settings["company_name"]),
                   str(catalog.settings["company_email"])]:
        assert needed in text, "PDF 에 없음: " + needed


def test_pdf_shows_the_exact_total(quote, catalog):
    text = _pdf_text(render_quote_pdf(quote, catalog.settings))
    assert f"{int(quote.total):,}" in text


def test_pdf_never_hides_a_stock_shortage(quote, catalog):
    """재고 부족이 견적서에서 안 보이면 고객이 납기를 오해한다."""
    text = _pdf_text(render_quote_pdf(quote, catalog.settings))
    assert "부족" in text
    assert "15" in text  # 20개 주문 - 재고 5개


def test_pdf_never_hides_an_unidentified_item(quote, catalog):
    text = _pdf_text(render_quote_pdf(quote, catalog.settings))
    assert "드론" in text and "확인 필요" in text


def test_pdf_states_prices_are_pre_tax(quote, catalog):
    assert "세전" in _pdf_text(render_quote_pdf(quote, catalog.settings))


def test_pdf_does_not_promise_a_delivery_date(quote, catalog):
    text = _pdf_text(render_quote_pdf(quote, catalog.settings))
    assert "확정할 수 없습니다" in text


def test_pdf_marks_mock_data(quote, catalog):
    text = _pdf_text(render_quote_pdf(quote, catalog.settings))
    assert "MOCK DATA" in text


def test_pdf_never_leaks_cost_price(quote, catalog):
    """원가(cost_price)가 견적서에 찍히면 영업 사고다.

    큰 금액의 부분 문자열로 우연히 일치하는 것(7,685,000 안의 85,000)은
    노출이 아니므로 숫자 경계를 둔다.
    """
    import re
    text = _pdf_text(render_quote_pdf(quote, catalog.settings))
    quoted_ids = {l.product_id for l in quote.lines}
    costs = catalog.products.loc[
        catalog.products["product_id"].isin(quoted_ids), "cost_price"]
    assert len(costs) > 0, "견적에 들어간 상품의 원가를 찾지 못했습니다"
    for cost in costs:
        pattern = r"(?<![\d,])" + re.escape(f"{int(cost):,}") + r"(?![\d,])"
        assert not re.search(pattern, text), "원가 노출: " + f"{int(cost):,}"


def test_broken_logo_path_does_not_break_the_pdf(quote, catalog):
    pdf = render_quote_pdf(quote, catalog.settings, logo_path="없는파일.png")
    assert pdf[:5] == b"%PDF-"


# ------------------------------------------------------------ 이메일

@pytest.mark.parametrize("lang", list(LANGUAGES))
def test_mock_draft_works_in_every_language(quote, lang):
    draft = draft_email(quote, lang, MOCK_CFG, "VietOffice Supply Co., Ltd.")
    assert draft.is_mock and draft.language == lang
    assert quote.number in draft.subject
    assert len(draft.body) > 100


@pytest.mark.parametrize("lang", list(LANGUAGES))
def test_draft_always_carries_the_exact_total(quote, lang):
    """금액은 Claude 가 아니라 Python 이 넣는다."""
    draft = draft_email(quote, lang, MOCK_CFG)
    assert f"{int(quote.total):,}" in draft.body
    assert f"{int(quote.subtotal):,}" in draft.body


@pytest.mark.parametrize("lang", list(LANGUAGES))
def test_draft_discloses_shortage_and_unknown_items(quote, lang):
    draft = draft_email(quote, lang, MOCK_CFG)
    assert "15" in draft.body          # 부족 수량
    assert "드론" in draft.body         # 미확인 품목
    assert "QT-" in draft.body


@pytest.mark.parametrize("lang", list(LANGUAGES))
def test_draft_does_not_promise_delivery(quote, lang):
    body = draft_email(quote, lang, MOCK_CFG).body
    assert any(k in body for k in ("별도 안내", "confirmed separately", "xác nhận riêng"))


def test_draft_marks_mock_data(quote):
    draft = draft_email(quote, "ko", MOCK_CFG)
    assert any("Mock" in n for n in draft.notes)
    assert "가상" in draft.body


def test_draft_says_it_is_not_sent(quote):
    assert any("발송하지 않습니다" in n for n in draft_email(quote, "ko", MOCK_CFG).notes)


def test_unsupported_language_is_rejected(quote):
    with pytest.raises(EmailError, match="지원하지 않는"):
        draft_email(quote, "jp", MOCK_CFG)


def test_vietnamese_draft_keeps_diacritics(quote):
    body = draft_email(quote, "vi", MOCK_CFG).body
    assert "Kính gửi" in body and "Trân trọng" in body
