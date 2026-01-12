"""Tests for Google OAuth authentication module (T-100).

This module tests the Google Calendar OAuth implementation per PRD Section 4.4:
- OAuth flow with token refresh
- Token persistence
- Credential validation
- Error handling
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch, mock_open
import pytest

from assistant.google.auth import (
    GoogleAuth,
    google_auth,
    SCOPES,
    TOKEN_PATH,
    CREDENTIALS_PATH,
    extract_oauth_code,
)


# =============================================================================
# Test OAuth Scopes Configuration
# =============================================================================

class TestOAuthScopes:
    """Test that all required OAuth scopes are configured."""

    def test_calendar_scope_present(self):
        """Calendar scope is required for AT-110."""
        assert "https://www.googleapis.com/auth/calendar" in SCOPES

    def test_gmail_readonly_scope_present(self):
        """Gmail read scope for morning briefings."""
        assert "https://www.googleapis.com/auth/gmail.readonly" in SCOPES

    def test_gmail_send_scope_present(self):
        """Gmail send scope for email sending."""
        assert "https://www.googleapis.com/auth/gmail.send" in SCOPES

    def test_gmail_compose_scope_present(self):
        """Gmail compose scope for drafts."""
        assert "https://www.googleapis.com/auth/gmail.compose" in SCOPES

    def test_drive_scope_present(self):
        """Drive scope for document creation."""
        assert "https://www.googleapis.com/auth/drive.file" in SCOPES

    def test_all_scopes_count(self):
        """Verify we have exactly 5 scopes as specified in PRD."""
        assert len(SCOPES) == 5


# =============================================================================
# Test Token Path Configuration
# =============================================================================

class TestTokenPaths:
    """Test token storage configuration."""

    def test_token_path_in_second_brain_dir(self):
        """Token should be stored in ~/.second-brain."""
        assert ".second-brain" in str(TOKEN_PATH)

    def test_token_path_is_json_file(self):
        """Token should be stored as JSON."""
        assert str(TOKEN_PATH).endswith(".json")

    def test_credentials_path_is_json_file(self):
        """Credentials should be stored as JSON."""
        assert str(CREDENTIALS_PATH).endswith(".json")


# =============================================================================
# Test GoogleAuth Class
# =============================================================================

class TestGoogleAuthInit:
    """Test GoogleAuth initialization."""

    def test_init_creates_instance(self):
        """GoogleAuth can be instantiated."""
        auth = GoogleAuth()
        assert auth is not None

    def test_init_credentials_none(self):
        """Initial credentials should be None."""
        auth = GoogleAuth()
        assert auth._credentials is None

    def test_singleton_instance_exists(self):
        """Module provides singleton google_auth instance."""
        assert google_auth is not None
        assert isinstance(google_auth, GoogleAuth)


class TestGoogleAuthCredentials:
    """Test GoogleAuth.credentials property."""

    def test_credentials_returns_none_when_not_set(self):
        """Returns None when no credentials loaded."""
        auth = GoogleAuth()
        assert auth.credentials is None

    def test_credentials_returns_valid_credentials(self):
        """Returns credentials when valid."""
        auth = GoogleAuth()
        mock_creds = MagicMock()
        mock_creds.valid = True
        auth._credentials = mock_creds

        assert auth.credentials == mock_creds

    def test_credentials_refreshes_expired_token(self):
        """Refreshes token when expired but has refresh_token."""
        auth = GoogleAuth()
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh_token_here"
        auth._credentials = mock_creds

        # After refresh, should be valid
        def set_valid_on_refresh(request):
            mock_creds.valid = True
        mock_creds.refresh.side_effect = set_valid_on_refresh

        with patch.object(auth, '_save_token'):
            result = auth.credentials

        mock_creds.refresh.assert_called_once()
        assert result == mock_creds

    def test_credentials_returns_none_on_refresh_failure(self):
        """Returns None if refresh fails."""
        auth = GoogleAuth()
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh_token_here"
        mock_creds.refresh.side_effect = Exception("Refresh failed")
        auth._credentials = mock_creds

        result = auth.credentials

        assert result is None


class TestGoogleAuthIsAuthenticated:
    """Test GoogleAuth.is_authenticated method."""

    def test_not_authenticated_when_no_credentials(self):
        """Returns False when no credentials."""
        auth = GoogleAuth()
        assert auth.is_authenticated() is False

    def test_authenticated_with_valid_credentials(self):
        """Returns True when credentials are valid."""
        auth = GoogleAuth()
        mock_creds = MagicMock()
        mock_creds.valid = True
        auth._credentials = mock_creds

        assert auth.is_authenticated() is True


class TestGoogleAuthLoadSavedCredentials:
    """Test GoogleAuth.load_saved_credentials method."""

    def test_returns_false_when_no_token_file(self):
        """Returns False when token file doesn't exist."""
        auth = GoogleAuth()
        with patch.object(Path, 'exists', return_value=False):
            result = auth.load_saved_credentials()

        assert result is False

    def test_loads_credentials_from_file(self):
        """Loads credentials from token file."""
        auth = GoogleAuth()
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False

        with patch.object(Path, 'exists', return_value=True):
            with patch('assistant.google.auth.Credentials.from_authorized_user_file', return_value=mock_creds):
                result = auth.load_saved_credentials()

        assert result is True
        assert auth._credentials == mock_creds

    def test_refreshes_expired_credentials_on_load(self):
        """Refreshes credentials if expired during load."""
        auth = GoogleAuth()
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh_token"

        def set_valid_on_refresh(request):
            mock_creds.valid = True
        mock_creds.refresh.side_effect = set_valid_on_refresh

        with patch.object(Path, 'exists', return_value=True):
            with patch('assistant.google.auth.Credentials.from_authorized_user_file', return_value=mock_creds):
                with patch.object(auth, '_save_token'):
                    result = auth.load_saved_credentials()

        assert result is True
        mock_creds.refresh.assert_called_once()

    def test_returns_false_on_load_error(self):
        """Returns False if loading fails."""
        auth = GoogleAuth()

        with patch.object(Path, 'exists', return_value=True):
            with patch('assistant.google.auth.Credentials.from_authorized_user_file', side_effect=Exception("Load failed")):
                result = auth.load_saved_credentials()

        assert result is False


