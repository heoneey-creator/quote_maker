"""견적서와 함께 보낼 이메일 초안. 한국어·영어·베트남어.

금액은 Claude 가 쓰지 않는다. Claude 는 인사말과 본문만 쓰고,
숫자가 들어가는 요약 블록은 Python 이 계산된 값으로 조립한다.
이렇게 하면 AI 가 금액을 한 자리 틀리게 적는 사고가 구조적으로 불가능하다.

이 단계에서 메일을 실제로 발송하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from core.config import Config
from core.pricing import Quote, format_money

SOURCE_CLAUDE = "claude"
SOURCE_MOCK = "mock"

LANGUAGES = {"ko": "한국어", "en": "English", "vi": "Tiếng Việt"}

_LANG_NAMES = {"ko": "Korean", "en": "English", "vi": "Vietnamese"}


class EmailError(Exception):
    pass


class EmailProse(BaseModel):
    subject: str = Field(description="Email subject line. No monetary figures.")
    body: str = Field(description="Email body prose without any monetary figures, "
                                  "totals, quantities or dates. 2-4 short paragraphs.")


@dataclass
class EmailDraft:
    language: str
    subject: str
    body: str
    source: str
    model: str = "-"
    notes: list = field(default_factory=list)

    @property
    def is_mock(self) -> bool:
        return self.source == SOURCE_MOCK


# ---------------------------------------------------------------- 요약 블록 (Python)

_LABELS = {
    "ko": {"quote": "견적번호", "date": "견적일자", "valid": "유효기간",
           "items": "품목 수", "subtotal": "소계", "discount": "할인",
           "tax": "부가세", "total": "합계(세금 포함)", "unit": "개",
           "short": "재고 확인 필요", "notfound": "확인이 필요한 품목",
           "shortmsg": "현재 재고 {available}개 / 주문 {ordered}개 — {shortage}개 부족",
           "delivery": "납기일은 재고 확인 후 별도 안내드립니다.",
           "mock": "※ 이 초안은 가상 데이터로 생성되었습니다."},
    "en": {"quote": "Quotation No.", "date": "Date", "valid": "Valid until",
           "items": "Line items", "subtotal": "Subtotal", "discount": "Discount",
           "tax": "VAT", "total": "Total (incl. tax)", "unit": "pcs",
           "short": "Stock to be confirmed", "notfound": "Items requiring clarification",
           "shortmsg": "{available} in stock / {ordered} ordered — short by {shortage}",
           "delivery": "The delivery date will be confirmed separately after a stock check.",
           "mock": "Note: this draft was generated from mock data."},
    "vi": {"quote": "Số báo giá", "date": "Ngày", "valid": "Có hiệu lực đến",
           "items": "Số mặt hàng", "subtotal": "Tạm tính", "discount": "Giảm giá",
           "tax": "VAT", "total": "Tổng cộng (gồm thuế)", "unit": "cái",
           "short": "Cần xác nhận tồn kho", "notfound": "Mặt hàng cần xác nhận",
           "shortmsg": "Còn {available} / đặt {ordered} — thiếu {shortage}",
           "delivery": "Ngày giao hàng sẽ được xác nhận riêng sau khi kiểm tra tồn kho.",
           "mock": "Lưu ý: bản nháp này được tạo từ dữ liệu giả."},
}


def _summary(quote: Quote, lang: str) -> str:
    L = _LABELS[lang]
    money = lambda v: format_money(v, quote.currency)
    pct = f"{quote.discount_rate * 100:.3f}".rstrip("0").rstrip(".")
    tax_pct = f"{quote.tax_rate * 100:.3f}".rstrip("0").rstrip(".")

    rows = [
        f"{L['quote']}: {quote.number}",
        f"{L['date']}: {quote.issue_date.isoformat()}",
        f"{L['valid']}: {quote.valid_until.isoformat()}",
        f"{L['items']}: {len(quote.lines)}",
        f"{L['subtotal']}: {money(quote.subtotal)}",
        f"{L['discount']} ({pct}%): -{money(quote.discount_amount)}",
        f"{L['tax']} ({tax_pct}%): {money(quote.tax_amount)}",
        f"{L['total']}: {money(quote.total)}",
    ]
    out = ["-" * 46] + rows + ["-" * 46]

    if quote.short_lines:
        out += ["", f"[{L['short']}]"]
        for line in quote.short_lines:
            out.append("- " + line.product_name + ": " + L["shortmsg"].format(
                available=f"{line.stock.available:,}", ordered=f"{line.stock.ordered:,}",
                shortage=f"{line.stock.shortage:,}"))
    if quote.unresolved:
        out += ["", f"[{L['notfound']}]"]
        for line in quote.unresolved:
            out.append("- " + line.requested.name_as_written)
    out += ["", L["delivery"]]
    if quote.is_mock_data:
        out += ["", L["mock"]]
    return "\n".join(out)


# ---------------------------------------------------------------- Mock 본문

_MOCK_PROSE = {
    "ko": ("{company} {contact}님께\n\n안녕하세요. {sender} 입니다.\n"
           "문의해 주신 내용에 대한 견적서를 첨부와 같이 보내드립니다.\n\n"
           "검토 후 문의사항이 있으시면 언제든 연락 주시기 바랍니다.\n"
           "거래를 함께할 수 있기를 기대합니다.\n\n감사합니다.\n{sender}"),
    "en": ("Dear {contact} ({company}),\n\nThank you for your enquiry. "
           "Please find our quotation attached.\n\n"
           "Should you have any questions, please do not hesitate to contact us. "
           "We look forward to working with you.\n\nBest regards,\n{sender}"),
    "vi": ("Kính gửi {contact} ({company}),\n\nCảm ơn Quý công ty đã liên hệ. "
           "Chúng tôi xin gửi kèm báo giá theo yêu cầu.\n\n"
           "Nếu Quý công ty có bất kỳ câu hỏi nào, xin vui lòng liên hệ với chúng tôi. "
           "Rất mong được hợp tác.\n\nTrân trọng,\n{sender}"),
}

_MOCK_SUBJECT = {
    "ko": "[견적서] {company} 귀중 — {number}",
    "en": "Quotation {number} for {company}",
    "vi": "Báo giá {number} — {company}",
}


def _mock_prose(quote: Quote, lang: str, sender: str) -> EmailProse:
    return EmailProse(
        subject=_MOCK_SUBJECT[lang].format(company=quote.customer.company_name,
                                           number=quote.number),
        body=_MOCK_PROSE[lang].format(company=quote.customer.company_name,
                                      contact=quote.customer.contact_name,
                                      sender=sender))


# ---------------------------------------------------------------- Claude 본문

SYSTEM_PROMPT = """You draft polite B2B sales emails for an office-supply distributor \
in Vietnam, to accompany a price quotation that is attached as a PDF.

