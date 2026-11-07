"""1단계 자체 점검: 설정 로딩과 Mock 모드 판정, 키 마스킹."""
from core.config import Config, mask


def _cfg(key="", creds="", sheet=""):
    return Config(anthropic_api_key=key, anthropic_model="m", google_credentials_file=creds, google_sheet_id=sheet)


def test_mock_mode_when_nothing_set():
    assert _cfg().mock_mode is True


def test_mock_mode_when_only_claude_set():
    assert _cfg(key="sk-ant-x").claude_ready is True
    assert _cfg(key="sk-ant-x").mock_mode is True


def test_sheets_not_ready_if_credentials_file_missing():
    # 경로만 적혀 있고 파일이 없으면 연결 가능으로 보지 않는다.
    assert _cfg(creds="no/such/file.json", sheet="abc").sheets_ready is False


def test_mask_never_leaks_full_key():
    secret = "sk-ant-api03-1234567890abcdef"
    out = mask(secret)
    assert secret not in out and out.startswith("sk-ant-")
    assert mask("") == "(없음)"
    assert mask("short") == "*****"


# ------------------------------------------------------- 배포 환경에서 터진 버그

def _cfg2(file="", json_="", sheet="abc"):
    return Config(anthropic_api_key="", anthropic_model="m",
                  google_credentials_file=file, google_sheet_id=sheet,
                  google_credentials_json=json_)


FAKE_JSON = ('{"type":"service_account","project_id":"p","private_key":'
             '"-----BEGIN PRIVATE KEY-----\nSUPERSECRETKEYMATERIAL' + "A" * 600
             + '\n-----END PRIVATE KEY-----\n","client_email":"a@b.iam.gserviceaccount.com"}')


def test_overlong_credentials_path_does_not_crash():
    """Streamlit Cloud 에서 _FILE 에 JSON 을 넣어 OSError(파일명 너무 김)로 앱이 죽었다."""
    cfg = _cfg2(file="x" * 5000)
    assert cfg.credentials_path is None
    assert cfg.has_credentials is False      # 예외가 아니라 False
    assert cfg.sheets_ready is False
    assert cfg.mock_mode is True


def test_path_with_nul_byte_does_not_crash():
    cfg = _cfg2(file="creds\x00.json")
    assert cfg.credentials_path is None and cfg.has_credentials is False


def test_json_pasted_into_the_file_variable_is_detected():
    """흔한 실수를 조용히 실패시키지 않고 알아서 인식한다."""
    cfg = _cfg2(file=FAKE_JSON)
    assert cfg.credentials_json == FAKE_JSON
    assert cfg.has_credentials and cfg.sheets_ready
    assert cfg.credentials_path is None


def test_credentials_label_never_leaks_the_private_key():
    """Settings 화면이 이 값을 출력한다. 키가 섞여 나가면 안 된다."""
    for cfg in (_cfg2(file=FAKE_JSON), _cfg2(json_=FAKE_JSON), _cfg2(file="x" * 5000)):
        label = cfg.credentials_label
        assert "SUPERSECRETKEY" not in label
        assert "BEGIN PRIVATE KEY" not in label
        assert len(label) < 200


def test_credentials_label_explains_the_mistake():
    assert "GOOGLE_SERVICE_ACCOUNT_JSON" in _cfg2(file="x" * 5000).credentials_label
    assert _cfg2().credentials_label == "(없음)"
    assert "찾을 수 없음" in _cfg2(file="missing.json").credentials_label


def test_explicit_json_variable_wins_over_file():
    cfg = _cfg2(file="some/path.json", json_=FAKE_JSON)
    assert cfg.credentials_json == FAKE_JSON
    assert cfg.credentials_path is None
