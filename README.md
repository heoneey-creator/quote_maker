# AI Quote Factory — 1단계 (AI Quote Maker)

베트남 B2B 사무용품 유통사를 위한 AI 견적서 자동 생성 도구.
고객의 자연어 문의 → Claude 가 구조화 → Google Sheets 상품/고객 조회 → Python 금액 계산 → PDF 견적서.

## 설계 원칙

- **금액 계산은 Python 에서만.** Claude 에는 계산을 맡기지 않습니다.
- **Claude 는 상품·가격을 만들어내지 않습니다.** 시트에 있는 상품만 매칭합니다.
- **Google Sheets 는 읽기 전용.**
- **`core/` 에는 Streamlit import 이 없습니다.** 2단계에서 UI를 FastAPI 로 교체해도 로직을 그대로 재사용합니다.
- API 키가 없으면 **Mock 모드**로 동작하고, 화면에 항상 Mock 임을 표시합니다.

## 폴더 구조

```
app.py            Streamlit UI (화면만)
core/
  config.py       환경변수 로딩 · 연결 상태 · 키 마스킹
data/
  products.csv    상품 22종 (VND)
  customers.csv   고객 6곳 (등급별 할인율)
  settings.csv    회사 정보 · 세율
tests/            pytest
.env.example      환경변수 샘플
.streamlit/       테마
SHEETS_SETUP.md   구글 시트 만드는 방법
```

## 설치 및 실행

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

copy .env.example .env          # Windows (mac/linux: cp)
streamlit run app.py
```

브라우저에서 http://localhost:8501 이 열립니다.
`.env` 가 비어 있어도 **Mock 모드**로 실행됩니다.

## 테스트

```bash
pytest tests -q
```

## 환경변수

| 이름 | 설명 | 없으면 |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API 키 | Mock 모드 |
| `ANTHROPIC_MODEL` | 모델 ID (기본 `claude-sonnet-5-5`) | 기본값 사용 |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | 서비스 계정 JSON 경로 | CSV 가상 데이터 사용 |
| `GOOGLE_SHEET_ID` | 스프레드시트 ID | CSV 가상 데이터 사용 |

`.env` 와 `credentials/` 는 `.gitignore` 에 등록되어 있습니다. 키는 화면·로그에 마스킹되어 출력됩니다.

## 가격 정책 (전 단계 공통)

- 통화: **VND**
- 시트의 `unit_price` 는 **세전** 가격
- 계산 순서: `상품별 합계 → 고객 등급 할인 → 세금(Settings.tax_rate)` — 세율은 코드에 고정하지 않습니다.

## 진행 상황

- [x] 1단계 프로젝트 초기화 및 폴더 구조
- [x] 2단계 가상 데이터 + Google Sheets 구조 설계 → [SHEETS_SETUP.md](SHEETS_SETUP.md)
- [ ] 3단계 Google Sheets 연결
- [ ] 4단계 고객 문의 AI 구조화
- [ ] 5단계 상품 매칭 및 재고 확인
- [ ] 6단계 가격 계산
- [ ] 7단계 견적 검토 화면
- [ ] 8단계 PDF 생성 및 이메일 초안
- [ ] 9단계 오류 처리 및 전체 테스트
- [ ] 10단계 배포 준비
