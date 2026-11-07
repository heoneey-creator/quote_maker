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