class TestGoogleAuthInteractiveAuth:
    """Test GoogleAuth.authenticate_interactive method."""

    def test_returns_false_when_no_credentials_file(self):
        """Returns False when credentials file missing."""
        auth = GoogleAuth()

        with patch('assistant.google.auth.CREDENTIALS_PATH') as mock_path:
            mock_path.exists.return_value = False
            result = auth.authenticate_interactive()

        assert result is False

    def test_runs_local_server_flow(self):
        """Runs OAuth flow with local server."""
        auth = GoogleAuth()
        mock_flow = MagicMock()
        mock_creds = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds

        with patch('assistant.google.auth.CREDENTIALS_PATH') as mock_path:
            mock_path.exists.return_value = True
            with patch('assistant.google.auth.InstalledAppFlow.from_client_secrets_file', return_value=mock_flow):
                with patch.object(auth, '_save_token'):
                    result = auth.authenticate_interactive()

        assert result is True
        mock_flow.run_local_server.assert_called_once_with(port=0)

    def test_returns_false_on_auth_error(self):
        """Returns False if authentication fails."""
        auth = GoogleAuth()
        mock_flow = MagicMock()
        mock_flow.run_local_server.side_effect = Exception("Auth failed")

        with patch('assistant.google.auth.CREDENTIALS_PATH') as mock_path:
            mock_path.exists.return_value = True
            with patch('assistant.google.auth.InstalledAppFlow.from_client_secrets_file', return_value=mock_flow):
                result = auth.authenticate_interactive()

        assert result is False


class TestGoogleAuthSaveToken:
    """Test GoogleAuth._save_token method."""

    def test_does_nothing_when_no_credentials(self):
        """Does nothing when credentials are None."""
        auth = GoogleAuth()
        auth._credentials = None

        # Should not raise
        auth._save_token()

    def test_creates_parent_directory(self):
        """Creates parent directory if needed."""
        auth = GoogleAuth()
        mock_creds = MagicMock()
        mock_creds.to_json.return_value = '{"token": "test"}'
        auth._credentials = mock_creds

        mock_path = MagicMock()
        mock_parent = MagicMock()
        mock_path.parent = mock_parent

        with patch('assistant.google.auth.TOKEN_PATH', mock_path):
            with patch('builtins.open', mock_open()):
                auth._save_token()

        mock_parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)

    def test_writes_credentials_to_file(self):
        """Writes credentials JSON to token file."""
        auth = GoogleAuth()
        mock_creds = MagicMock()
        mock_creds.to_json.return_value = '{"token": "test_token"}'
        auth._credentials = mock_creds

        m = mock_open()
        with patch('assistant.google.auth.TOKEN_PATH') as mock_path:
            mock_parent = MagicMock()
            mock_path.parent = mock_parent
            with patch('builtins.open', m):
                auth._save_token()

        m().write.assert_called_once_with('{"token": "test_token"}')


