"""견적서 PDF 생성.

폰트가 이 모듈에서 가장 까다로운 부분이다. 한글·베트남어·₫ 를 한 장에
같이 인쇄해야 하는데, 윈도 기본 한글 폰트(malgun.ttf)는 베트남어 성조
부호(ễ ệ Đ ố ồ ườ)가 없어서 빈 칸으로 찍힌다. Noto Sans KR 만 셋을 다 덮는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from core.config import PROJECT_ROOT
from core.pricing import Quote, format_money

FONT_NAME = "QuoteFont"
FALLBACK_FONT = "Helvetica"

# 한글 + 베트남어 + ₫ 를 모두 덮는 폰트를 찾는다. 순서가 곧 우선순위.
FONT_CANDIDATES = [
    PROJECT_ROOT / "fonts" / "NotoSansKR-Regular.ttf",
    Path("C:/Windows/Fonts/NotoSansKR-VF.ttf"),
    # Debian/Ubuntu 의 fonts-noto-cjk (Streamlit Cloud 배포 환경).
    # .ttc 는 여러 폰트를 담은 모음이라 subfontIndex 를 돌려봐야 한다.
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-VF.otf.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf"),
]

# .ttc 안의 폰트 수는 파일마다 달라서, 커버리지를 통과하는 첫 번째를 쓴다.
MAX_SUBFONTS = 6

# 이 글자들이 안 나오면 폰트가 부적합하다고 판단한다.
COVERAGE_PROBE = "견적서 Nguyễn Huệ Đống ố ồ ườ ₫ QUOTATION"

NAVY = colors.HexColor("#1e293b")
BLUE = colors.HexColor("#2563eb")
GREY = colors.HexColor("#64748b")
LIGHT = colors.HexColor("#f1f5f9")
RED = colors.HexColor("#b91c1c")
AMBER = colors.HexColor("#b45309")

_font_state: "FontState | None" = None


@dataclass(frozen=True)
class FontState:
    name: str
    path: str
    warning: str = ""

    @property
    def ok(self) -> bool:
        return not self.warning


def _missing_glyphs(path: Path, subfont: int = 0) -> list:
    face = TTFont("probe", str(path), subfontIndex=subfont).face
    return [c for c in COVERAGE_PROBE if c != " " and not face.charToGlyph.get(ord(c))]


def _try_font(path: Path, subfont: int, tried: list) -> bool:
    label = path.name + (f"[{subfont}]" if subfont else "")
    try:
        missing = _missing_glyphs(path, subfont)
    except Exception as exc:        # 깨진 파일, 없는 subfont, CFF 미지원 등
        tried.append(label + ": " + type(exc).__name__)
        return False
    if missing:
        tried.append(label + ": " + "".join(missing) + " 글자 없음")
        return False
    try:
        pdfmetrics.registerFont(TTFont(FONT_NAME, str(path), subfontIndex=subfont))
    except Exception as exc:
        tried.append(label + ": 등록 실패 " + type(exc).__name__)
        return False
    # 변동(variable) 폰트라 별도 Bold 파일이 없다. 굵게 요청도 같은 파일로 받는다.
    pdfmetrics.registerFontFamily(FONT_NAME, normal=FONT_NAME, bold=FONT_NAME,
                                  italic=FONT_NAME, boldItalic=FONT_NAME)
    return True


def register_font() -> FontState:
    """폰트를 한 번만 등록하고 결과를 기억한다."""
    global _font_state
    if _font_state is not None:
        return _font_state

    tried = []
    for path in FONT_CANDIDATES:
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        subfonts = range(MAX_SUBFONTS) if path.suffix.lower() == ".ttc" else [0]
        for subfont in subfonts:
            if _try_font(path, subfont, tried):
                _font_state = FontState(FONT_NAME, str(path)
                                        + (f" (#{subfont})" if subfont else ""))
                return _font_state

    detail = (" 시도한 폰트: " + "; ".join(tried)) if tried else ""
    _font_state = FontState(
        FALLBACK_FONT, "(내장 Helvetica)",
        "한글·베트남어를 지원하는 폰트를 찾지 못해 Helvetica 로 대체합니다. "
        "PDF 의 한글과 베트남어가 깨집니다. README 의 폰트 설치 안내를 따르세요." + detail)
    return _font_state


def _styles(font: str) -> dict:
    def style(name, **kw):
        return ParagraphStyle(name, **{"fontName": font, "textColor": NAVY,
                                       "fontSize": 9, "leading": 13, **kw})
    return {
        "title": style("t", fontSize=26, leading=30, textColor=BLUE),
        "h": style("h", fontSize=10.5, leading=15),
        "body": style("b"),
        "small": style("s", fontSize=7.8, leading=11, textColor=GREY),
        "cell": style("c", fontSize=8.5, leading=11),
        "right": style("r", alignment=TA_RIGHT),
        "warn": style("w", fontSize=8.5, leading=12, textColor=RED),
        "mock": style("m", fontSize=11, leading=14, textColor=AMBER, alignment=TA_CENTER),
    }


def _contact_line(settings: dict) -> str:
    """연락처 한 줄. Settings 에 없는 항목은 'Tel -' 로 찍지 않고 빼버린다."""
    parts = []
    phone = str(settings.get("company_phone", "")).strip()
    email = str(settings.get("company_email", "")).strip()
    if phone:
        parts.append("Tel " + phone)
    if email:
        parts.append(email)
    return " · ".join(parts)


def _logo_flowable(logo_path, width=42 * mm):
    if not logo_path:
        return None
    path = Path(logo_path)
    if not path.is_file():
        return None
    try:
        reader = ImageReader(str(path))
        iw, ih = reader.getSize()
        return Image(str(path), width=width, height=width * ih / iw)
    except Exception:
        return None  # 로고가 깨져도 견적서는 나와야 한다


def _header(quote: Quote, settings: dict, st: dict, logo_path) -> list:
    company = [
        Paragraph(str(settings.get("company_name", "")), st["h"]),
        Paragraph(str(settings.get("company_address", "")), st["small"]),
        Paragraph(_contact_line(settings), st["small"]),
    ]
    logo = _logo_flowable(logo_path)
    left = [logo, Spacer(1, 3 * mm)] + company if logo else company

    meta = Table([
        ["견적번호 / No.", quote.number],
        ["견적일자 / Date", quote.issue_date.isoformat()],
        ["유효기간 / Valid until", quote.valid_until.isoformat()],
    ], colWidths=[32 * mm, 38 * mm])
    meta.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), st["body"].fontName),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (0, -1), GREY),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, LIGHT),
    ]))

    head = Table([[left, [Paragraph("QUOTATION", st["title"]),
                          Paragraph("견적서 · Báo giá", st["small"]),
                          Spacer(1, 4 * mm), meta]]],
                 colWidths=[88 * mm, 82 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return [head]


def _customer_block(quote: Quote, st: dict) -> list:
    c = quote.customer
    rows = [[Paragraph("수신 / Bill to", st["small"]), ""],
            [Paragraph(c.company_name, st["h"]),
             Paragraph("고객등급 " + c.customer_tier, st["right"])],
            [Paragraph(c.contact_name + " · " + c.email, st["small"]), ""]]
    table = Table(rows, colWidths=[110 * mm, 60 * mm])
    table.setStyle(TableStyle([
        ("SPAN", (0, 0), (1, 0)), ("SPAN", (0, 2), (1, 2)),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return [table]


def _items_table(quote: Quote, st: dict) -> list:
    header = ["#", "상품명 / Item", "수량", "단가 / Unit", "금액 / Amount", "재고"]
    rows = [[Paragraph(h, st["small"]) for h in header]]
    shortage_rows = []

    for i, line in enumerate(quote.lines, 1):
        if line.stock.status == "short":
            shortage_rows.append(i)
            stock_text = "부족 " + f"{line.stock.shortage:,}"
        else:
            stock_text = line.stock.label
        rows.append([
            Paragraph(str(i), st["cell"]),
            Paragraph(line.product_name, st["cell"]),
            Paragraph(f"{line.quantity:,}", st["right"]),
            Paragraph(format_money(line.unit_price, quote.currency), st["right"]),
            Paragraph(format_money(line.line_total, quote.currency), st["right"]),
            Paragraph(stock_text, st["cell"]),
        ])

    # 금액에 못 들어간 상품도 숨기지 않고 같은 표에 '확인 필요' 로 적는다.
    for line in quote.unresolved:
        rows.append([
            Paragraph("–", st["cell"]),
            Paragraph(line.requested.name_as_written + "  (카탈로그 미확인)", st["warn"]),
            Paragraph(f"{line.requested.quantity:,}" if line.requested.quantity else "–", st["right"]),
            Paragraph("확인 필요", st["warn"]),
            Paragraph("확인 필요", st["warn"]),
            Paragraph("확인 필요", st["warn"]),
        ])

    table = Table(rows, colWidths=[8 * mm, 72 * mm, 16 * mm, 29 * mm, 31 * mm, 14 * mm],
                  repeatRows=1)
    style = [
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, NAVY),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, LIGHT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    for r in shortage_rows:
        style.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#fef2f2")))
    if quote.unresolved:
        first = len(quote.lines) + 1
        style.append(("BACKGROUND", (0, first), (-1, -1), colors.HexColor("#fff7ed")))
    table.setStyle(TableStyle(style))
    return [table]


def _totals(quote: Quote, st: dict) -> list:
    pct = lambda d: f"{d * 100:.3f}".rstrip("0").rstrip(".") + "%"
    rows = [
        ["소계 / Subtotal", format_money(quote.subtotal, quote.currency)],
        ["할인 / Discount (" + pct(quote.discount_rate) + ")",
         "-" + format_money(quote.discount_amount, quote.currency)],
        ["과세대상 / Taxable", format_money(quote.taxable, quote.currency)],
        ["부가세 / VAT (" + pct(quote.tax_rate) + ")",
         format_money(quote.tax_amount, quote.currency)],
        ["합계 / TOTAL", format_money(quote.total, quote.currency)],
    ]
    table = Table([[Paragraph(a, st["body"]), Paragraph(b, st["right"])] for a, b in rows],
                  colWidths=[55 * mm, 45 * mm], hAlign="RIGHT")
    table.setStyle(TableStyle([
        ("LINEABOVE", (0, 4), (-1, 4), 0.8, NAVY),
        ("BACKGROUND", (0, 4), (-1, 4), LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return [table]


def _notice(quote: Quote, st: dict) -> list:
    out = []
    if quote.warnings:
        body = "".join("• " + w + "<br/>" for w in quote.warnings)
        box = Table([[Paragraph("<b>확인 필요 / Please note</b><br/>" + body, st["warn"])]],
                    colWidths=[170 * mm])
        box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fef2f2")),
            ("BOX", (0, 0), (-1, -1), 0.6, RED),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        out += [box, Spacer(1, 4 * mm)]

    delivery = quote.delivery_note or "고객 요청 납기 없음"
    out.append(Paragraph(
        "<b>납기 안내 / Delivery</b><br/>고객 요청: " + delivery
        + "<br/>납기일은 현재 재고만으로 확정할 수 없습니다. 영업 담당자 확인 후 "
          "별도 회신드립니다. (Delivery date is subject to confirmation.)", st["small"]))
    if quote.remarks:
        out += [Spacer(1, 3 * mm),
                Paragraph("<b>비고 / Remarks</b><br/>" + quote.remarks.replace("\n", "<br/>"),
                          st["small"])]
    return out


def _footer(quote: Quote, settings: dict, st: dict) -> list:
    return [Paragraph(
        "표시 금액은 " + quote.currency + " 기준이며, 상품 단가는 <b>세전</b> 가격입니다. "
        "부가세는 Settings 의 세율을 적용했습니다.<br/>"
        + str(settings.get("company_name", "")) + " · "
        + str(settings.get("company_address", "")) + "<br/>"
        + _contact_line(settings), st["small"])]


def render_quote_pdf(quote: Quote, settings: dict, logo_path=None) -> bytes:
    """견적서 PDF 를 bytes 로 돌려준다. 파일을 쓰지 않으므로 서버에서도 안전하다."""
    font = register_font()
    st = _styles(font.name)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title="Quotation " + quote.number,
                            author=str(settings.get("company_name", "")))

    story = []
    if quote.is_mock_data:
        banner = Table([[Paragraph("가상 데이터로 생성된 견적서입니다 — 실제 거래에 "
                                   "사용하지 마세요<br/>MOCK DATA — NOT FOR ACTUAL USE",
                                   st["mock"])]], colWidths=[170 * mm])
        banner.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffbeb")),
            ("BOX", (0, 0), (-1, -1), 1, AMBER),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story += [banner, Spacer(1, 5 * mm)]

    story += _header(quote, settings, st, logo_path)
    story += [Spacer(1, 7 * mm)]
    story += _customer_block(quote, st)
    story += [Spacer(1, 6 * mm)]
    story += _items_table(quote, st)
    story += [Spacer(1, 5 * mm)]
    story += _totals(quote, st)
    story += [Spacer(1, 7 * mm)]
    story += _notice(quote, st)
    story += [Spacer(1, 6 * mm)]
    story += _footer(quote, settings, st)

    doc.build(story)
    return buffer.getvalue()
