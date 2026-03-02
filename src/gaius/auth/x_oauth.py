"""X (Twitter) OAuth 2.0 Authorization Code Flow with PKCE.

Implements the OAuth 2.0 flow required for X API v2 bookmark access.
Uses PKCE (Proof Key for Code Exchange) for enhanced security.

Scopes required:
- bookmark.read: Read bookmarks
- users.read: Read user profile
- tweet.read: Read tweet content
- offline.access: Get refresh token for long-lived access

Guru Meditation Codes:
- #XB.00000001.NOTOKEN: No OAuth tokens found for user
- #XB.00000002.TOKENEXP: Token expired, no refresh token
- #XB.00000003.NOCLIENT: X_CLIENT_ID not configured
"""

import base64
import hashlib
import secrets
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg
import httpx


class XOAuthError(Exception):
    """X OAuth-related errors with Guru Meditation codes."""

    def __init__(self, message: str, guru_code: str | None = None):
        self.guru_code = guru_code
        full_message = f"{message} ({guru_code})" if guru_code else message
        super().__init__(full_message)


@dataclass
class XOAuthConfig:
    """X OAuth configuration from environment."""

    client_id: str
    client_secret: str | None  # Optional for public clients
    redirect_uri: str
    scopes: list[str]

    @classmethod
    def from_env(cls) -> "XOAuthConfig":
        """Load configuration from HOCON config.

        Config paths (resolved from env vars at config-load time):
        - x_bookmarks.client_id: OAuth 2.0 Client ID (required)
        - x_bookmarks.client_secret: OAuth 2.0 Client Secret (required for confidential clients)
        - x_bookmarks.callback_url: Callback URL
        """
        from gaius.core.config import get_config

        cfg = get_config()
        raw = cfg._raw
        xb = raw.get("gaius.x_bookmarks", {}) if raw else {}

        client_id = xb.get("client_id", "") if xb else ""
        if not client_id:
            raise XOAuthError(
                "X_CLIENT_ID not configured.\n"
                "  Get credentials at: https://developer.x.com/en/portal/dashboard\n"
                "  Set X_CLIENT_ID env var or x_bookmarks.client_id in config",
                guru_code="#XB.00000003.NOCLIENT",
            )

        client_secret = xb.get("client_secret", "") if xb else ""

        return cls(
            client_id=client_id,
            client_secret=client_secret or None,
            redirect_uri=xb.get("callback_url", "https://gaius.zndx.org/x-callback") if xb else "https://gaius.zndx.org/x-callback",
            scopes=["bookmark.read", "users.read", "tweet.read", "offline.access"],
        )


@dataclass
class XTokens:
    """OAuth tokens for X API access."""

    user_id: str
    username: str
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scopes: list[str]

    @property
    def is_expired(self) -> bool:
        """Check if token is expired (with 5 min buffer)."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= self.expires_at - timedelta(minutes=5)

    @property
    def needs_refresh(self) -> bool:
        """Check if token needs refresh."""
        return self.is_expired and self.refresh_token is not None


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code verifier and challenge.

    Returns:
        Tuple of (code_verifier, code_challenge).
        - verifier: 43-128 character random string
        - challenge: Base64-URL encoded SHA256 hash of verifier
    """
    # Generate random verifier (43-128 characters, using 64)
    code_verifier = secrets.token_urlsafe(48)  # 64 characters

    # Generate challenge: Base64-URL encoded SHA256 hash
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    return code_verifier, code_challenge


