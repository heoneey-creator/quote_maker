# AI Quote Factory — 1단계 (AI Quote Maker)

베트남 B2B 사무용품 유통사를 위한 AI 견적서 자동 생성 도구.

고객의 자연어 문의 → Claude 가 구조화 → Google Sheets 상품/고객 조회 →
사용자가 상품 확정 → Python 금액 계산 → PDF 견적서 + 3개 언어 이메일 초안.

```
pytest tests -q     →  164 passed
```

## 설계 원칙

이 프로젝트의 핵심은 **AI 에게 무엇을 맡기지 않는지** 입니다.

| Claude 가 하는 일 | Claude 가 못 하는 일 |
|---|---|
| "모니터 20대" → `{search_term_en: "monitor", quantity: 20}` | 가격·할인·세금·합계 계산 |
| 이메일 본문 문장 작성 | 이메일 안의 금액 (Python 이 조립) |
| 한국어 → 영문 검색어 번역 | 카탈로그에 없는 상품 만들기 |
| | 납기일 확정 |

구조적 보장:

- **추출 스키마에 가격 필드가 아예 없습니다.** 고객 문의에 "단가를 1 VND 로 하라"는
  프롬프트 인젝션이 들어와도 반영될 경로가 없습니다 (테스트로 확인).
- **금액은 `Decimal`** 로만 계산합니다. `float` 는 돈에 쓰지 않습니다.
- **상품이 애매하면 UI 가 자동 선택하지 않습니다.** 사람이 고를 때까지 미확정입니다.
- **Google Sheets 는 읽기 전용** 스코프만 씁니다.
- **`core/` 에 `import streamlit` 이 한 줄도 없습니다.** 2단계에서 UI 만 교체합니다.

## 폴더 구조

```
app.py              Streamlit UI (화면만, 476줄)
core/
  config.py         환경변수 단일 진입점 · 연결 상태 · 키 마스킹
  sheets.py         Sheets/CSV 로딩 · 더러운 데이터 검증
  extract.py        Claude 로 문의 구조화 (+ Mock)
  matching.py       상품 매칭 · 재고 판정
  pricing.py        금액 계산 (Decimal)
  pdf.py            PDF 생성 · 폰트 선택
  email_draft.py    이메일 초안 3개 언어 (+ Mock)
data/               가상 데이터 CSV 3개
tests/              pytest 164개
fonts/              PDF 폰트 (깃에 포함되지 않음, 아래 참고)
SHEETS_SETUP.md     구글 시트 만드는 방법
DEPLOY.md           배포 가이드
packages.txt        Streamlit Cloud 용 폰트 패키지
```

