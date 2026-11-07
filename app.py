"""AI Quote Factory — Streamlit UI.

이 파일에는 계산·매칭·PDF 로직이 없다. 전부 core/ 를 호출만 한다.
FastAPI 로 갈아끼울 때 버려지는 파일은 이것 하나다.
"""
from decimal import Decimal

import pandas as pd
import streamlit as st

from core.config import load_config, mask
from core.email_draft import LANGUAGES, EmailError, draft_email
from core.extract import ExtractError, extract_request
from core.matching import (
    AMBIGUOUS, DISCONTINUED, MATCHED, NOT_FOUND, MatchError, check_stock,
    match_request, select_product,
)
from core.pdf import register_font, render_quote_pdf
from core.pricing import (
    PricingError, build_quote, customer_from_catalog, format_money,
    override_quantity, quote_rows,
)
from core.sheets import DataError, load_catalog, explain_sheet_error

st.set_page_config(page_title="AI Quote Factory", page_icon="📄", layout="wide")

PAGES = ["Dashboard", "New Quotation", "Product Search", "Quotation Preview",
         "Settings / Connection"]
STEPS = ["고객 문의 입력", "AI 요청 분석", "상품 자동 매칭", "가격·재고 확인",
         "견적 검토", "PDF 다운로드"]

SAMPLE_INQUIRY = ("안녕하세요. 모니터 20대, 키보드 30개,\n무선 마우스 30개가 필요합니다.\n"
                  "다음 주까지 납품 가능한지 확인해 주시고 견적 부탁드립니다.")

cfg = load_config()


# ---------------------------------------------------------------- 공통

@st.cache_data(show_spinner="데이터를 불러오는 중...")
def cached_catalog(sheet_id: str, creds: str):
    """시트 API 를 매 클릭마다 호출하지 않는다 (할당량·속도).
    캐시 키는 설정값이므로, .env 를 바꾸면 자동으로 다시 읽는다."""
    return load_catalog(cfg)


def get_catalog():
    try:
        return cached_catalog(cfg.google_sheet_id, cfg.google_credentials_file)
    except Exception as exc:
        st.error("**데이터를 불러오지 못했습니다**\n\n" + explain_sheet_error(exc))
        st.stop()


def data_badge(catalog):
    if catalog.is_mock_data:
        return "🧪 가상 데이터 (CSV)"
    return "🟢 Google Sheets"


def ai_badge(is_mock: bool):
    return "🧪 MOCK 결과 (AI 아님)" if is_mock else "🤖 Claude 실제 응답"


def step_bar(current: int):
    cols = st.columns(len(STEPS))
    for i, (col, name) in enumerate(zip(cols, STEPS), start=1):
        if i < current:
            col.markdown(f"✅ **{i}. {name}**")
        elif i == current:
            col.markdown(f"🔵 **{i}. {name}**")
        else:
            col.caption(f"{i}. {name}")
    st.divider()


def reset_quote_state():
    for key in ("extraction", "lines", "quote", "pdf_bytes", "email"):
        st.session_state.pop(key, None)


# ---------------------------------------------------------------- 사이드바

with st.sidebar:
    st.title("📄 AI Quote Factory")
    st.caption("B2B 견적 자동화 · 1단계")
    page = st.radio("메뉴", PAGES, label_visibility="collapsed")
    st.divider()

    if cfg.claude_ready:
        st.success("🤖 Claude API 연결됨\n\n`" + cfg.anthropic_model + "`")
    else:
        st.warning("🧪 Claude MOCK 모드\n\nAI 결과가 가짜입니다.")

    if cfg.sheets_ready:
        st.success("🟢 Google Sheets 설정됨")
    else:
        st.warning("🧪 가상 데이터 (CSV)\n\n상품·가격이 실제가 아닙니다.")

    st.divider()
    if st.button("🔄 데이터 다시 읽기", width="stretch"):
        cached_catalog.clear()
        st.rerun()


# ---------------------------------------------------------------- Dashboard

