# Google Sheets 설정 가이드

앱은 시트를 **읽기만** 합니다. 쓰기 권한을 주지 마세요.

## 1. 탭 3개 만들기

스프레드시트에 아래 이름의 탭을 **정확히 이 철자로** 만듭니다 (대소문자 구분).

| 탭 이름 | 첫 행 | 내용 |
|---|---|---|
| `Products` | 컬럼명 | 상품 목록 |
| `Customers` | 컬럼명 | 고객 목록 |
| `Settings` | `key`, `value` | 회사 정보·세율 |

기본 탭 이름이 `Sheet1` / `시트1` 이면 `Products` 로 바꾸고, 나머지 두 개는 하단 `+` 로 추가합니다.

## 2. 가상 데이터 넣기

가장 쉬운 방법은 복사-붙여넣기입니다.

1. `data/products.csv` 를 메모장으로 열어 전체 복사
2. 시트 `Products` 탭의 `A1` 셀 클릭 → 붙여넣기
3. 붙여넣기 직후 나타나는 아이콘에서 **"텍스트를 열로 분할"** 선택
4. `Customers`, `Settings` 도 같은 방식으로 반복

> 메뉴의 `파일 → 가져오기` 를 쓸 경우, **가져오기 위치**를 "현재 시트 바꾸기"로 두고 탭을 먼저 선택해야 엉뚱한 탭에 들어가지 않습니다.

## 3. 컬럼 규칙

**Products**

| 컬럼 | 형식 | 비고 |
|---|---|---|
| `product_id` | 문자 | **중복 불가** |
| `product_name` | 문자 | 매칭 기준이 되는 이름 |
| `category` | 문자 | Monitor, Keyboard, Mouse ... |
| `unit_price` | 숫자 | **세전** 판매 단가 |
| `cost_price` | 숫자 | 원가 (견적서에 노출되지 않음) |
| `stock_quantity` | 숫자 | 0 이상 |
| `currency` | 문자 | 데모에서는 전부 `VND` |
| `active` | `TRUE`/`FALSE` | `FALSE` 는 견적에서 제외 |

**Customers**

| 컬럼 | 형식 | 비고 |
|---|---|---|
| `customer_id` | 문자 | **중복 불가** |
| `company_name` | 문자 | 견적서에 인쇄됨 |
| `contact_name` | 문자 | |
| `email` | 문자 | 이메일 초안 수신자 |
| `customer_tier` | 문자 | STANDARD / SILVER / GOLD / PLATINUM |
| `discount_rate` | 숫자 | `0.05` = 5% (퍼센트가 아니라 **소수**) |

> ⚠️ 구글 시트에서 `0.05` 를 입력하면 자동으로 `5.00%` 로 표시될 수 있습니다. 표시만 바뀐 것이면 괜찮지만, `5` 라고 입력하면 500% 할인이 됩니다. `discount_rate` 열을 선택해 `서식 → 숫자 → 일반` 으로 두세요.

**Settings** (`key`, `value` 2열)

| key | 예시 값 | 쓰임 |
|---|---|---|
| `company_name` | VietOffice Supply Co., Ltd. | 견적서 헤더 |
| `company_address` | 12 Nguyen Hue Blvd, District 1, HCMC | 견적서 하단 |
| `company_email` | sales@vietoffice.example.com | 견적서 연락처 |
| `company_phone` | +84 28 3822 1234 | 견적서 연락처 |
| `quotation_valid_days` | `14` | 견적 유효기간 계산 |
| `default_currency` | `VND` | 금액 표기 |
| `tax_rate` | `0.10` | **세율. 코드에 고정하지 않고 여기서 읽습니다** |

베트남 부가세는 품목·시기에 따라 8% 감면이 적용되는 경우가 있습니다. 세율이 바뀌면 코드를 수정하지 말고 이 칸만 고치세요.

## 4. 서비스 계정에 공유

시트 우측 상단 **공유** → 아래 이메일 추가 → 권한은 **뷰어(Viewer)** → 전송.

```
<서비스계정이름>@<프로젝트ID>.iam.gserviceaccount.com
```

(이 주소는 `credentials.json` 의 `client_email` 값입니다. 알림 메일 보내기 체크는 해제해도 됩니다.)

## 5. Google Cloud 에서 API 켜기

[console.cloud.google.com](https://console.cloud.google.com/) → 본인 프로젝트 선택 →
**API 및 서비스 → 라이브러리** 에서 아래 두 개를 **사용 설정**합니다.

- Google Sheets API
- Google Drive API

## 6. 시트 ID 확인

주소창에서 `/d/` 와 `/edit` 사이 문자열입니다.

```
https://docs.google.com/spreadsheets/d/①여기가_시트_ID①/edit#gid=0
```

`.env` 의 `GOOGLE_SHEET_ID` 에 넣습니다.

## 자주 나는 오류

| 증상 | 원인 |
|---|---|
| `403 PERMISSION_DENIED` | 4번 공유 안 됨, 또는 5번 API 미사용 설정 |
| `404 Requested entity was not found` | 시트 ID 오타 |
| `WorksheetNotFound` | 탭 이름 철자 (`Products` ≠ `products`) |
| 금액이 0 으로 나옴 | 가격 셀이 텍스트로 저장됨 (쉼표·공백 제거) |
