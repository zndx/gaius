"""Authentication module for Gaius.

Provides OAuth 2.0 flows for external service integration.
"""

from .x_oauth import (
    XOAuthConfig,
    XOAuthClient,
    generate_pkce_pair,
    get_authorization_url,
    exchange_code_for_token,
    refresh_access_token,
    save_tokens,
    get_tokens,
    XOAuthError,
)

__all__ = [
    "XOAuthConfig",
    "XOAuthClient",
    "generate_pkce_pair",
    "get_authorization_url",
    "exchange_code_for_token",
    "refresh_access_token",
    "save_tokens",
    "get_tokens",
    "XOAuthError",
]