if page == "Dashboard":
    st.header("Dashboard")
    catalog = get_catalog()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("데이터 소스", "Sheets" if not catalog.is_mock_data else "CSV")
    c2.metric("판매 가능 상품", f"{len(catalog.active_products)}종")
    c3.metric("등록 고객", f"{len(catalog.customers)}곳")
    c4.metric("AI", "Claude" if cfg.claude_ready else "MOCK")

    if catalog.is_mock_data or not cfg.claude_ready:
        st.info("🧪 일부가 **가상 모드**입니다. " + data_badge(catalog)
                + " / " + ai_badge(not cfg.claude_ready), icon="🧪")

    for warning in catalog.warnings:
        st.warning(warning, icon="⚠️")

    st.subheader("견적 작성 흐름")
    st.markdown(" → ".join(f"**{i}. {s}**" for i, s in enumerate(STEPS, 1)))
    st.caption(f"표시 가격은 모두 **세전** 기준입니다. 통화 {catalog.currency} · "
               f"부가세 {catalog.tax_rate * 100:g}% · 견적 유효기간 {catalog.valid_days}일 "
               "(값은 모두 Settings 탭에서 읽습니다)")

    st.subheader("재고 주의 상품")
    low = catalog.active_products.nsmallest(5, "stock_quantity")[
        ["product_id", "product_name", "stock_quantity", "unit_price"]]
    low["unit_price"] = low["unit_price"].map(lambda v: format_money(Decimal(str(v)), catalog.currency))
    st.dataframe(low, hide_index=True, width="stretch")


# ---------------------------------------------------------------- New Quotation