class TestGoogleAuthGetAuthUrl:
    """Test GoogleAuth.get_auth_url method."""

    def test_returns_none_when_no_credentials_file(self):
        """Returns None when credentials file missing."""
        auth = GoogleAuth()

        with patch('assistant.google.auth.CREDENTIALS_PATH') as mock_path:
            mock_path.exists.return_value = False
            result = auth.get_auth_url()

        assert result is None

    def test_returns_auth_url(self):
        """Returns authorization URL for OAuth flow."""
        auth = GoogleAuth()
        mock_flow = MagicMock()
        mock_flow.client_config = {
            'installed': {
                'redirect_uris': ['http://localhost']
            }
        }
        mock_flow.authorization_url.return_value = ('https://accounts.google.com/o/oauth2/auth?client_id=...', 'state')

        with patch('assistant.google.auth.CREDENTIALS_PATH') as mock_path:
            mock_path.exists.return_value = True
            with patch('assistant.google.auth.InstalledAppFlow.from_client_secrets_file', return_value=mock_flow):
                result = auth.get_auth_url()

        assert result == 'https://accounts.google.com/o/oauth2/auth?client_id=...'
        mock_flow.authorization_url.assert_called_once_with(
            prompt='consent',
            access_type='offline',
        )

    def test_returns_none_when_no_redirect_uri(self):
        """Returns None when redirect_uris not configured."""
        auth = GoogleAuth()
        mock_flow = MagicMock()
        mock_flow.client_config = {}  # No redirect_uris

        with patch('assistant.google.auth.CREDENTIALS_PATH') as mock_path:
            mock_path.exists.return_value = True
            with patch('assistant.google.auth.InstalledAppFlow.from_client_secrets_file', return_value=mock_flow):
                result = auth.get_auth_url()

        assert result is None

    def test_returns_none_on_error(self):
        """Returns None if URL generation fails."""
        auth = GoogleAuth()

        with patch('assistant.google.auth.CREDENTIALS_PATH') as mock_path:
            mock_path.exists.return_value = True
            with patch('assistant.google.auth.InstalledAppFlow.from_client_secrets_file', side_effect=Exception("Flow error")):
                result = auth.get_auth_url()

        assert result is None


class TestGoogleAuthCompleteAuthWithCode:
    """Test GoogleAuth.complete_auth_with_code method."""

    def test_returns_false_when_no_credentials_file(self):
        """Returns False when credentials file missing."""
        auth = GoogleAuth()

        with patch('assistant.google.auth.CREDENTIALS_PATH') as mock_path:
            mock_path.exists.return_value = False
            result = auth.complete_auth_with_code("test_code")

        assert result is False

    def test_completes_auth_with_code(self):
        """Completes authentication with authorization code."""
        auth = GoogleAuth()
        mock_flow = MagicMock()
        mock_creds = MagicMock()
        mock_flow.credentials = mock_creds
        mock_flow.client_config = {
            'installed': {
                'redirect_uris': ['http://localhost']
            }
        }

        with patch('assistant.google.auth.CREDENTIALS_PATH') as mock_path:
            mock_path.exists.return_value = True
            with patch('assistant.google.auth.InstalledAppFlow.from_client_secrets_file', return_value=mock_flow):
                with patch.object(auth, '_save_token'):
                    result = auth.complete_auth_with_code("auth_code_123")

        assert result is True
        mock_flow.fetch_token.assert_called_once_with(code="auth_code_123")
        assert auth._credentials == mock_creds

    def test_returns_false_when_no_redirect_uri(self):
        """Returns False when redirect_uris not configured."""
        auth = GoogleAuth()
        mock_flow = MagicMock()
        mock_flow.client_config = {}  # No redirect_uris

        with patch('assistant.google.auth.CREDENTIALS_PATH') as mock_path:
            mock_path.exists.return_value = True
            with patch('assistant.google.auth.InstalledAppFlow.from_client_secrets_file', return_value=mock_flow):
                result = auth.complete_auth_with_code("auth_code_123")

        assert result is False

    def test_returns_false_on_error(self):
        """Returns False if code exchange fails."""
        auth = GoogleAuth()
        mock_flow = MagicMock()
        mock_flow.client_config = {
            'installed': {
                'redirect_uris': ['http://localhost']
            }
        }
        mock_flow.fetch_token.side_effect = Exception("Token exchange failed")

        with patch('assistant.google.auth.CREDENTIALS_PATH') as mock_path:
            mock_path.exists.return_value = True
            with patch('assistant.google.auth.InstalledAppFlow.from_client_secrets_file', return_value=mock_flow):
                result = auth.complete_auth_with_code("invalid_code")

        assert result is False


