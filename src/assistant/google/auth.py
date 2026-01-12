import logging
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/drive.file",
]

TOKEN_PATH = Path.home() / ".second-brain" / "google_token.json"
CREDENTIALS_PATH = Path(__file__).parent.parent.parent.parent / "google_credentials.json"


def extract_oauth_code(text: str) -> str | None:
    candidate = text.strip()
    if not candidate:
        return None

    if candidate.startswith(("http://", "https://")):
        parsed = urlparse(candidate)
        for query in (parsed.query, parsed.fragment):
            if not query:
                continue
            qs = parse_qs(query)
            code_values = qs.get("code")
            if code_values and isinstance(code_values[0], str) and code_values[0]:
                return code_values[0]

    if "code=" in candidate:
        query = candidate.lstrip("?#")
        qs = parse_qs(query)
        code_values = qs.get("code")
        if code_values and isinstance(code_values[0], str) and code_values[0]:
            return code_values[0]

    return candidate


class GoogleAuth:
    def __init__(self):
        self._credentials: Credentials | None = None

    @property
    def credentials(self) -> Credentials | None:
        if self._credentials and self._credentials.valid:
            return self._credentials

        if self._credentials and self._credentials.expired and self._credentials.refresh_token:
            try:
                self._credentials.refresh(Request())
                self._save_token()
                return self._credentials
            except Exception as e:
                logger.error(f"Failed to refresh token: {e}")
                return None

        return None

    def is_authenticated(self) -> bool:
        return self.credentials is not None

    def load_saved_credentials(self) -> bool:
        if not TOKEN_PATH.exists():
            return False

        try:
            self._credentials = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
            if self._credentials and self._credentials.expired and self._credentials.refresh_token:
                self._credentials.refresh(Request())
                self._save_token()
            return self._credentials is not None and self._credentials.valid
        except Exception as e:
            logger.error(f"Failed to load saved credentials: {e}")
            return False

    def authenticate_interactive(self) -> bool:
        if not CREDENTIALS_PATH.exists():
            logger.error(f"Google credentials file not found at {CREDENTIALS_PATH}")
            return False

        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            self._credentials = flow.run_local_server(port=0)
            self._save_token()
            return True
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return False

    def _save_token(self) -> None:
        if not self._credentials:
            return

        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_PATH, "w") as f:
            f.write(self._credentials.to_json())

    def _get_redirect_uri(self, flow: InstalledAppFlow) -> str | None:
        client_config = flow.client_config or {}

        redirect_uris = client_config.get("redirect_uris")
        if isinstance(redirect_uris, str) and redirect_uris:
            return redirect_uris
        if isinstance(redirect_uris, (list, tuple)) and redirect_uris:
            first = redirect_uris[0]
            return first if isinstance(first, str) and first else None

        for config_key in ("installed", "web"):
            nested_redirect_uris = client_config.get(config_key, {}).get("redirect_uris", [])
            if isinstance(nested_redirect_uris, str) and nested_redirect_uris:
                return nested_redirect_uris
            if isinstance(nested_redirect_uris, (list, tuple)) and nested_redirect_uris:
                first = nested_redirect_uris[0]
                return first if isinstance(first, str) and first else None

        return None

    def get_auth_url(self) -> str | None:
        if not CREDENTIALS_PATH.exists():
            return None

        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            redirect_uri = self._get_redirect_uri(flow)
            if not redirect_uri:
                logger.error(
                    "No redirect_uris found in google_credentials.json (top-level or under 'installed'/'web')."
                )
                return None
            flow.redirect_uri = redirect_uri
            auth_url, _ = flow.authorization_url(
                prompt="consent",
                access_type="offline",
            )
            return auth_url
        except Exception as e:
            logger.error(f"Failed to generate auth URL: {e}")
            return None

    def complete_auth_with_code(self, code: str) -> bool:
        if not CREDENTIALS_PATH.exists():
            return False

        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            redirect_uri = self._get_redirect_uri(flow)
            if not redirect_uri:
                logger.error(
                    "No redirect_uris found in google_credentials.json (top-level or under 'installed'/'web')."
                )
                return False
            flow.redirect_uri = redirect_uri
            flow.fetch_token(code=code)
            self._credentials = flow.credentials
            self._save_token()
            return True
        except Exception as e:
            logger.error(f"Failed to complete auth with code: {e}")
            return False


google_auth = GoogleAuth()