elif page == "New Quotation":
    st.header("New Quotation")
    catalog = get_catalog()
    products = catalog.products

    current = 1
    if st.session_state.get("extraction"):
        current = 3
    if st.session_state.get("lines") and all(
            not l.needs_attention for l in st.session_state["lines"]):
        current = 4
    if st.session_state.get("quote"):
        current = 6
    step_bar(current)

    # --- 1. 고객 문의 입력 -------------------------------------------------
    st.subheader("1. 고객 문의 입력")
    left, right = st.columns([2, 1])
    with right:
        labels = {row.customer_id: f"{row.company_name} ({row.customer_tier} "
                                   f"{row.discount_rate * 100:g}%)"
                  for row in catalog.customers.itertuples(index=False)}
        customer_id = st.selectbox("고객 선택", list(labels), format_func=labels.get)
        st.caption("할인율은 고객 등급에서 가져오며, 5단계에서 수정할 수 있습니다.")
    with left:
        inquiry = st.text_area("고객이 보낸 문의 내용", value=SAMPLE_INQUIRY, height=160)

    if st.button("🤖 AI 로 요청 분석", type="primary"):
        reset_quote_state()
        st.session_state.pop("extract_error", None)
        try:
            with st.spinner("문의를 분석하는 중..."):
                st.session_state["extraction"] = extract_request(inquiry, cfg)
            st.session_state["lines"] = match_request(
                st.session_state["extraction"].request, products)
            st.rerun()
        except ExtractError as exc:
            # 오류는 session_state 에 담는다. st.rerun() 뒤에 쓴 st.error 는 지워진다.
            st.session_state["extract_error"] = str(exc)

    if st.session_state.get("extract_error"):
        st.error(st.session_state["extract_error"])

    extraction = st.session_state.get("extraction")
    if not extraction:
        st.stop()

    # --- 2. AI 분석 결과 ---------------------------------------------------
    st.divider()
    st.subheader("2. AI 요청 분석 결과")
    if extraction.is_mock:
        st.warning("🧪 **MOCK 결과입니다.** 정규식으로 만든 가짜 분석이며 "
                   "Claude 가 생성한 것이 아닙니다.", icon="🧪")
    else:
        st.success("🤖 Claude (`" + extraction.model + "`) 가 분석한 실제 결과입니다.")
    for note in extraction.notes:
        st.caption("• " + note)

    request = extraction.request
    st.dataframe(pd.DataFrame([{
        "고객 표현": i.name_as_written, "검색어(영문)": i.search_term_en,
        "수량": i.quantity, "비고": i.note} for i in request.items]),
        hide_index=True, width="stretch")
    meta = st.columns(3)
    meta[0].metric("요청 납기(원문)", request.delivery_request_text or "없음")
    meta[1].metric("확정 납기일", request.delivery_date_iso or "미확정")
    meta[2].metric("언급된 고객명", request.customer_name_mentioned or "없음")
    if request.other_requirements:
        st.info("**기타 요구사항**\n\n"
                + "\n".join("- " + r for r in request.other_requirements))
    st.caption("⚠️ 위 내용은 고객이 보낸 텍스트에서 추출한 것입니다. "
               "가격·재고·납기는 여기서 오지 않고 시트와 계산에서만 나옵니다.")

    # --- 3. 상품 매칭 ------------------------------------------------------
    st.divider()
    st.subheader("3. 상품 자동 매칭")
    lines = st.session_state["lines"]
    all_labels = {str(r.product_id): f"{r.product_id} · {r.product_name} "
                                     f"({format_money(Decimal(str(r.unit_price)), catalog.currency)}, "
                                     f"재고 {int(r.stock_quantity):,})"
                  for r in catalog.active_products.itertuples(index=False)}

    keep = []
    for idx, line in enumerate(lines):
        icon = {MATCHED: "✅", AMBIGUOUS: "🔶", NOT_FOUND: "❌",
                DISCONTINUED: "🚫"}[line.status]
        title = (f"{icon} {line.requested.name_as_written} "
                 f"— {line.requested.quantity:,}개 요청")
        with st.expander(title, expanded=line.needs_attention):
            for note in line.notes:
                st.caption("• " + note)

            # 후보가 여럿이거나 못 찾은 줄은 사람이 고르기 전까지 비워 둔다.
            # 첫 후보를 자동 선택하면 '모니터' 요청에 엉뚱한 모델이 조용히 들어간다.
            options = [c.product_id for c in line.candidates
                       if c.product_id in all_labels] or list(all_labels)
            if line.status != MATCHED:
                options = [""] + options
            labels = dict(all_labels, **{"": "— 상품을 선택하세요 —"})
            default = (options.index(line.selected_product_id)
                       if line.selected_product_id in options else 0)
            cols = st.columns([3, 1, 1])
            chosen = cols[0].selectbox("상품", options, index=default,
                                       format_func=labels.get, key=f"sel{idx}")
            qty = cols[1].number_input("수량", min_value=1, max_value=1_000_000,
                                       value=max(1, line.requested.quantity),
                                       step=1, key=f"qty{idx}")
            if not chosen:
                st.info("상품이 확정되지 않았습니다. 목록에서 선택하면 금액이 계산됩니다. "
                        "선택하지 않으면 견적서에 '확인 필요' 로 표시됩니다.")
                keep.append(line)
                continue
            # 체크박스는 상품이 정해진 뒤에만 만든다. 위젯 값은 key 로 유지되므로,
            # 미확정 상태에서 먼저 만들면 False 로 굳어 선택해도 포함되지 않는다.
            if not cols[2].checkbox("포함", value=True, key=f"inc{idx}"):
                st.caption("이 품목은 견적 금액에서 제외되고 '확인 필요' 로 표시됩니다.")
                keep.append(line)
                continue
            try:
                updated = override_quantity(select_product(line, chosen, products), int(qty))
            except (MatchError, PricingError) as exc:
                st.error(str(exc))
                keep.append(line)
                continue
            stock = check_stock(updated)
            if stock.status == "short":
                st.error(f"재고 부족: 주문 {stock.ordered:,}개 / 현재 재고 "
                         f"{stock.available:,}개 → **{stock.shortage:,}개 부족**")
            else:
                st.success(f"재고 정상 (현재 {stock.available:,}개)")
            keep.append(updated)
    st.session_state["lines"] = keep
    lines = keep

    # --- 4. 가격·재고 요약 --------------------------------------------------
    st.divider()
    st.subheader("4. 가격·재고 확인")
    resolved = [l for l in lines if l.status == MATCHED and l.selected]
    unresolved = [l for l in lines if l not in resolved]
    cols = st.columns(3)
    cols[0].metric("견적 포함 품목", f"{len(resolved)}건")
    cols[1].metric("재고 부족", f"{sum(1 for l in resolved if check_stock(l).status == 'short')}건")
    cols[2].metric("확인 필요", f"{len(unresolved)}건")
    if unresolved:
        st.warning("다음 품목은 **금액에 포함되지 않고** 견적서에 '확인 필요' 로 "
                   "표시됩니다:\n\n"
                   + "\n".join("- " + l.requested.name_as_written for l in unresolved))

    if not resolved:
        st.info("위 3번에서 상품을 하나 이상 선택하면 금액 계산과 견적 검토가 나타납니다.",
                icon="👆")
        st.stop()

    # --- 5. 견적 검토 ------------------------------------------------------
    st.divider()
    st.subheader("5. 견적 검토")
    customer = customer_from_catalog(catalog, customer_id)
    c1, c2 = st.columns(2)
    discount_pct = c1.number_input(
        "할인율 (%)", min_value=0.0, max_value=90.0,
        value=float(customer.discount_rate * 100), step=0.5,
        help=f"기본값은 {customer.customer_tier} 등급 할인율입니다.")
    valid_days = c2.number_input("견적 유효기간 (일)", min_value=1, max_value=365,
                                 value=catalog.valid_days, step=1)
    delivery_note = st.text_input("납기 관련 메모",
                                  value=request.delivery_request_text,
                                  help="견적서에 '고객 요청' 으로 인쇄됩니다. "
                                       "납기일 확정은 하지 않습니다.")
    remarks = st.text_area("특이사항 / 비고",
                           value="\n".join(request.other_requirements), height=90)

    try:
        quote = build_quote(lines, customer, catalog,
                            discount_rate=Decimal(str(discount_pct)) / 100,
                            valid_days=int(valid_days),
                            delivery_note=delivery_note, remarks=remarks,
                            quote_number=st.session_state.get("quote_number", ""))
    except PricingError as exc:
        st.error("**계산할 수 없습니다** — " + str(exc))
        st.stop()
    st.session_state["quote_number"] = quote.number
    st.session_state["quote"] = quote

    st.dataframe(quote_rows(quote), hide_index=True, width="stretch")
    t1, t2 = st.columns([2, 1])
    with t2:
        for label, value in [("소계", quote.subtotal),
                             (f"할인 ({discount_pct:g}%)", -quote.discount_amount),
                             ("과세대상", quote.taxable),
                             (f"부가세 ({quote.tax_rate * 100:g}%)", quote.tax_amount)]:
            st.write(f"{label} · **{format_money(value, quote.currency)}**")
        st.metric("합계 (세금 포함)", format_money(quote.total, quote.currency))
    with t1:
        for warning in quote.warnings:
            st.warning(warning, icon="⚠️")
        st.caption(f"계산 순서: 줄 합계 → 소계 → 할인 → 과세대상 → 부가세 → 합계. "
                   f"모든 금액은 {quote.currency} 정수로 반올림됩니다.")

    # --- 6. PDF + 이메일 ---------------------------------------------------
    st.divider()
    st.subheader("6. PDF 다운로드 & 이메일 초안")
    font = register_font()
    if not font.ok:
        st.error(font.warning)

    pdf_col, mail_col = st.columns(2)
    with pdf_col:
        logo = st.file_uploader("회사 로고 (선택, PNG/JPG)", type=["png", "jpg", "jpeg"])
        logo_path = None
        if logo is not None:
            # 업로드 파일은 임시 폴더에 둔다. 프로젝트 폴더에 쓰면 깃에 섞인다.
            import tempfile
            from pathlib import Path as _Path
            logo_path = str(_Path(tempfile.gettempdir()) / ("quote_logo_" + logo.name))
            with open(logo_path, "wb") as fh:
                fh.write(logo.getbuffer())
        if st.button("📄 PDF 생성", type="primary"):
            st.session_state["pdf_bytes"] = render_quote_pdf(quote, catalog.settings, logo_path)
        if st.session_state.get("pdf_bytes"):
            st.download_button("⬇️ 견적서 PDF 다운로드",
                               data=st.session_state["pdf_bytes"],
                               file_name=quote.number + ".pdf",
                               mime="application/pdf", width="stretch")
            st.caption(f"{len(st.session_state['pdf_bytes']):,} bytes · 폰트 {font.name}")

    with mail_col:
        lang = st.radio("이메일 언어", list(LANGUAGES),
                        format_func=LANGUAGES.get, horizontal=True)
        if st.button("✉️ 이메일 초안 생성"):
            try:
                with st.spinner("초안을 작성하는 중..."):
                    st.session_state["email"] = draft_email(
                        quote, lang, cfg, str(catalog.settings.get("company_name", "")))
            except EmailError as exc:
                st.error(str(exc))
        email = st.session_state.get("email")
        if email:
            st.caption(ai_badge(email.is_mock) + ("" if email.is_mock
                                                  else " · `" + email.model + "`"))
            st.text_input("제목", value=email.subject, key="mail_subject")
            st.text_area("본문", value=email.body, height=320, key="mail_body")
            st.caption("📮 이 단계에서는 메일을 발송하지 않습니다. 복사해서 사용하세요.")


