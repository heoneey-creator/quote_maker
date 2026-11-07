"""AI Quote Factory - Streamlit UI. 비즈니스 로직은 core/ 에만 둡니다."""
import streamlit as st

from core.config import load_config, mask

st.set_page_config(page_title="AI Quote Factory", page_icon="📄", layout="wide")

cfg = load_config()

PAGES = ["Dashboard", "New Quotation", "Product Search", "Quotation Preview", "Settings / Connection"]

with st.sidebar:
    st.title("📄 AI Quote Factory")
    st.caption("B2B 견적 자동화 · 1단계")
    page = st.radio("메뉴", PAGES, label_visibility="collapsed")
    st.divider()
    if cfg.mock_mode:
        st.warning("🧪 **MOCK 모드**\n\nAI 응답과 상품 데이터가 가상입니다.")
    else:
        st.success("🟢 **실제 연동 모드**\n\nClaude API + Google Sheets")

if cfg.mock_mode:
    st.info("🧪 현재 **MOCK 모드**입니다. 화면의 AI 결과·상품 데이터는 실제 값이 아닙니다.", icon="🧪")

if page == "Dashboard":
    st.header("Dashboard")
    c1, c2, c3 = st.columns(3)
    c1.metric("Claude API", "연결됨" if cfg.claude_ready else "미설정")
    c2.metric("Google Sheets", "연결됨" if cfg.sheets_ready else "미설정")
    c3.metric("동작 모드", "MOCK" if cfg.mock_mode else "LIVE")
    st.divider()
    st.subheader("견적 작성 흐름")
    st.markdown(
        "1. 고객 문의 입력 → 2. AI 요청 분석 → 3. 상품 자동 매칭 → "
        "4. 가격·재고 확인 → 5. 견적 검토 → 6. PDF 다운로드"
    )
    st.caption("표시 가격은 모두 **세전(VAT 별도)** 기준이며 통화는 VND 입니다.")

elif page == "Settings / Connection":
    st.header("Settings / Connection Status")
    st.subheader("Claude API")
    st.write(f"키: `{mask(cfg.anthropic_api_key)}` · 모델: `{cfg.anthropic_model}`")
    if not cfg.claude_ready:
        st.error("`.env` 의 `ANTHROPIC_API_KEY` 가 비어 있습니다. (console.anthropic.com 에서 발급)")

    st.subheader("Google Sheets")
    st.write(f"인증 파일: `{cfg.google_credentials_file or '(없음)'}` · 시트 ID: `{mask(cfg.google_sheet_id)}`")
    if not cfg.sheets_ready:
        st.error("서비스 계정 JSON 파일 경로와 시트 ID 를 `.env` 에 설정하세요. (3단계에서 안내)")
    st.caption("Google Sheets 는 **읽기 전용**으로만 사용합니다.")
    st.divider()
    st.caption("키 원문은 화면·로그에 출력되지 않습니다. `.env` 와 인증 파일은 `.gitignore` 에 등록되어 있습니다.")

else:
    st.header(page)
    st.info(f"**{page}** 화면은 다음 단계에서 구현합니다.")