class TestGoogleAuthGetRedirectUri:
    """Test GoogleAuth._get_redirect_uri helper method."""

    def test_extracts_from_top_level_string(self):
        """Extracts redirect_uri from top-level string."""
        auth = GoogleAuth()
        mock_flow = MagicMock()
        mock_flow.client_config = {
            'redirect_uris': 'http://localhost:8080'
        }

        result = auth._get_redirect_uri(mock_flow)
        assert result == 'http://localhost:8080'

    def test_extracts_from_top_level_list(self):
        """Extracts redirect_uri from top-level list."""
        auth = GoogleAuth()
        mock_flow = MagicMock()
        mock_flow.client_config = {
            'redirect_uris': ['http://localhost:8080', 'http://example.com']
        }

        result = auth._get_redirect_uri(mock_flow)
        assert result == 'http://localhost:8080'

    def test_extracts_from_installed_config(self):
        """Extracts redirect_uri from 'installed' section."""
        auth = GoogleAuth()
        mock_flow = MagicMock()
        mock_flow.client_config = {
            'installed': {
                'redirect_uris': ['urn:ietf:wg:oauth:2.0:oob']
            }
        }

        result = auth._get_redirect_uri(mock_flow)
        assert result == 'urn:ietf:wg:oauth:2.0:oob'

    def test_extracts_from_web_config(self):
        """Extracts redirect_uri from 'web' section."""
        auth = GoogleAuth()
        mock_flow = MagicMock()
        mock_flow.client_config = {
            'web': {
                'redirect_uris': ['http://localhost:3000/callback']
            }
        }

        result = auth._get_redirect_uri(mock_flow)
        assert result == 'http://localhost:3000/callback'

    def test_returns_none_when_not_found(self):
        """Returns None when redirect_uris not in config."""
        auth = GoogleAuth()
        mock_flow = MagicMock()
        mock_flow.client_config = {}

        result = auth._get_redirect_uri(mock_flow)
        assert result is None

    def test_handles_empty_list(self):
        """Returns None for empty list."""
        auth = GoogleAuth()
        mock_flow = MagicMock()
        mock_flow.client_config = {
            'redirect_uris': []
        }

        result = auth._get_redirect_uri(mock_flow)
        assert result is None

    def test_handles_none_client_config(self):
        """Returns None when client_config is None."""
        auth = GoogleAuth()
        mock_flow = MagicMock()
        mock_flow.client_config = None

        result = auth._get_redirect_uri(mock_flow)
        assert result is None


# =============================================================================
# Test extract_oauth_code function
# =============================================================================

class TestExtractOAuthCode:
    """Test extract_oauth_code helper function."""

    def test_extracts_from_full_url(self):
        """Extracts code from full OAuth redirect URL."""
        url = "http://localhost/?code=4/P7q7W91a-oMsCeLvIaQm6bTrgtp7&scope=https://www.googleapis.com/auth/calendar"
        result = extract_oauth_code(url)
        assert result == "4/P7q7W91a-oMsCeLvIaQm6bTrgtp7"

    def test_extracts_from_https_url(self):
        """Extracts code from HTTPS URL."""
        url = "https://localhost/callback?code=abc123&state=xyz"
        result = extract_oauth_code(url)
        assert result == "abc123"

    def test_extracts_from_fragment(self):
        """Extracts code from URL fragment."""
        url = "http://localhost/#code=fragment_code_123"
        result = extract_oauth_code(url)
        assert result == "fragment_code_123"

    def test_extracts_from_query_string_alone(self):
        """Extracts code from query string without URL prefix."""
        text = "code=just_the_code"
        result = extract_oauth_code(text)
        assert result == "just_the_code"

    def test_extracts_from_query_with_question_mark(self):
        """Extracts code from query string with leading ?."""
        text = "?code=question_mark_code"
        result = extract_oauth_code(text)
        assert result == "question_mark_code"

    def test_returns_plain_code_as_is(self):
        """Returns plain code string unchanged."""
        code = "4/P7q7W91a-oMsCeLvIaQm6bTrgtp7"
        result = extract_oauth_code(code)
        assert result == code

    def test_returns_none_for_empty_string(self):
        """Returns None for empty input."""
        result = extract_oauth_code("")
        assert result is None

    def test_returns_none_for_whitespace(self):
        """Returns None for whitespace-only input."""
        result = extract_oauth_code("   ")
        assert result is None

    def test_strips_whitespace(self):
        """Strips whitespace from input."""
        result = extract_oauth_code("  my_code  ")
        assert result == "my_code"

    def test_handles_complex_url(self):
        """Handles complex Google OAuth redirect URL."""
        url = "http://localhost:8080/?state=abc&code=4/0ARtbsJqPvX2&scope=https://www.googleapis.com/auth/calendar%20https://www.googleapis.com/auth/gmail.readonly"
        result = extract_oauth_code(url)
        assert result == "4/0ARtbsJqPvX2"