# ---------------------------------------------------------------- Product Search

elif page == "Product Search":
    st.header("Product Search")
    catalog = get_catalog()
    st.caption(data_badge(catalog) + " · 단가는 모두 세전 " + catalog.currency)

    c1, c2, c3 = st.columns([2, 1, 1])
    term = c1.text_input("상품명 검색", placeholder="monitor, 키보드, paper ...")
    category = c2.selectbox("카테고리", ["전체"] + sorted(catalog.products["category"].unique()))
    only_active = c3.checkbox("판매 가능만", value=True)

    df = catalog.products
    if only_active:
        df = df[df["active"]]
    if category != "전체":
        df = df[df["category"] == category]
    if term.strip():
        from core.matching import _score
        df = df.assign(유사도=[round(_score(term, f"{r.product_name} {r.category}"), 2)
                             for r in df.itertuples(index=False)])
        df = df[df["유사도"] >= 0.6].sort_values("유사도", ascending=False)

    view = df.copy()
    view["unit_price"] = view["unit_price"].map(
        lambda v: format_money(Decimal(str(v)), catalog.currency))
    st.caption(f"{len(view)}건")
    st.dataframe(view.drop(columns=["cost_price"]), hide_index=True,
                 width="stretch")
    st.caption("원가(cost_price)는 화면과 견적서에 표시하지 않습니다.")


