"""상품·고객·설정 데이터 로딩. Google Sheets 또는 CSV, 어느 쪽이든 같은 결과를 돌려준다.

여기서 모든 더러운 데이터를 걸러내므로, 뒤 단계는 깨끗한 DataFrame 만 본다.
Google Sheets 는 읽기 전용 스코프만 사용한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

import pandas as pd

from core.config import Config, DATA_DIR

READONLY_SCOPE = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

PRODUCT_COLUMNS = ["product_id", "product_name", "category", "unit_price",
                   "cost_price", "stock_quantity", "currency", "active"]
CUSTOMER_COLUMNS = ["customer_id", "company_name", "contact_name", "email",
                    "customer_tier", "discount_rate"]
REQUIRED_SETTINGS = ["company_name", "company_address", "company_email",
                     "quotation_valid_days", "default_currency", "tax_rate"]

SOURCE_SHEETS = "Google Sheets"
SOURCE_CSV = "CSV 가상 데이터"


class DataError(Exception):
    """데이터가 견적을 만들 수 없을 정도로 잘못된 경우."""


@dataclass
class Catalog:
    products: pd.DataFrame
    customers: pd.DataFrame
    settings: dict
    source: str
    warnings: list = field(default_factory=list)

    @property
    def is_mock_data(self) -> bool:
        return self.source == SOURCE_CSV

    @property
    def active_products(self) -> pd.DataFrame:
        return self.products[self.products["active"]].copy()

    @property
    def tax_rate(self) -> Decimal:
        return to_decimal(self.settings["tax_rate"], "tax_rate", lo=0, hi=1)

    @property
    def valid_days(self) -> int:
        days = self.settings["quotation_valid_days"]
        try:
            n = int(float(str(days).strip()))
        except ValueError:
            raise DataError("Settings 의 quotation_valid_days 가 숫자가 아닙니다: " + repr(days))
        if not 1 <= n <= 365:
            raise DataError("quotation_valid_days 가 1~365 범위를 벗어났습니다: " + str(n))
        return n

    @property
    def currency(self) -> str:
        return str(self.settings.get("default_currency", "VND")).strip() or "VND"


# ---------------------------------------------------------------- 값 변환

def to_decimal(raw, label: str, lo=None, hi=None) -> Decimal:
    """통화 기호와 쉼표가 섞인 값을 Decimal 로. 실패하면 DataError."""
    text = str(raw).strip().replace(",", "").replace(" ", "").replace(" ", "")
    text = "".join(c for c in text if c.isdigit() or c in ".-")
    if not text:
        raise DataError(label + " 값이 비어 있습니다: " + repr(raw))
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise DataError(label + " 값을 숫자로 읽을 수 없습니다: " + repr(raw))
    if lo is not None and value < lo:
        raise DataError(label + " 가 " + str(lo) + " 보다 작습니다: " + str(value))
    if hi is not None and value > hi:
        raise DataError(label + " 가 " + str(hi) + " 보다 큽니다: " + str(value))
    return value


def _numeric(series: pd.Series) -> pd.Series:
    """통화 기호·쉼표가 섞인 열을 숫자로. 실패한 칸은 NaN."""
    cleaned = (series.astype(str)
               .str.replace(r"[^\d.\-]", "", regex=True)
               .replace("", pd.NA))
    return pd.to_numeric(cleaned, errors="coerce")


_TRUE_WORDS = {"true", "1", "yes", "y", "참", "활성", "사용", "o"}


def _to_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin(_TRUE_WORDS)


# ---------------------------------------------------------------- 검증

def _clean_table(df: pd.DataFrame, columns: list, id_col: str,
                 numeric: dict, label: str, warnings: list) -> pd.DataFrame:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise DataError(label + " 에 필요한 컬럼이 없습니다: " + ", ".join(missing)
                        + "\n현재 컬럼: " + ", ".join(str(c) for c in df.columns))

    df = df[columns].copy()
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].astype(str).str.strip().replace({"nan": "", "None": ""})

    before = len(df)
    df = df[df[id_col] != ""].dropna(subset=[id_col])
    if before != len(df):
        warnings.append(label + ": " + id_col + " 가 빈 행 "
                        + str(before - len(df)) + "개를 건너뛰었습니다.")

    dups = df[df.duplicated(id_col, keep="first")][id_col].tolist()
    if dups:
        warnings.append(label + ": " + id_col + " 중복 " + str(len(dups))
                        + "건 — 첫 행만 사용합니다 (" + ", ".join(dups[:5]) + ").")
        df = df.drop_duplicates(id_col, keep="first")

    for col, bounds in numeric.items():
        lo, hi = bounds
        df[col] = _numeric(df[col])
        bad = df[col].isna() | (df[col] < lo) | (df[col] > hi)
        if bad.any():
            ids = df.loc[bad, id_col].tolist()
            warnings.append(label + ": " + col + " 값이 잘못된 행 " + str(int(bad.sum()))
                            + "개를 제외했습니다 ("
                            + ", ".join(str(i) for i in ids[:5]) + ").")
            df = df[~bad]

    if df.empty:
        raise DataError(label + " 에서 사용할 수 있는 행이 없습니다. 데이터를 확인하세요.")
    return df.reset_index(drop=True)


def _clean_products(df: pd.DataFrame, warnings: list) -> pd.DataFrame:
    df = _clean_table(df, PRODUCT_COLUMNS, "product_id",
                      {"unit_price": (1, 10 ** 12), "cost_price": (0, 10 ** 12),
                       "stock_quantity": (0, 10 ** 9)}, "Products", warnings)
    df["active"] = _to_bool(df["active"])
    df = df[df["product_name"] != ""].reset_index(drop=True)

    weird = df[df["unit_price"] < df["cost_price"]]["product_id"].tolist()
    if weird:
        warnings.append("Products: 판매가가 원가보다 낮은 상품이 있습니다 — 확인하세요 ("
                        + ", ".join(weird[:5]) + ").")
    currencies = set(df["currency"]) - {""}
    if len(currencies) > 1:
        warnings.append("Products: 통화가 섞여 있습니다 (" + ", ".join(sorted(currencies))
                        + "). 견적은 한 통화만 사용합니다.")
    if not df["active"].any():
        raise DataError("Products: active=TRUE 인 상품이 하나도 없습니다.")
    return df


def _clean_customers(df: pd.DataFrame, warnings: list) -> pd.DataFrame:
    # 구글 시트에서 5% 를 '5' 로 적으면 500% 할인이 된다. 0.9 상한으로 걸러낸다.
    df = _clean_table(df, CUSTOMER_COLUMNS, "customer_id",
                      {"discount_rate": (0, 0.9)}, "Customers", warnings)
    mixed = df.groupby("customer_tier")["discount_rate"].nunique()
    for tier, n in mixed.items():
        if n > 1:
            warnings.append("Customers: 등급 '" + str(tier) + "' 에 서로 다른 할인율이 섞여 있습니다.")
    no_email = df[~df["email"].str.contains("@", na=False)]["customer_id"].tolist()
    if no_email:
        warnings.append("Customers: 이메일 형식이 아닌 고객 " + str(len(no_email))
                        + "명 (" + ", ".join(no_email[:5]) + ").")
    return df


def _clean_settings(pairs: list, warnings: list) -> dict:
    settings = {}
    for row in pairs:
        if not row or not str(row[0]).strip():
            continue
        key = str(row[0]).strip()
        value = str(row[1]).strip() if len(row) > 1 else ""
        if key in settings:
            warnings.append("Settings: 키 '" + key + "' 가 중복입니다 — 첫 값을 사용합니다.")
            continue
        settings[key] = value

    if settings.get("key") == "value":  # 헤더 행이 그대로 들어온 경우
        settings.pop("key")
    missing = [k for k in REQUIRED_SETTINGS if not settings.get(k)]
    if missing:
        raise DataError("Settings 탭에 다음 항목이 없거나 비어 있습니다: " + ", ".join(missing))
    return settings


# ---------------------------------------------------------------- 소스별 읽기

def _load_from_csv(warnings: list) -> Catalog:
    for name in ("products", "customers", "settings"):
        if not (DATA_DIR / (name + ".csv")).is_file():
            raise DataError("가상 데이터 파일이 없습니다: data/" + name + ".csv")
    settings_df = pd.read_csv(DATA_DIR / "settings.csv", dtype=str).fillna("")
    return Catalog(
        products=_clean_products(pd.read_csv(DATA_DIR / "products.csv", dtype=str), warnings),
        customers=_clean_customers(pd.read_csv(DATA_DIR / "customers.csv", dtype=str), warnings),
        settings=_clean_settings(settings_df[["key", "value"]].values.tolist(), warnings),
        source=SOURCE_CSV,
        warnings=warnings,
    )


def _credentials(cfg: Config):
    """인증 정보를 파일 또는 환경변수 JSON 문자열에서 만든다."""
    from google.oauth2.service_account import Credentials

    raw = cfg.credentials_json
    if raw:
        import json
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DataError("서비스 계정 JSON 을 읽을 수 없습니다 (" + exc.msg + ").\n"
                            "Secrets 에 넣을 때는 홑따옴표로 감싸고 private_key 안의 "
                            "\\n 을 그대로 두세요.")
        return Credentials.from_service_account_info(info, scopes=READONLY_SCOPE)

    path = cfg.credentials_path
    if path is None:
        raise DataError("서비스 계정 인증 정보를 쓸 수 없습니다 — "
                        + cfg.credentials_label)
    return Credentials.from_service_account_file(str(path), scopes=READONLY_SCOPE)


def _load_from_sheets(cfg: Config, warnings: list) -> Catalog:
    import gspread

    book = gspread.authorize(_credentials(cfg)).open_by_key(cfg.google_sheet_id)
    sheets = book.worksheets()
    tabs = {ws.title.strip().lower(): ws for ws in sheets}

    def tab(name: str):
        ws = tabs.get(name.lower())
        if ws is None:
            raise DataError("'" + name + "' 탭을 찾을 수 없습니다. 현재 탭: "
                            + ", ".join(w.title for w in sheets))
        return ws

    def table(name: str) -> pd.DataFrame:
        rows = tab(name).get_all_values()
        if len(rows) < 2:
            raise DataError("'" + name + "' 탭에 데이터 행이 없습니다 (첫 행은 컬럼명이어야 합니다).")
        header = [h.strip() for h in rows[0]]
        return pd.DataFrame(rows[1:], columns=header)

    return Catalog(
        products=_clean_products(table("Products"), warnings),
        customers=_clean_customers(table("Customers"), warnings),
        settings=_clean_settings(tab("Settings").get_all_values(), warnings),
        source=SOURCE_SHEETS,
        warnings=warnings,
    )


def load_catalog(cfg: Config) -> Catalog:
    """시트가 설정되어 있으면 시트에서, 아니면 CSV 에서 읽는다.

    시트 연결이 실패하면 예외를 그대로 올린다. 조용히 가상 데이터로 바꾸면
    사용자가 실제 데이터를 보고 있다고 착각한다.
    """
    warnings = []
    if not cfg.sheets_ready:
        if cfg.google_sheet_id and not cfg.has_credentials:
            warnings.append("서비스 계정 인증 정보를 찾을 수 없어 가상 데이터를 사용합니다.")
        return _load_from_csv(warnings)
    return _load_from_sheets(cfg, warnings)


def explain_sheet_error(exc: Exception) -> str:
    """구글 API 오류를 초보자가 고칠 수 있는 말로 바꾼다."""
    text = str(exc)
    if "must not be an Office file" in text:
        return ("이 파일은 구글 스프레드시트가 아니라 업로드된 엑셀(.xlsx) 파일입니다.\n"
                "드라이브에서 파일을 열고 [파일] → [Google 스프레드시트로 저장] 을 누른 뒤, "
                "새로 생긴 파일의 ID 를 .env 의 GOOGLE_SHEET_ID 에 넣으세요.")
    if "PERMISSION_DENIED" in text or "403" in text:
        return ("시트 접근 권한이 없습니다.\n"
                "1) 시트를 서비스 계정 이메일(credentials.json 의 client_email)에 뷰어로 공유했는지\n"
                "2) Google Cloud 에서 Sheets API 와 Drive API 를 사용 설정했는지 확인하세요.")
    if "404" in text or "not found" in text.lower():
        return "시트를 찾을 수 없습니다. .env 의 GOOGLE_SHEET_ID 오타를 확인하세요."
    if "invalid_grant" in text or "JWT" in text:
        return "서비스 계정 인증이 거부되었습니다. credentials.json 이 유효한지, PC 시계가 정확한지 확인하세요."
    if isinstance(exc, DataError):
        return text
    return type(exc).__name__ + ": " + text[:300]