def get_authorization_url(state: str, config: XOAuthConfig | None = None) -> tuple[str, str]:
    """Build X OAuth authorization URL.

    Args:
        state: Random state value for CSRF protection.
        config: OAuth configuration (loads from env if not provided).

    Returns:
        Tuple of (authorization_url, code_verifier).
        The code_verifier must be saved and passed to exchange_code_for_token.
    """
    if config is None:
        config = XOAuthConfig.from_env()

    code_verifier, code_challenge = generate_pkce_pair()

    params = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "scope": " ".join(config.scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    base_url = "https://twitter.com/i/oauth2/authorize"
    url = f"{base_url}?{urllib.parse.urlencode(params)}"

    return url, code_verifier


async def exchange_code_for_token(
    code: str, verifier: str, config: XOAuthConfig | None = None
) -> dict[str, Any]:
    """Exchange authorization code for access token.

    Args:
        code: Authorization code from callback.
        verifier: PKCE code_verifier from get_authorization_url.
        config: OAuth configuration.

    Returns:
        Token response dict with access_token, refresh_token, expires_in, etc.

    Raises:
        XOAuthError: If token exchange fails.
    """
    if config is None:
        config = XOAuthConfig.from_env()

    data = {
        "code": code,
        "grant_type": "authorization_code",
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "code_verifier": verifier,
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    # Add Basic auth if client_secret is available
    if config.client_secret:
        auth_string = f"{config.client_id}:{config.client_secret}"
        auth_b64 = base64.b64encode(auth_string.encode()).decode()
        headers["Authorization"] = f"Basic {auth_b64}"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.twitter.com/2/oauth2/token",
            data=data,
            headers=headers,
            timeout=30.0,
        )

        if response.status_code != 200:
            error_data = response.json() if response.content else {}
            raise XOAuthError(
                f"Token exchange failed: {error_data.get('error_description', response.text)}",
                guru_code="#XB.00000005.APIERROR",
            )

        return response.json()


async def refresh_access_token(
    refresh_token: str, config: XOAuthConfig | None = None
) -> dict[str, Any]:
    """Refresh expired access token.

    Args:
        refresh_token: The refresh token from previous auth.
        config: OAuth configuration.

    Returns:
        New token response with fresh access_token.

    Raises:
        XOAuthError: If refresh fails.
    """
    if config is None:
        config = XOAuthConfig.from_env()

    data = {
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "client_id": config.client_id,
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    if config.client_secret:
        auth_string = f"{config.client_id}:{config.client_secret}"
        auth_b64 = base64.b64encode(auth_string.encode()).decode()
        headers["Authorization"] = f"Basic {auth_b64}"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.twitter.com/2/oauth2/token",
            data=data,
            headers=headers,
            timeout=30.0,
        )

        if response.status_code != 200:
            error_data = response.json() if response.content else {}
            raise XOAuthError(
                f"Token refresh failed: {error_data.get('error_description', response.text)}",
                guru_code="#XB.00000002.TOKENEXP",
            )

        return response.json()


async def get_user_info(access_token: str) -> dict[str, Any]:
    """Get authenticated user's info.

    Args:
        access_token: Valid access token.

    Returns:
        User data with id and username.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.twitter.com/2/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )

        if response.status_code != 200:
            raise XOAuthError(
                f"Failed to get user info: {response.text}",
                guru_code="#XB.00000005.APIERROR",
            )

        return response.json().get("data", {})


async def save_tokens(
    user_id: str,
    username: str,
    token_data: dict[str, Any],
    pool: asyncpg.Pool,
) -> None:
    """Save OAuth tokens to database.

    Args:
        user_id: X user ID.
        username: X @handle.
        token_data: Token response from OAuth flow.
        pool: asyncpg connection pool.
    """

    expires_at = None
    if "expires_in" in token_data:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])

    scopes = token_data.get("scope", "").split() if token_data.get("scope") else []

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO x_oauth_tokens (user_id, username, access_token, refresh_token, token_type, scopes, expires_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                username = EXCLUDED.username,
                access_token = EXCLUDED.access_token,
                refresh_token = COALESCE(EXCLUDED.refresh_token, x_oauth_tokens.refresh_token),
                token_type = EXCLUDED.token_type,
                scopes = EXCLUDED.scopes,
                expires_at = EXCLUDED.expires_at,
                updated_at = NOW()
            """,
            user_id,
            username,
            token_data["access_token"],
            token_data.get("refresh_token"),
            token_data.get("token_type", "Bearer"),
            scopes,
            expires_at,
        )


async def get_tokens(user_id: str, pool: asyncpg.Pool) -> XTokens | None:
    """Load tokens from database.

    Args:
        user_id: X user ID.
        pool: asyncpg connection pool.

    Returns:
        XTokens if found, None otherwise.
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT user_id, username, access_token, refresh_token, scopes, expires_at
            FROM x_oauth_tokens
            WHERE user_id = $1
            """,
            user_id,
        )

        if row is None:
            return None

        return XTokens(
            user_id=row["user_id"],
            username=row["username"],
            access_token=row["access_token"],
            refresh_token=row["refresh_token"],
            expires_at=row["expires_at"],
            scopes=row["scopes"] or [],
        )