# ---------------------------------------------------------------- Preview

elif page == "Quotation Preview":
    st.header("Quotation Preview")
    quote = st.session_state.get("quote")
    if not quote:
        st.info("아직 작성된 견적이 없습니다. **New Quotation** 에서 먼저 만들어 주세요.")
        st.stop()

    if quote.is_mock_data:
        st.warning("🧪 가상 데이터로 만든 견적입니다. 실제 거래에 사용하지 마세요.", icon="🧪")
    c = st.columns(4)
    c[0].metric("견적번호", quote.number)
    c[1].metric("고객", quote.customer.company_name)
    c[2].metric("유효기간", quote.valid_until.isoformat())
    c[3].metric("합계", format_money(quote.total, quote.currency))
    st.dataframe(quote_rows(quote), hide_index=True, width="stretch")
    for warning in quote.warnings:
        st.warning(warning, icon="⚠️")
    if st.session_state.get("pdf_bytes"):
        st.download_button("⬇️ 견적서 PDF 다시 받기", data=st.session_state["pdf_bytes"],
                           file_name=quote.number + ".pdf", mime="application/pdf")


# ---------------------------------------------------------------- Settings

else:
    st.header("Settings / Connection Status")

    st.subheader("Claude API")
    st.write(f"키 `{mask(cfg.anthropic_api_key)}` · 모델 `{cfg.anthropic_model}`")
    if cfg.claude_ready:
        st.success("설정됨 — AI 분석과 이메일 초안이 실제 Claude 응답입니다.")
    else:
        st.error("`.env` 의 `ANTHROPIC_API_KEY` 가 비어 있어 **MOCK 모드**로 동작합니다.")

    st.subheader("Google Sheets")
    st.write(f"인증 파일 `{cfg.google_credentials_file or '(없음)'}` · "
             f"시트 ID `{mask(cfg.google_sheet_id)}`")
    try:
        catalog = cached_catalog(cfg.google_sheet_id, cfg.google_credentials_file)
        st.success(f"{catalog.source} 에서 상품 {len(catalog.products)}건 · "
                   f"고객 {len(catalog.customers)}건을 읽었습니다.")
        for warning in catalog.warnings:
            st.warning(warning, icon="⚠️")
        st.json(catalog.settings, expanded=False)
    except Exception as exc:
        st.error("**연결 실패**\n\n" + explain_sheet_error(exc))
    st.caption("Google Sheets 는 **읽기 전용** 스코프로만 접근합니다.")

    st.subheader("PDF 폰트")
    font = register_font()
    if font.ok:
        st.success(f"`{font.name}` — {font.path}")
        st.caption("한글·베트남어·₫ 를 모두 지원하는 폰트입니다.")
    else:
        st.error(font.warning)

    st.divider()
    st.caption("API 키는 화면과 로그에 마스킹되어 출력됩니다. "
               "`.env` 와 인증 파일은 `.gitignore` 에 등록되어 있습니다.")
