"""환경설정 로더. 여기서만 os.environ 을 읽습니다 (UI/로직은 이 객체만 사용)."""
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
import os

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Config:
    anthropic_api_key: str
    anthropic_model: str
    google_credentials_file: str
    google_sheet_id: str

    @property
    def claude_ready(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def sheets_ready(self) -> bool:
        """서비스 계정 파일이 실제로 존재하고 시트 ID 가 있을 때만 True."""
        return bool(self.google_sheet_id) and bool(self.google_credentials_file) and Path(self.google_credentials_file).is_file()

    @property
    def mock_mode(self) -> bool:
        """Claude 키나 시트 설정 중 하나라도 없으면 Mock 모드."""
        return not (self.claude_ready and self.sheets_ready)


def load_config() -> Config:
    return Config(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5").strip(),
        google_credentials_file=os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip(),
        google_sheet_id=os.getenv("GOOGLE_SHEET_ID", "").strip(),
    )


def mask(secret: str) -> str:
    """로그·화면에 키 원문을 절대 남기지 않기 위한 마스킹."""
    if not secret:
        return "(없음)"
    return f"{secret[:7]}...{secret[-4:]}" if len(secret) > 14 else "*" * len(secret)