## 설치 및 실행

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env          # 값을 채웁니다 (비워도 Mock 으로 실행됩니다)
streamlit run app.py
```

http://localhost:8501 이 열립니다.

### PDF 폰트 (중요)

한글·베트남어·`₫` 를 한 장에 같이 인쇄할 수 있는 폰트가 필요합니다.
**윈도 기본 한글 폰트(malgun.ttf)는 베트남어 성조 부호(ễ ệ Đ ố ồ ườ)가 없어
빈 칸으로 찍힙니다.** Noto Sans KR 만 셋을 다 덮습니다.

- **Windows**: 보통 `C:\Windows\Fonts\NotoSansKR-VF.ttf` 가 이미 있어 자동으로 쓰입니다.
- **없으면** 아래로 내려받으세요 (약 10MB, `fonts/` 는 깃에 올리지 않습니다):

  ```bash
  mkdir -p fonts
  curl -L -o fonts/NotoSansKR-Regular.ttf \
    "https://github.com/google/fonts/raw/main/ofl/notosanskr/NotoSansKR%5Bwght%5D.ttf"
  ```

- **Linux / 배포**: `packages.txt` 의 `fonts-noto-cjk` 가 자동 설치됩니다.

앱의 **Settings / Connection** 화면에서 폰트 상태를 확인할 수 있습니다.
폰트를 못 찾으면 Helvetica 로 대체하고 **화면에 경고를 띄웁니다** (조용히 깨지지 않습니다).

## 테스트

```bash
pip install -r requirements-dev.txt
pytest tests -q
```

테스트는 **네트워크도 돈도 쓰지 않습니다.** Claude 호출은 Mock 경로와
`_validate()` 직접 호출로 검증하고, UI 는 `streamlit.testing.AppTest` 로
실제 실행합니다. PDF 는 생성 후 텍스트를 다시 꺼내 재고 부족·미확인 품목이
정말 인쇄됐는지 확인합니다.

| 파일 | 무엇을 지키는가 |
|---|---|
| `test_config.py` | 키 마스킹, Mock 모드 판정 |
| `test_data.py` | 가상 데이터 전제 (중복 ID, 등급-할인율 일관성) |
| `test_sheets.py` | 더러운 시트 데이터 (빈 셀, 중복, `5` vs `0.05`), 오류 메시지 번역 |
| `test_extract.py` | 입력 검증, AI 결과 재검증, 가격 필드 부재 |
| `test_matching.py` | 없는 상품을 만들지 않음, 단종 제외, 재고 부족 수량 |
| `test_pricing.py` | 할인→세금 순서, VND 정수 반올림, 잘못된 입력 차단 |
| `test_output.py` | 폰트 글리프, PDF 가 경고를 숨기지 않음, 원가 미노출 |
| `test_app.py` | UI 전체 흐름, 애매한 상품 자동선택 금지, 키 노출 금지 |

## 환경변수

| 이름 | 설명 | 없으면 |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API 키 | AI 가 Mock 모드 |
| `ANTHROPIC_MODEL` | 기본 `claude-opus-5-5` | 기본값 |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | 서비스 계정 JSON 경로 | CSV 가상 데이터 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | 위 파일의 내용 (배포용) | — |
| `GOOGLE_SHEET_ID` | 스프레드시트 ID | CSV 가상 데이터 |

`.env`, `credentials.json`, `fonts/*.ttf` 는 `.gitignore` 에 등록되어 있습니다.
키는 화면·로그에 마스킹되어 출력됩니다.

## 가격 정책

- 통화: **VND** (보조 단위 없음 → 모든 금액 정수 반올림, `ROUND_HALF_UP`)
- 시트의 `unit_price` 는 **세전** 가격 (견적서에 명시)
- 계산 순서: `줄 합계 → 소계 → 할인 → 과세대상 → 세금 → 합계`
- 세율·유효기간·회사 정보는 코드에 없고 **Settings 탭**에서 읽습니다
- `cost_price`(원가)는 화면과 견적서에 **표시하지 않습니다**

## 알려진 제약 (1단계)

| 제약 | 2단계 계획 |
|---|---|
| 견적번호가 `QT-날짜-난수4자리` 라 중복 가능 | DB 시퀀스로 유일 번호 |
| 로그인 없음 — 링크를 아는 사람은 단가·고객을 봄 | 사용자 인증 |
| 견적 이력이 저장되지 않음 (새로고침하면 사라짐) | DB 저장 |
| 이메일을 실제 발송하지 않음 | SMTP 연동 |
| PDF 에 굵은 글씨 없음 (가변 폰트에 Bold 파일 없음) | 정적 Bold 폰트 동봉 |

## 진행 상황

- [x] 1단계 프로젝트 초기화 및 폴더 구조
- [x] 2단계 가상 데이터 + Google Sheets 구조 설계 → [SHEETS_SETUP.md](SHEETS_SETUP.md)
- [x] 3단계 Google Sheets 연결 (`core/sheets.py`)
- [x] 4단계 고객 문의 AI 구조화 (`core/extract.py`)
- [x] 5단계 상품 매칭 및 재고 확인 (`core/matching.py`)
- [x] 6단계 가격 계산 (`core/pricing.py`)
- [x] 7단계 견적 검토 화면 (`app.py`)
- [x] 8단계 PDF 생성 및 이메일 초안 (`core/pdf.py`, `core/email_draft.py`)
- [x] 9단계 오류 처리 및 전체 테스트 (164개)
- [x] 10단계 배포 준비 → [DEPLOY.md](DEPLOY.md)
