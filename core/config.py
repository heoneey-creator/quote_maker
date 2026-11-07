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
    # 배포 환경(Streamlit Cloud 등)에는 JSON 파일을 올릴 수 없다.
    # 그래서 JSON 내용을 환경변수 문자열로 받는 경로도 둔다.
    google_credentials_json: str = ""

    @property
    def claude_ready(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def credentials_json(self) -> str:
        """JSON 내용을 _FILE 쪽에 넣는 실수가 흔하다 (배포 Secrets 설정에서).
        값이 '{' 로 시작하면 경로가 아니라 내용으로 본다."""
        if self.google_credentials_json:
            return self.google_credentials_json
        if self.google_credentials_file.lstrip().startswith("{"):
            return self.google_credentials_file
        return ""

    @property
    def credentials_path(self) -> Path | None:
        """존재하는 인증 파일 경로, 없으면 None.

        경로가 255자를 넘거나 NUL 이 섞이면 is_file() 이 예외를 던진다.
        설정값 하나가 앱 전체를 죽이지 않게 여기서 흡수한다.
        """
        raw = self.google_credentials_file.strip()
        if not raw or self.credentials_json:
            return None
        try:
            path = Path(raw)
            return path if path.is_file() else None
        except (OSError, ValueError):
            return None

    @property
    def has_credentials(self) -> bool:
        return bool(self.credentials_json) or self.credentials_path is not None

    @property
    def credentials_label(self) -> str:
        """화면에 띄워도 안전한 설명. 원문을 쓰면 private key 가 노출된다."""
        if self.credentials_json:
            return "JSON 문자열 (" + f"{len(self.credentials_json):,}" + "자)"
        if self.credentials_path is not None:
            return "파일 " + self.credentials_path.name
        raw = self.google_credentials_file.strip()
        if not raw:
            return "(없음)"
        if len(raw) > 80:
            return "설정값이 비정상입니다 (경로인데 " + f"{len(raw):,}" + "자). " \
                   "JSON 내용을 넣으셨다면 GOOGLE_SERVICE_ACCOUNT_JSON 을 쓰세요."
        return "파일을 찾을 수 없음: " + raw

    @property
    def sheets_ready(self) -> bool:
        """인증 정보가 실제로 있고 시트 ID 가 있을 때만 True."""
        return bool(self.google_sheet_id) and self.has_credentials

    @property
    def mock_mode(self) -> bool:
        """Claude 키나 시트 설정 중 하나라도 없으면 Mock 모드."""
        return not (self.claude_ready and self.sheets_ready)


def load_config() -> Config:
    return Config(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5").strip(),
        google_credentials_file=os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip(),
        google_sheet_id=os.getenv("GOOGLE_SHEET_ID", "").strip(),
        google_credentials_json=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip(),
    )


def mask(secret: str) -> str:
    """로그·화면에 키 원문을 절대 남기지 않기 위한 마스킹."""
    if not secret:
        return "(없음)"
    return f"{secret[:7]}...{secret[-4:]}" if len(secret) > 14 else "*" * len(secret)