Hard rules:
- Write ONLY in the requested language.
- Never write any monetary amount, percentage, quantity, date, or quotation number. \
A separate summary block with the exact figures is appended automatically after your \
text. Refer to the attachment instead ("as per the attached quotation").
- Never promise or confirm a delivery date, lead time, or stock availability.
- Keep it to 2-4 short paragraphs: greeting, that the quotation is attached, an \
invitation to ask questions, and a closing with the sender name.
- Professional and warm, not salesy. No emoji, no markdown."""


def _claude_prose(quote: Quote, lang: str, sender: str, cfg: Config) -> EmailProse:
    import anthropic

    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    context = (
        "Language: " + _LANG_NAMES[lang] + "\n"
        "Customer company: " + quote.customer.company_name + "\n"
        "Customer contact person: " + quote.customer.contact_name + "\n"
        "Sender (our company): " + sender + "\n"
        "Number of line items: " + str(len(quote.lines)) + "\n"
        "Some items are short on stock: " + ("yes" if quote.short_lines else "no") + "\n"
        "Some requested items could not be identified: "
        + ("yes" if quote.unresolved else "no"))
    try:
        response = client.messages.parse(
            model=cfg.anthropic_model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": context}],
            output_format=EmailProse,
        )
    except anthropic.AuthenticationError:
        raise EmailError("Claude API 키가 거부되었습니다. .env 의 ANTHROPIC_API_KEY 를 확인하세요.")
    except anthropic.RateLimitError:
        raise EmailError("Claude API 호출 한도에 걸렸습니다. 잠시 후 다시 시도하세요.")
    except anthropic.APIConnectionError:
        raise EmailError("Claude API 에 연결할 수 없습니다. 인터넷 연결을 확인하세요.")
    except anthropic.APIStatusError as e:
        raise EmailError("Claude API 오류 (" + str(e.status_code) + "). 잠시 후 다시 시도하세요.")

    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise EmailError("Claude 가 이메일 초안을 만들지 못했습니다. 다시 시도해 주세요.")
    return response.parsed_output


# ---------------------------------------------------------------- 공개 함수

def draft_email(quote: Quote, language: str, cfg: Config,
                sender_name: str = "") -> EmailDraft:
    lang = (language or "ko").lower()
    if lang not in LANGUAGES:
        raise EmailError("지원하지 않는 언어입니다: " + str(language)
                         + " (가능: " + ", ".join(LANGUAGES) + ")")
    sender = sender_name or "Sales Team"
    notes = []

    if cfg.claude_ready:
        prose, source, model = _claude_prose(quote, lang, sender, cfg), SOURCE_CLAUDE, cfg.anthropic_model
    else:
        prose, source, model = _mock_prose(quote, lang, sender), SOURCE_MOCK, "-"
        notes.append("Mock 모드: 정해진 템플릿 문장입니다. 실제 Claude 결과가 아닙니다.")

    # Claude 가 규칙을 어기고 숫자를 썼더라도, 권위 있는 숫자는 항상 아래 블록이다.
    body = prose.body.strip() + "\n\n" + _summary(quote, lang)
    subject = prose.subject.strip() or _MOCK_SUBJECT[lang].format(
        company=quote.customer.company_name, number=quote.number)
    if quote.number not in subject:
        subject = subject + " [" + quote.number + "]"
    notes.append("이 단계에서는 메일을 발송하지 않습니다. 복사해서 사용하세요.")
    return EmailDraft(lang, subject, body, source, model, notes)
