"""RE NXT Sky API client for OAuth authentication and query execution."""

import time
from typing import Optional
from urllib.parse import urlencode
import requests


class RESkyAPI:
    """Client for interacting with Blackbaud RE NXT Sky API."""

    AUTH_URL = "https://oauth2.sky.blackbaud.com/authorization"
    TOKEN_URL = "https://oauth2.sky.blackbaud.com/token"
    API_BASE = "https://api.sky.blackbaud.com"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        subscription_key: str
    ):
        """
        Initialize the RE Sky API client.

        Args:
            client_id: OAuth client ID
            client_secret: OAuth client secret
            redirect_uri: OAuth redirect URI
            subscription_key: Blackbaud API subscription key
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.subscription_key = subscription_key

        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.token_expires_at: Optional[float] = None

    def get_authorization_url(self) -> str:
        """
        Generate the OAuth authorization URL.

        Returns:
            Authorization URL for user to visit
        """
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "offline_access"
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code_for_tokens(self, authorization_code: str) -> bool:
        """
        Exchange authorization code for access and refresh tokens.

        Args:
            authorization_code: Code received from OAuth callback

        Returns:
            True if successful
        """
        data = {
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }

        response = requests.post(self.TOKEN_URL, data=data)
        response.raise_for_status()

        tokens = response.json()
        self.access_token = tokens["access_token"]
        self.refresh_token = tokens.get("refresh_token")
        expires_in = tokens.get("expires_in", 3600)
        self.token_expires_at = time.time() + expires_in

        return True

    def refresh_access_token(self) -> bool:
        """
        Refresh the access token using the refresh token.

        Returns:
            True if successful
        """
        if not self.refresh_token:
            return False

        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }

        response = requests.post(self.TOKEN_URL, data=data)
        response.raise_for_status()

        tokens = response.json()
        self.access_token = tokens["access_token"]
        if "refresh_token" in tokens:
            self.refresh_token = tokens["refresh_token"]
        expires_in = tokens.get("expires_in", 3600)
        self.token_expires_at = time.time() + expires_in

        return True

    def is_authenticated(self) -> bool:
        """Check if the client has valid tokens."""
        return self.access_token is not None

    def is_token_expired(self) -> bool:
        """Check if the access token is expired or about to expire."""
        if not self.token_expires_at:
            return True
        return time.time() >= (self.token_expires_at - 60)

    def ensure_valid_token(self) -> bool:
        """
        Ensure we have a valid access token, refreshing if necessary.

        Returns:
            True if we have a valid token
        """
        if not self.is_authenticated():
            return False

        if self.is_token_expired():
            return self.refresh_access_token()

        return True

    def _get_headers(self) -> dict:
        """Get headers for API requests."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Bb-Api-Subscription-Key": self.subscription_key,
            "Content-Type": "application/json"
        }

    def execute_query(
        self,
        query_id: str,
        poll_interval: int = 10,
        status_callback=None
    ) -> list[dict]:
        """
        Execute a saved query and return results.

        Args:
            query_id: ID of the saved query to execute
            poll_interval: Seconds between status polls (default 10)
            status_callback: Optional callback function for status updates

        Returns:
            List of result rows as dictionaries
        """
        if not self.ensure_valid_token():
            raise RuntimeError("Not authenticated or unable to refresh token")

        start_url = f"{self.API_BASE}/query/v1/queries/{query_id}/results"
        response = requests.post(start_url, headers=self._get_headers())
        response.raise_for_status()

        job_data = response.json()
        job_id = job_data.get("id")

        if not job_id:
            raise RuntimeError("No job ID returned from query execution")

        time.sleep(poll_interval)

        job_url = f"{self.API_BASE}/query/v1/jobs/{job_id}"

        while True:
            response = requests.get(job_url, headers=self._get_headers())
            response.raise_for_status()

            job_status = response.json()
            status = job_status.get("status", "Unknown")

            if status_callback:
                status_callback(f"Status: {status}")

            if status == "Completed":
                return job_status.get("results", [])
            elif status in ["Failed", "Cancelled"]:
                raise RuntimeError(f"Query job {status.lower()}")

            time.sleep(poll_interval)

    def set_tokens(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_at: Optional[float] = None
    ):
        """
        Set tokens directly (e.g., from session state).

        Args:
            access_token: OAuth access token
            refresh_token: OAuth refresh token
            expires_at: Token expiration timestamp
        """
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_expires_at = expires_at

    def get_tokens(self) -> dict:
        """
        Get current tokens for storage.

        Returns:
            Dictionary with token data
        """
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.token_expires_at
        }