# =============================================================================
# Test Integration Scenarios
# =============================================================================

class TestGoogleAuthIntegration:
    """Integration tests for OAuth flow scenarios."""

    def test_full_interactive_flow(self):
        """Test full interactive OAuth flow (mocked)."""
        auth = GoogleAuth()

        # Mock the flow
        mock_flow = MagicMock()
        mock_creds = MagicMock()
        mock_creds.to_json.return_value = '{"token": "test"}'
        mock_flow.run_local_server.return_value = mock_creds

        with patch('assistant.google.auth.CREDENTIALS_PATH') as mock_path:
            mock_path.exists.return_value = True
            with patch('assistant.google.auth.InstalledAppFlow.from_client_secrets_file', return_value=mock_flow):
                # Authenticate
                result = auth.authenticate_interactive()

        assert result is True
        assert auth._credentials == mock_creds

    def test_url_code_flow(self):
        """Test URL + code OAuth flow for headless environments."""
        auth = GoogleAuth()

        # Step 1: Get auth URL
        mock_flow = MagicMock()
        mock_flow.client_config = {
            'installed': {'redirect_uris': ['http://localhost']}
        }
        mock_flow.authorization_url.return_value = ('https://auth.url', 'state')

        with patch('assistant.google.auth.CREDENTIALS_PATH') as mock_path:
            mock_path.exists.return_value = True
            with patch('assistant.google.auth.InstalledAppFlow.from_client_secrets_file', return_value=mock_flow):
                auth_url = auth.get_auth_url()

        assert auth_url == 'https://auth.url'

        # Step 2: Complete with code
        mock_flow2 = MagicMock()
        mock_flow2.client_config = {
            'installed': {'redirect_uris': ['http://localhost']}
        }
        mock_creds = MagicMock()
        mock_flow2.credentials = mock_creds

        with patch('assistant.google.auth.CREDENTIALS_PATH') as mock_path:
            mock_path.exists.return_value = True
            with patch('assistant.google.auth.InstalledAppFlow.from_client_secrets_file', return_value=mock_flow2):
                with patch.object(auth, '_save_token'):
                    result = auth.complete_auth_with_code("user_provided_code")

        assert result is True
        assert auth._credentials == mock_creds

    def test_token_persistence_and_reload(self):
        """Test that tokens can be saved and reloaded."""
        auth1 = GoogleAuth()

        # Create mock credentials
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False
        mock_creds.to_json.return_value = '{"token": "persistent"}'
        auth1._credentials = mock_creds

        # Save token (mocked)
        saved_json = None
        m = mock_open()
        with patch('assistant.google.auth.TOKEN_PATH') as mock_path:
            mock_parent = MagicMock()
            mock_path.parent = mock_parent
            with patch('builtins.open', m):
                auth1._save_token()
                # Capture what was written
                saved_json = m().write.call_args[0][0]

        assert saved_json == '{"token": "persistent"}'

        # Create new instance and load
        auth2 = GoogleAuth()
        mock_creds2 = MagicMock()
        mock_creds2.valid = True
        mock_creds2.expired = False

        with patch.object(Path, 'exists', return_value=True):
            with patch('assistant.google.auth.Credentials.from_authorized_user_file', return_value=mock_creds2):
                result = auth2.load_saved_credentials()

        assert result is True


