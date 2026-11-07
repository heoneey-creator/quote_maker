"""가상 데이터 점검: 뒤 단계(매칭·계산·재고)가 이 전제에 의존한다."""
import pandas as pd
import pytest

from core.config import DATA_DIR


@pytest.fixture(scope="module")
def products():
    return pd.read_csv(DATA_DIR / "products.csv")


@pytest.fixture(scope="module")
def customers():
    return pd.read_csv(DATA_DIR / "customers.csv")


def test_ids_are_unique_and_complete(products, customers):
    assert products["product_id"].is_unique
    assert customers["customer_id"].is_unique
    assert not products.isna().any().any(), "products.csv 에 빈 셀이 있습니다"
    assert not customers.isna().any().any(), "customers.csv 에 빈 셀이 있습니다"


def test_prices_are_positive_and_sane(products):
    assert (products["unit_price"] > 0).all()
    assert (products["stock_quantity"] >= 0).all()
    # 판매가가 원가보다 낮으면 데이터 입력 오류
    assert (products["unit_price"] > products["cost_price"]).all()


def test_single_currency_for_demo(products):
    assert set(products["currency"]) == {"VND"}


def test_discount_rate_in_range(customers):
    assert customers["discount_rate"].between(0, 0.5).all()


def test_tier_maps_to_one_discount_rate(customers):
    # 같은 등급이 서로 다른 할인율을 가지면 계산 결과를 설명할 수 없다
    assert (customers.groupby("customer_tier")["discount_rate"].nunique() == 1).all()


def test_deliberate_edge_cases_exist(products):
    """이 세 가지가 있어야 재고 경고·비활성·유사상품 흐름을 테스트할 수 있다."""
    assert (products["stock_quantity"] == 0).any(), "재고 0 상품이 필요합니다"
    assert (~products["active"].astype(bool)).any(), "active=FALSE 상품이 필요합니다"
    monitors = products[products["category"] == "Monitor"]
    assert len(monitors) >= 3, "유사 상품 선택 흐름 테스트용 모니터가 3개 이상 필요합니다"


def test_settings_has_required_keys():
    s = pd.read_csv(DATA_DIR / "settings.csv")
    keys = set(s["key"])
    assert {"company_name", "company_address", "company_email",
            "quotation_valid_days", "default_currency", "tax_rate"} <= keys
    values = dict(zip(s["key"], s["value"]))
    assert 0 <= float(values["tax_rate"]) < 1, "tax_rate 는 0.10 같은 소수 형식입니다"
    assert int(values["quotation_valid_days"]) > 0