async def get_any_tokens(pool: asyncpg.Pool) -> XTokens | None:
    """Get tokens for any configured user (for single-user setups).

    Args:
        pool: asyncpg connection pool.

    Returns:
        XTokens if any user is configured, None otherwise.
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT user_id, username, access_token, refresh_token, scopes, expires_at
            FROM x_oauth_tokens
            ORDER BY updated_at DESC
            LIMIT 1
            """
        )

        if row is None:
            return None

        return XTokens(
            user_id=row["user_id"],
            username=row["username"],
            access_token=row["access_token"],
            refresh_token=row["refresh_token"],
            expires_at=row["expires_at"],
            scopes=row["scopes"] or [],
        )


async def ensure_valid_token(pool: asyncpg.Pool, user_id: str | None = None) -> XTokens:
    """Get valid tokens, refreshing if needed.

    Args:
        pool: asyncpg connection pool.
        user_id: Specific user ID, or None to get any configured user.

    Returns:
        Valid XTokens with fresh access_token.

    Raises:
        XOAuthError: If no tokens found or refresh fails.
    """
    if user_id:
        tokens = await get_tokens(user_id, pool)
    else:
        tokens = await get_any_tokens(pool)

    if tokens is None:
        raise XOAuthError(
            "No OAuth tokens found. Run '/x auth' to authenticate.\n"
            "  Required: X Developer account with bookmark.read access",
            guru_code="#XB.00000001.NOTOKEN",
        )

    # Refresh if needed
    if tokens.needs_refresh:
        if tokens.refresh_token is None:
            raise XOAuthError(
                "Token expired and no refresh token available.\n"
                "  Run '/x auth' to re-authenticate.",
                guru_code="#XB.00000002.TOKENEXP",
            )

        token_data = await refresh_access_token(tokens.refresh_token)
        await save_tokens(tokens.user_id, tokens.username, token_data, pool)
        tokens = await get_tokens(tokens.user_id, pool)
        if tokens is None:
            raise XOAuthError("Failed to reload tokens after refresh")

    return tokens


class XOAuthClient:
    """High-level OAuth client for X API.

    Used by the engine's XBookmarksService to manage OAuth flows.
    Requires a database pool for token storage.
    """

    def __init__(self, pool: asyncpg.Pool, config: XOAuthConfig | None = None):
        """Initialize client with database pool.

        Args:
            pool: asyncpg connection pool for token storage.
            config: OAuth configuration (loads from env if not provided).
        """
        self._pool = pool
        self._config = config

    @property
    def config(self) -> XOAuthConfig:
        """Get or load configuration."""
        if self._config is None:
            self._config = XOAuthConfig.from_env()
        return self._config

    def get_auth_url(self, state: str | None = None) -> tuple[str, str, str]:
        """Get authorization URL with state and verifier.

        Returns:
            Tuple of (url, state, verifier).
        """
        if state is None:
            state = secrets.token_urlsafe(16)
        url, verifier = get_authorization_url(state, self.config)
        return url, state, verifier

    async def complete_auth(self, code: str, verifier: str) -> XTokens:
        """Complete OAuth flow with authorization code.

        Args:
            code: Authorization code from callback.
            verifier: PKCE verifier from get_auth_url.

        Returns:
            Authenticated tokens.
        """
        token_data = await exchange_code_for_token(code, verifier, self.config)
        user_info = await get_user_info(token_data["access_token"])

        user_id = user_info["id"]
        username = user_info["username"]

        await save_tokens(user_id, username, token_data, self._pool)

        return XTokens(
            user_id=user_id,
            username=username,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=(
                datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])
                if "expires_in" in token_data
                else None
            ),
            scopes=token_data.get("scope", "").split(),
        )

    async def get_valid_token(self, user_id: str | None = None) -> str:
        """Get a valid access token, refreshing if needed.

        Args:
            user_id: Specific user, or None for any configured user.

        Returns:
            Valid access token string.
        """
        tokens = await ensure_valid_token(self._pool, user_id)
        return tokens.access_token
