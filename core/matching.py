"""AI 가 뽑은 상품명을 실제 카탈로그에 붙인다.

규칙: 카탈로그에 없는 상품은 절대 만들어내지 않는다. 애매하면 사람이 고른다.
외부 라이브러리 없이 difflib(표준 라이브러리)만 쓴다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import SequenceMatcher

import pandas as pd

from core.extract import ExtractedRequest, RequestedItem

MIN_SCORE = 0.60          # 이보다 낮으면 후보로도 안 본다
EXACT_SCORE = 0.999       # 질의 단어가 상품명에 모두 들어 있는 경우
MAX_CANDIDATES = 6

# 매칭 상태
MATCHED = "matched"            # 상품 하나로 확정
AMBIGUOUS = "ambiguous"        # 후보 여러 개 - 사용자가 선택
NOT_FOUND = "not_found"        # 카탈로그에 없음 - 확인 필요
DISCONTINUED = "discontinued"  # 이름은 있으나 active=FALSE

# 재고 상태
STOCK_OK = "ok"
STOCK_SHORT = "short"
STOCK_UNKNOWN = "unknown"

# 영문 카탈로그 <-> 한국어 문의를 잇는 최소 사전.
# Claude 가 영문 키워드를 만들어주지만, Mock 모드와 오역 대비용 안전망이다.
SYNONYMS = {
    "monitor": ["monitor", "display", "lcd", "모니터"],
    "keyboard": ["keyboard", "키보드"],
    "mouse": ["mouse", "마우스"],
    "printer": ["printer", "프린터"],
    "paper": ["paper", "용지", "복사지"],
    "toner": ["toner", "cartridge", "토너"],
    "chair": ["chair", "의자"],
    "desk": ["desk", "table", "책상"],
    "cabinet": ["cabinet", "drawer", "서랍", "캐비넷"],
    "cable": ["cable", "케이블"],
    "dock": ["dock", "docking", "독"],
}


class MatchError(Exception):
    pass


@dataclass
class Candidate:
    product_id: str
    product_name: str
    category: str
    unit_price: Decimal
    stock_quantity: int
    score: float


@dataclass
class MatchedLine:
    requested: RequestedItem
    status: str
    candidates: list = field(default_factory=list)
    selected_product_id: str = ""
    notes: list = field(default_factory=list)

    @property
    def needs_attention(self) -> bool:
        return (self.status != MATCHED or not self.selected_product_id
                or self.requested.quantity <= 0)

    @property
    def selected(self) -> Candidate | None:
        return next((c for c in self.candidates if c.product_id == self.selected_product_id), None)


# ---------------------------------------------------------------- 점수

def _tokens(text: str) -> list:
    """'Dell 24" Monitor P2425H' -> ['dell','24','monitor','p2425h']"""
    return [t for t in re.split(r"[^0-9a-z가-힣]+", str(text).lower()) if t]


def _expand(tokens: list) -> set:
    """동의어를 펼친다. 'monitor' 질의가 '모니터' 상품명에도 걸리게."""
    out = set(tokens)
    for group in SYNONYMS.values():
        if out & set(group):
            out |= set(group)
    return out


def _score(query: str, product_text: str) -> float:
    q_tokens = _tokens(query)
    if not q_tokens:
        return 0.0
    p_tokens = _tokens(product_text)
    p_expanded = _expand(p_tokens)

    # 질의 단어가 상품명에 모두 등장하면 완전 일치로 본다.
    # 'monitor' 가 모니터 3종에 모두 1.0 이 되는 것은 의도된 동작 -> 사용자가 고른다.
    if all(t in p_expanded for t in _expand(q_tokens) & set(q_tokens)):
        return EXACT_SCORE

    hits = sum(1 for t in q_tokens if t in p_expanded)
    coverage = hits / len(q_tokens)
    fuzzy = SequenceMatcher(None, " ".join(q_tokens), " ".join(p_tokens)).ratio()
    return max(coverage * 0.95, fuzzy)


def _candidates(query: str, products: pd.DataFrame) -> list:
    scored = []
    for row in products.itertuples(index=False):
        score = _score(query, str(row.product_name) + " " + str(row.category))
        if score >= MIN_SCORE:
            scored.append(Candidate(
                product_id=str(row.product_id), product_name=str(row.product_name),
                category=str(row.category), unit_price=Decimal(str(row.unit_price)),
                stock_quantity=int(row.stock_quantity), score=round(score, 3)))
    scored.sort(key=lambda c: (-c.score, c.product_name))
    return scored[:MAX_CANDIDATES]


# ---------------------------------------------------------------- 매칭

def match_line(item: RequestedItem, products: pd.DataFrame) -> MatchedLine:
    """상품 한 줄을 카탈로그에 붙인다. 질의는 영문 키워드와 원문 둘 다 시도한다."""
    active = products[products["active"]] if "active" in products else products

    candidates = _candidates(item.search_term_en, active)
    if not candidates and item.name_as_written != item.search_term_en:
        candidates = _candidates(item.name_as_written, active)

    notes = []
    if item.quantity <= 0:
        notes.append("수량이 확인되지 않았습니다. 직접 입력하세요.")

    if not candidates:
        inactive = products[~products["active"]] if "active" in products else products.iloc[0:0]
        dead = _candidates(item.search_term_en, inactive)
        if dead:
            notes.append("'" + dead[0].product_name + "' 은(는) 단종(active=FALSE) 상품입니다.")
            return MatchedLine(item, DISCONTINUED, dead, "", notes)
        notes.append("카탈로그에서 찾을 수 없습니다. 상품을 직접 선택하거나 요청에서 제외하세요.")
        return MatchedLine(item, NOT_FOUND, [], "", notes)

    top = candidates[0].score
    tied = [c for c in candidates if c.score >= top - 1e-9]

    if len(tied) == 1 and top >= EXACT_SCORE:
        return MatchedLine(item, MATCHED, candidates, tied[0].product_id, notes)
    if len(candidates) == 1:
        notes.append("정확히 일치하지 않습니다 (유사도 "
                     + str(int(top * 100)) + "%). 상품이 맞는지 확인하세요.")
        return MatchedLine(item, MATCHED, candidates, candidates[0].product_id, notes)

    notes.append("유사 상품이 " + str(len(candidates)) + "개 있습니다. 하나를 선택하세요.")
    return MatchedLine(item, AMBIGUOUS, candidates, "", notes)


def match_request(request: ExtractedRequest, products: pd.DataFrame) -> list:
    return [match_line(item, products) for item in request.items]


# ---------------------------------------------------------------- 재고

@dataclass
class StockCheck:
    status: str
    ordered: int
    available: int
    shortage: int

    @property
    def label(self) -> str:
        return {STOCK_OK: "정상", STOCK_SHORT: "재고 부족",
                STOCK_UNKNOWN: "확인 필요"}[self.status]


def check_stock(line: MatchedLine) -> StockCheck:
    """주문 수량과 재고를 비교한다. 납기일은 여기서 판단하지 않는다 —
    현재 재고만으로는 입고 일정을 알 수 없다."""
    product = line.selected
    qty = max(0, line.requested.quantity)
    if product is None or line.status in (NOT_FOUND, DISCONTINUED) or qty == 0:
        return StockCheck(STOCK_UNKNOWN, qty, 0, 0)
    if product.stock_quantity >= qty:
        return StockCheck(STOCK_OK, qty, product.stock_quantity, 0)
    return StockCheck(STOCK_SHORT, qty, product.stock_quantity,
                      qty - product.stock_quantity)


def select_product(line: MatchedLine, product_id: str, products: pd.DataFrame) -> MatchedLine:
    """사용자가 상품을 직접 고르거나 바꿀 때. 카탈로그에 있는 ID 만 받는다."""
    row = products[products["product_id"].astype(str) == str(product_id)]
    if row.empty:
        raise MatchError("카탈로그에 없는 상품 ID 입니다: " + str(product_id))
    r = row.iloc[0]
    if "active" in row and not bool(r["active"]):
        raise MatchError("단종된 상품은 견적에 넣을 수 없습니다: " + str(r["product_name"]))
    chosen = Candidate(product_id=str(r["product_id"]), product_name=str(r["product_name"]),
                       category=str(r["category"]), unit_price=Decimal(str(r["unit_price"])),
                       stock_quantity=int(r["stock_quantity"]), score=1.0)
    others = [c for c in line.candidates if c.product_id != chosen.product_id]
    notes = [n for n in line.notes if "유사 상품" not in n and "찾을 수 없" not in n]
    return MatchedLine(line.requested, MATCHED, [chosen] + others, chosen.product_id, notes)
