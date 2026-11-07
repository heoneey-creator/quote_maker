"""3단계 점검: CSV 로딩, 더러운 데이터 걸러내기, 오류 메시지 번역."""
import pandas as pd
import pytest

from core.config import Config
from core.sheets import (
    SOURCE_CSV, Catalog, DataError, _clean_customers, _clean_products,
    _clean_settings, explain_sheet_error, load_catalog, to_decimal,
)

CSV_ONLY = Config(anthropic_api_key="", anthropic_model="m",
                  google_credentials_file="", google_sheet_id="")


def _products(**overrides):
    row = {"product_id": "P001", "product_name": "Monitor", "category": "Monitor",
           "unit_price": "1000", "cost_price": "800", "stock_quantity": "10",
           "currency": "VND", "active": "TRUE"}
    rows = overrides.pop("rows", [{}])
    return pd.DataFrame([{**row, **r} for r in rows])


# ------------------------------------------------------------ CSV 경로

def test_csv_load_gives_clean_catalog():
    cat = load_catalog(CSV_ONLY)
    assert cat.source == SOURCE_CSV and cat.is_mock_data
    assert len(cat.products) == 22
    assert len(cat.active_products) == 21  # P022 는 active=FALSE
    assert len(cat.customers) == 6
    assert cat.warnings == []
    assert cat.products["active"].dtype == bool


def test_settings_typed_accessors():
    cat = load_catalog(CSV_ONLY)
    assert str(cat.tax_rate) == "0.10"
    assert cat.valid_days == 14
    assert cat.currency == "VND"


# ------------------------------------------------------------ 숫자 변환

@pytest.mark.parametrize("raw,expected", [
    ("4,590,000", "4590000"), ("4 590 000", "4590000"),
    ("4590000 VND", "4590000"), ("0.10", "0.10"), (78000, "78000"),
])
def test_to_decimal_handles_messy_currency(raw, expected):
    assert str(to_decimal(raw, "price")) == expected


@pytest.mark.parametrize("raw", ["", "   ", "abc", None])
def test_to_decimal_rejects_garbage(raw):
    with pytest.raises(DataError):
        to_decimal(raw, "price")


def test_to_decimal_enforces_bounds():
    with pytest.raises(DataError):
        to_decimal("1.5", "tax_rate", lo=0, hi=1)


# ------------------------------------------------------------ 더러운 데이터

def test_missing_column_is_a_hard_error():
    df = _products().drop(columns=["unit_price"])
    with pytest.raises(DataError, match="unit_price"):
        _clean_products(df, [])


def test_duplicate_product_id_keeps_first_and_warns():
    df = _products(rows=[{"product_id": "P001", "product_name": "A"},
                         {"product_id": "P001", "product_name": "B"}])
    warns = []
    out = _clean_products(df, warns)
    assert len(out) == 1 and out.iloc[0]["product_name"] == "A"
    assert any("중복" in w for w in warns)


def test_rows_with_unreadable_price_are_dropped():
    df = _products(rows=[{"product_id": "P001"},
                         {"product_id": "P002", "unit_price": "문의"}])
    warns = []
    out = _clean_products(df, warns)
    assert out["product_id"].tolist() == ["P001"]
    assert any("unit_price" in w for w in warns)


def test_blank_id_rows_are_skipped():
    df = _products(rows=[{"product_id": "P001"}, {"product_id": ""}])
    warns = []
    assert len(_clean_products(df, warns)) == 1
    assert any("빈 행" in w for w in warns)


def test_active_accepts_various_spellings():
    df = _products(rows=[{"product_id": "P1", "active": "TRUE"},
                         {"product_id": "P2", "active": "yes"},
                         {"product_id": "P3", "active": "1"},
                         {"product_id": "P4", "active": "FALSE"},
                         {"product_id": "P5", "active": ""}])
    out = _clean_products(df, [])
    assert out["active"].tolist() == [True, True, True, False, False]


def test_all_inactive_is_a_hard_error():
    df = _products(rows=[{"active": "FALSE"}])
    with pytest.raises(DataError, match="active=TRUE"):
        _clean_products(df, [])


def test_percent_typed_as_whole_number_is_rejected():
    """discount_rate 에 5 (=500%) 를 넣으면 행이 제외되고, 남는 게 없으면 오류."""
    df = pd.DataFrame([{"customer_id": "C001", "company_name": "A", "contact_name": "B",
                        "email": "a@b.com", "customer_tier": "GOLD", "discount_rate": "5"}])
    with pytest.raises(DataError):
        _clean_customers(df, [])


def test_bad_email_only_warns():
    df = pd.DataFrame([{"customer_id": "C001", "company_name": "A", "contact_name": "B",
                        "email": "없음", "customer_tier": "GOLD", "discount_rate": "0.05"}])
    warns = []
    assert len(_clean_customers(df, warns)) == 1
    assert any("이메일" in w for w in warns)


def test_settings_missing_key_is_a_hard_error():
    with pytest.raises(DataError, match="tax_rate"):
        _clean_settings([["company_name", "X"]], [])


def test_settings_tolerates_header_row_and_blanks():
    rows = [["key", "value"], [], ["company_name", "X"], ["company_address", "Y"],
            ["company_email", "a@b.com"], ["quotation_valid_days", "14"],
            ["default_currency", "VND"], ["tax_rate", "0.1"], ["  ", ""]]
    out = _clean_settings(rows, [])
    assert out["company_name"] == "X" and "key" not in out


def test_valid_days_out_of_range_is_rejected():
    cat = Catalog(products=_products(), customers=_products(), source="x",
                  settings={"quotation_valid_days": "0", "tax_rate": "0.1"})
    with pytest.raises(DataError, match="1~365"):
        _ = cat.valid_days


# ------------------------------------------------------------ 오류 메시지

@pytest.mark.parametrize("message,expect", [
    ("This operation is not supported for this document. The document must not be an Office file.", "엑셀"),
    ("APIError [403]: PERMISSION_DENIED", "공유"),
    ("APIError [404]: Requested entity was not found", "GOOGLE_SHEET_ID"),
    ("invalid_grant: JWT signature", "시계"),
])
def test_sheet_errors_become_actionable_korean(message, expect):
    assert expect in explain_sheet_error(RuntimeError(message))


# ------------------------------------------------------------ 배포(10단계) 경로

def test_credentials_can_come_from_a_json_string():
    """Streamlit Cloud 에는 JSON 파일을 올릴 수 없다. 문자열 경로가 동작해야 한다."""
    cfg = Config(anthropic_api_key="", anthropic_model="m",
                 google_credentials_file="", google_sheet_id="abc",
                 google_credentials_json='{"type":"service_account"}')
    assert cfg.has_credentials and cfg.sheets_ready


def test_broken_credentials_json_gives_a_clear_error():
    from core.sheets import _credentials
    cfg = Config(anthropic_api_key="", anthropic_model="m",
                 google_credentials_file="", google_sheet_id="abc",
                 google_credentials_json="not json at all")
    with pytest.raises(DataError, match="JSON"):
        _credentials(cfg)


def test_sheet_id_without_credentials_falls_back_to_csv_with_a_warning():
    cfg = Config(anthropic_api_key="", anthropic_model="m",
                 google_credentials_file="missing.json", google_sheet_id="abc")
    catalog = load_catalog(cfg)
    assert catalog.source == SOURCE_CSV
    assert any("인증 정보" in w for w in catalog.warnings)
