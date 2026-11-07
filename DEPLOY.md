# 배포 가이드 (10단계)

## 배포 전 점검

```bash
pytest tests -q          # 161개 전부 통과해야 합니다
```

`.env` 와 `credentials.json` 이 **커밋되지 않았는지** 확인:

```bash
git ls-files | grep -E "\.env$|credentials|\.ttf$"   # 아무것도 안 나와야 정상
```

## Streamlit Community Cloud (무료, 가장 쉬움)

### 1. 앱 만들기

[share.streamlit.io](https://share.streamlit.io) → **New app** →
저장소 `heoneey-creator/quote_maker`, 브랜치 `main`, 파일 `app.py`.

### 2. Secrets 입력

**Advanced settings → Secrets** 에 아래를 붙여넣습니다.
Streamlit Cloud 는 여기 적은 값을 환경변수로도 넣어주므로, 코드 수정이 필요 없습니다.

```toml
ANTHROPIC_API_KEY = "sk-ant-..."
ANTHROPIC_MODEL = "claude-opus-5-5"
GOOGLE_SHEET_ID = "..."
GOOGLE_SERVICE_ACCOUNT_JSON = '{"type":"service_account","project_id":"...","private_key":"-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n", ... }'
```

> ⚠️ 클라우드에는 `credentials.json` **파일을 올릴 수 없습니다.**
> 그래서 `GOOGLE_SERVICE_ACCOUNT_JSON` 에 파일 내용을 그대로 넣습니다.
> `private_key` 안의 줄바꿈은 `\n` 문자 그대로 유지하고, 전체를 **홑따옴표**로 감싸세요
> (쌍따옴표로 감싸면 `\n` 이 깨집니다).

### 3. 폰트

저장소의 [packages.txt](packages.txt) 에 `fonts-noto-cjk` 가 들어 있어
Streamlit Cloud 가 배포 시 자동 설치합니다. 이 폰트가 없으면 PDF 의
한글과 베트남어가 깨집니다. 배포 후 **Settings / Connection** 화면의
"PDF 폰트" 항목이 초록색인지 확인하세요.

### 4. 접근 제한

이 앱에는 로그인이 없습니다. 상품 원가는 화면에 표시하지 않지만,
**단가·고객 목록은 링크를 아는 사람이면 모두 볼 수 있습니다.**

Streamlit Cloud 의 **Settings → Sharing** 에서 앱을 비공개로 바꾸고
볼 수 있는 이메일을 지정하세요. 사내 사용이라면 반드시 설정해야 합니다.

## 로컬 PC 에서 사내 공유

```bash
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

같은 네트워크에서 `http://<내PC주소>:8501` 로 접속됩니다.
인증이 없으므로 사내망에서만 쓰세요.

## 비용

| 항목 | 비용 |
|---|---|
| Streamlit Cloud | 무료 |
| Google Sheets API | 무료 (읽기 할당량 충분) |
| Claude API | 호출당 과금 |

견적 1건당 Claude 호출은 2회(요청 분석 + 이메일 초안)입니다.
입력이 짧아 1건당 비용은 매우 작지만, 모델을 바꾸면 달라집니다.
`.env` 의 `ANTHROPIC_MODEL` 을 `claude-haiku-5-5` 로 바꾸면 훨씬 저렴해집니다
(품질은 떨어집니다). 현재 기본값은 가장 성능이 좋은 `claude-opus-5-5` 입니다.

시트 조회는 `@st.cache_data` 로 캐시되므로 클릭마다 API 를 호출하지 않습니다.
데이터를 시트에서 수정한 뒤에는 사이드바의 **🔄 데이터 다시 읽기** 를 누르세요.

## 2단계로 넘어갈 때

지금 구조에서 바뀌는 것은 `app.py` 하나입니다.

| 유지 | 교체 |
|---|---|
| `core/sheets.py` 데이터 로딩 | `app.py` → FastAPI 라우터 |
| `core/extract.py` AI 구조화 | |
| `core/matching.py` 상품 매칭 | |
| `core/pricing.py` 금액 계산 | 견적번호 생성만 DB 시퀀스로 |
| `core/pdf.py` PDF | |
| `core/email_draft.py` 이메일 | 실제 발송 추가 |
| `tests/` (UI 테스트 제외) | `tests/test_app.py` |

`core/` 에는 `import streamlit` 이 한 줄도 없습니다. 확인:

```bash
grep -rn "streamlit" core/     # 결과가 없어야 정상
```