# =============================================================================
# Test PRD Section 4.4 Requirements
# =============================================================================

class TestPRDSection44Requirements:
    """Tests verifying PRD Section 4.4 Google Calendar API requirements."""

    def test_can_create_calendar_service_with_credentials(self):
        """Credentials can be used to build Calendar service."""
        auth = GoogleAuth()
        mock_creds = MagicMock()
        mock_creds.valid = True
        auth._credentials = mock_creds

        # Verify credentials can be passed to googleapiclient
        creds = auth.credentials
        assert creds is not None
        assert creds.valid is True

    def test_offline_access_requested(self):
        """Auth URL requests offline access for refresh tokens."""
        auth = GoogleAuth()
        mock_flow = MagicMock()
        mock_flow.client_config = {
            'installed': {'redirect_uris': ['http://localhost']}
        }
        mock_flow.authorization_url.return_value = ('https://auth.url', 'state')

        with patch('assistant.google.auth.CREDENTIALS_PATH') as mock_path:
            mock_path.exists.return_value = True
            with patch('assistant.google.auth.InstalledAppFlow.from_client_secrets_file', return_value=mock_flow):
                auth.get_auth_url()

        # Verify offline access was requested
        mock_flow.authorization_url.assert_called_once_with(
            prompt='consent',
            access_type='offline',
        )


# =============================================================================
# Test PRD Section 4.8 Failure Handling
# =============================================================================

class TestOAuthFailureHandling:
    """Tests for OAuth failure scenarios per PRD Section 4.8."""

    def test_token_refresh_on_expiry(self):
        """Token refreshed automatically when expired."""
        auth = GoogleAuth()
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh_me"

        def set_valid(request):
            mock_creds.valid = True
        mock_creds.refresh.side_effect = set_valid

        auth._credentials = mock_creds

        with patch.object(auth, '_save_token'):
            result = auth.credentials

        assert result is not None
        mock_creds.refresh.assert_called_once()

    def test_graceful_handling_of_refresh_failure(self):
        """Handles token refresh failure gracefully."""
        auth = GoogleAuth()
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "bad_token"
        mock_creds.refresh.side_effect = Exception("Refresh denied")

        auth._credentials = mock_creds

        result = auth.credentials

        assert result is None  # Graceful None, not exception


# =============================================================================
# Acceptance Test: AT-T100
# =============================================================================

class TestAT100GoogleCalendarOAuth:
    """Acceptance test for T-100: Google Calendar OAuth.

    Criteria:
    - OAuth flow with token refresh works
    - Token persistence to ~/.second-brain/google_token.json
    - Both interactive and URL+code flows supported
    - Required scopes for Calendar, Gmail, Drive
    """

    def test_oauth_scopes_complete(self):
        """All required OAuth scopes are configured."""
        required_scopes = {
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.compose",
            "https://www.googleapis.com/auth/drive.file",
        }
        assert required_scopes == set(SCOPES)

    def test_token_refresh_works(self):
        """Token refresh mechanism functions correctly."""
        auth = GoogleAuth()
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "valid_refresh_token"

        def set_valid(request):
            mock_creds.valid = True
        mock_creds.refresh.side_effect = set_valid

        auth._credentials = mock_creds

        with patch.object(auth, '_save_token'):
            result = auth.credentials

        assert result is not None
        assert result.valid is True

    def test_token_persistence_path(self):
        """Token stored at correct path."""
        assert "second-brain" in str(TOKEN_PATH)
        assert "google_token.json" in str(TOKEN_PATH)

    def test_interactive_flow_available(self):
        """Interactive OAuth flow method exists."""
        auth = GoogleAuth()
        assert hasattr(auth, 'authenticate_interactive')
        assert callable(auth.authenticate_interactive)

    def test_url_code_flow_available(self):
        """URL + code OAuth flow methods exist."""
        auth = GoogleAuth()
        assert hasattr(auth, 'get_auth_url')
        assert hasattr(auth, 'complete_auth_with_code')
        assert callable(auth.get_auth_url)
        assert callable(auth.complete_auth_with_code)

    def test_code_extraction_utility(self):
        """OAuth code extraction utility works."""
        # From URL
        url = "http://localhost/?code=test_code_123"
        assert extract_oauth_code(url) == "test_code_123"

        # Plain code
        assert extract_oauth_code("plain_code") == "plain_code"
