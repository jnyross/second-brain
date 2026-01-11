import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

from assistant.config import settings

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
    
    def get_auth_url(self) -> str | None:
        if not CREDENTIALS_PATH.exists():
            return None
        
        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
            auth_url, _ = flow.authorization_url(prompt="consent")
            return auth_url
        except Exception as e:
            logger.error(f"Failed to generate auth URL: {e}")
            return None
    
    def complete_auth_with_code(self, code: str) -> bool:
        if not CREDENTIALS_PATH.exists():
            return False
        
        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
            flow.fetch_token(code=code)
            self._credentials = flow.credentials
            self._save_token()
            return True
        except Exception as e:
            logger.error(f"Failed to complete auth with code: {e}")
            return False


google_auth = GoogleAuth()
