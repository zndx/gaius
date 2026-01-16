"""X Bookmarks sync service for the Gaius engine.

Manages X (Twitter) bookmark synchronization via OAuth 2.0 API:
- OAuth flow management (authorization, token refresh)
- Rate-limited API request queue processing (1 req/15 min on Free tier)
- Bookmark fetching with pagination and resumption
- Sync to Iceberg HX and KB manifests
- pg_cron triggered daily sync

Guru Meditation Codes:
- #XB.00000001.NOTOKEN: No OAuth tokens found for user
- #XB.00000002.TOKENEXP: Token expired, no refresh token
- #XB.00000003.NOCLIENT: X_CLIENT_ID not configured
- #XB.00000004.RATELIMIT: X API rate limit exceeded
- #XB.00000005.APIERROR: X API returned error
- #XB.00000011.NOFOLDER: Folders endpoint not available (403) - feature disabled
- #XB.00000012.FOLDERFAIL: Folders fetch failed (non-403 error)
- #XB.00000013.BOOKMARKFAIL: Failed to fetch bookmarks for folder
"""


class XBookmarksError(Exception):
    """X Bookmarks service error with Guru Meditation code."""

    def __init__(self, message: str, guru_code: str | None = None):
        super().__init__(message)
        self.guru_code = guru_code

    def __str__(self) -> str:
        if self.guru_code:
            return f"{super().__str__()}\n  Guru Meditation: {self.guru_code}"
        return super().__str__()

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import asyncpg
import httpx

from ...auth.x_oauth import (
    XOAuthClient,
    XOAuthConfig,
    XOAuthError,
    ensure_valid_token,
)

logger = logging.getLogger(__name__)


@dataclass
class XBookmark:
    """A bookmarked tweet."""

    tweet_id: str
    folder_id: str | None
    folder_name: str | None
    text: str
    author_id: str
    author_username: str
    urls: list[str] = field(default_factory=list)
    media_urls: list[str] = field(default_factory=list)
    tweet_created_at: datetime | None = None
    bookmarked_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        """SHA-256 hash of tweet content for deduplication."""
        content = f"{self.tweet_id}:{self.text}:{self.author_username}"
        return hashlib.sha256(content.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "tweet_id": self.tweet_id,
            "folder_id": self.folder_id,
            "folder_name": self.folder_name,
            "text": self.text,
            "author_id": self.author_id,
            "author_username": self.author_username,
            "urls": self.urls,
            "media_urls": self.media_urls,
            "tweet_created_at": (
                self.tweet_created_at.isoformat() if self.tweet_created_at else None
            ),
            "bookmarked_at": (
                self.bookmarked_at.isoformat() if self.bookmarked_at else None
            ),
            "content_hash": self.content_hash,
            "metadata": self.metadata,
        }


@dataclass
class XSyncRun:
    """Result of a sync operation."""

    run_id: int
    user_id: str
    status: str
    bookmarks_fetched: int = 0
    bookmarks_new: int = 0
    folders_synced: int = 0
    pages_fetched: int = 0
    pagination_token: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    # Extended fields for Iceberg and work queue
    iceberg_written: int = 0
    queue_items: int = 0
    action_required: str | None = None
    guidance_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        result = {
            "run_id": self.run_id,
            "user_id": self.user_id,
            "status": self.status,
            "bookmarks_fetched": self.bookmarks_fetched,
            "bookmarks_new": self.bookmarks_new,
            "folders_synced": self.folders_synced,
            "pages_fetched": self.pages_fetched,
            "pagination_token": self.pagination_token,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
            # Extended fields
            "iceberg_written": self.iceberg_written,
            "queue_items": self.queue_items,
        }
        if self.action_required:
            result["action_required"] = self.action_required
        if self.guidance_message:
            result["guidance_message"] = self.guidance_message
        return result


@dataclass
class XBookmarksConfig:
    """Configuration for X Bookmarks service."""

    queue_poll_interval_s: int = 900  # 15 minutes for Free tier rate limit
    sync_batch_size: int = 100  # Max bookmarks per page
    kb_root: str = "build/dev"

    @classmethod
    def from_hocon(cls, config: dict[str, Any]) -> "XBookmarksConfig":
        """Load from HOCON config."""
        x_config = config.get("gaius", {}).get("x", {}).get("sync", {})
        return cls(
            queue_poll_interval_s=x_config.get("poll_interval_s", 900),
            sync_batch_size=x_config.get("batch_size", 100),
            kb_root=config.get("gaius", {}).get("kb", {}).get("root", "build/dev"),
        )


# Type alias for event callback
XBEventCallback = "Callable[[str, dict[str, Any]], None]"


class XBookmarksService:
    """X Bookmarks sync service.

    Manages OAuth flows, rate-limited API requests, and bookmark sync.
    Designed to run within the Gaius engine process with access to
    the shared database pool.

    Event Types (for InitStream push updates):
    - XB_AUTH_COMPLETED: OAuth completed successfully (includes user_id, username)
    - XB_AUTH_FAILED: OAuth failed (includes error message)
    - XB_STATUS_CHANGED: Sync/queue status changed (includes queue_depth, can_request)
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        config: XBookmarksConfig | None = None,
    ):
        """Initialize service.

        Args:
            pool: asyncpg connection pool.
            config: Service configuration.
        """
        self._pool = pool
        self._config = config or XBookmarksConfig()

        # OAuth client (lazy init)
        self._oauth_client: XOAuthClient | None = None

        # Background task state
        self._running = False
        self._queue_task: asyncio.Task | None = None

        # Stats
        self._total_syncs = 0
        self._total_bookmarks = 0
        self._last_sync_at: datetime | None = None

        # Feature availability (None = not checked, True/False = checked)
        self._folders_available: bool | None = None

        # Event callback for pushing updates to InitStream subscribers
        self._event_callback: Callable[[str, dict[str, Any]], None] | None = None

        logger.info("XBookmarksService initialized")

    def set_event_callback(
        self, callback: Callable[[str, dict[str, Any]], None]
    ) -> None:
        """Set callback for pushing XB events to InitStream subscribers.

        The callback receives (event_type, data) where:
        - event_type: One of XB_AUTH_COMPLETED, XB_AUTH_FAILED, XB_STATUS_CHANGED
        - data: Event-specific payload dict

        Args:
            callback: Function to call when events occur.
        """
        self._event_callback = callback
        logger.info("XBookmarksService event callback registered")

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event to InitStream subscribers with OTel tracing.

        Creates a span for the emit operation and injects trace context
        into the event data for propagation across async boundaries.

        Args:
            event_type: Event type (XB_AUTH_COMPLETED, XB_AUTH_FAILED, XB_STATUS_CHANGED)
            data: Event payload (will be modified to include trace context)
        """
        from gaius.core.telemetry import get_tracer, XBAuthAttrs

        tracer = get_tracer()
        with tracer.start_as_current_span("xb.auth_event.emit") as span:
            span.set_attribute(XBAuthAttrs.EVENT_TYPE, event_type)
            span.set_attribute(XBAuthAttrs.USER_ID, data.get("user_id", ""))
            span.set_attribute(XBAuthAttrs.USERNAME, data.get("username", ""))
            span.set_attribute(XBAuthAttrs.IS_TEST, data.get("is_test", False))

            if self._event_callback:
                # Inject trace context into event data for propagation
                try:
                    from opentelemetry import trace as otel_trace
                    trace_ctx = span.get_span_context()
                    if hasattr(trace_ctx, 'trace_id') and hasattr(trace_ctx, 'span_id'):
                        data["_trace_id"] = format(trace_ctx.trace_id, "032x")
                        data["_span_id"] = format(trace_ctx.span_id, "016x")
                except Exception:
                    # OTel not fully initialized - continue without trace context
                    pass

                span.add_event("xb.callback.invoking")
                try:
                    logger.info(f"Emitting XB event: {event_type} with data: {data}")
                    self._event_callback(event_type, data)
                    span.add_event("xb.callback.invoked")
                    logger.info(f"Successfully emitted XB event: {event_type}")
                except Exception as e:
                    span.record_exception(e)
                    logger.error(f"Failed to emit XB event {event_type}: {e}", exc_info=True)
                    raise
            else:
                span.add_event("xb.callback.not_registered")
                logger.warning(f"XB event {event_type} not emitted: no callback registered")

    @property
    def oauth_client(self) -> XOAuthClient:
        """Get or create OAuth client."""
        if self._oauth_client is None:
            try:
                config = XOAuthConfig.from_env()
                self._oauth_client = XOAuthClient(self._pool, config)
            except XOAuthError:
                # Config not available - client will fail on use
                self._oauth_client = XOAuthClient(self._pool)
        return self._oauth_client

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background queue processor."""
        if self._running:
            return

        self._running = True
        self._queue_task = asyncio.create_task(self._queue_processor_loop())
        logger.info("XBookmarksService started")

    async def stop(self) -> None:
        """Stop the background queue processor."""
        if not self._running:
            return

        self._running = False
        if self._queue_task:
            self._queue_task.cancel()
            try:
                await self._queue_task
            except asyncio.CancelledError:
                pass

        logger.info("XBookmarksService stopped")

    # ─────────────────────────────────────────────────────────────────────────
    # OAuth Flow
    # ─────────────────────────────────────────────────────────────────────────

    async def get_auth_url(self) -> tuple[str, str, str]:
        """Get OAuth authorization URL and store verifier in database.

        The state and verifier are stored in x_oauth_pending table so that
        complete_auth can retrieve the verifier without the client needing
        to store it (important for CLI flows with manual code entry).

        Returns:
            Tuple of (url, state, verifier). The verifier is also stored
            in the database keyed by state.
        """
        url, state, verifier = self.oauth_client.get_auth_url()

        # Store the pending auth in database
        async with self._pool.acquire() as conn:
            # Clean up expired pending auths first
            await conn.execute("SELECT x_cleanup_pending_auths()")

            # Store this pending auth
            await conn.execute(
                """
                INSERT INTO x_oauth_pending (state, verifier, expires_at)
                VALUES ($1, $2, NOW() + INTERVAL '10 minutes')
                ON CONFLICT (state) DO UPDATE SET
                    verifier = EXCLUDED.verifier,
                    expires_at = NOW() + INTERVAL '10 minutes'
                """,
                state,
                verifier,
            )

        logger.info(f"OAuth auth URL generated, state={state[:8]}...")
        return url, state, verifier

    async def complete_auth(self, code: str, verifier: str | None = None) -> dict[str, Any]:
        """Complete OAuth flow with authorization code.

        Args:
            code: Authorization code from callback.
            verifier: PKCE verifier from get_auth_url. If not provided,
                looks up the most recent pending auth from database.

        Returns:
            Dict with user_id and username.
        """
        # If verifier not provided, look it up from the most recent pending auth
        if not verifier:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT verifier FROM x_oauth_pending
                    WHERE expires_at > NOW()
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
                if not row:
                    raise XOAuthError(
                        "No pending OAuth authorization found.\n"
                        "  The authorization may have expired (10 minute limit).\n"
                        "  Please run '/x-bookmarks auth' again to start over.",
                        guru_code="#XB.00000006.NOPENDING",
                    )
                verifier = row["verifier"]
                logger.info("Retrieved verifier from pending auth")

        tokens = await self.oauth_client.complete_auth(code, verifier)

        # Clean up used pending auth
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM x_oauth_pending WHERE expires_at <= NOW()")

        return {
            "user_id": tokens.user_id,
            "username": tokens.username,
            "scopes": tokens.scopes,
            "expires_at": tokens.expires_at.isoformat() if tokens.expires_at else None,
        }

    async def complete_auth_by_state(self, code: str, state: str) -> dict[str, Any]:
        """Complete OAuth flow using state to look up verifier.

        Called when Cloudflare Worker sends callback directly via HTTP,
        or when polling KV finds a pending OAuth code.

        Unlike complete_auth(), this looks up the verifier using the
        specific state parameter rather than the most recent pending auth.

        Args:
            code: Authorization code from callback.
            state: State parameter that was passed to X during auth initiation.

        Returns:
            Dict with user_id and username on success, or error on failure.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT verifier FROM x_oauth_pending
                WHERE state = $1 AND expires_at > NOW()
                """,
                state,
            )

            if not row:
                logger.warning(f"complete_auth_by_state: no pending auth for state={state[:8]}...")
                return {
                    "error": "Invalid or expired state",
                    "guru_code": "#XB.00000007.INVALIDSTATE",
                }

            verifier = row["verifier"]
            logger.info(f"Found verifier for state={state[:8]}...")

        try:
            result = await self.complete_auth(code, verifier)
            return result
        except Exception as e:
            logger.error(f"complete_auth_by_state failed: {e}")
            return {"error": str(e)}

    async def poll_kv_for_pending_auth(self) -> dict[str, Any] | None:
        """Poll Cloudflare KV for pending OAuth codes.

        The Cloudflare Worker stores OAuth codes in KV after X callback.
        This method checks for any pending codes that match our pending
        auth states and completes the OAuth flow automatically.

        Requires environment variables:
        - CLOUDFLARE_ACCOUNT_ID: Cloudflare account ID
        - CLOUDFLARE_API_TOKEN: API token with Workers KV read/write
        - CLOUDFLARE_KV_NAMESPACE_ID: KV namespace ID (GAIUS_SESSIONS)

        Returns:
            Dict with user_id and username if auth completed, None otherwise.
        """
        import os

        account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
        api_token = os.environ.get("CLOUDFLARE_API_TOKEN")
        namespace_id = os.environ.get("CLOUDFLARE_KV_NAMESPACE_ID")

        if not all([account_id, api_token, namespace_id]):
            # KV polling not configured - not an error, just skip
            return None

        # Get pending auth states from database
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT state FROM x_oauth_pending
                WHERE expires_at > NOW()
                ORDER BY created_at DESC
                """
            )

        if not rows:
            return None

        # Check KV for each pending state
        async with httpx.AsyncClient() as client:
            for row in rows:
                state = row["state"]
                kv_key = f"oauth-pending/{state}"

                try:
                    response = await client.get(
                        f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
                        f"/storage/kv/namespaces/{namespace_id}/values/{kv_key}",
                        headers={
                            "Authorization": f"Bearer {api_token}",
                        },
                        timeout=10.0,
                    )

                    if response.status_code == 200:
                        try:
                            data = response.json()
                            code = data.get("code")
                            if code:
                                logger.info(f"Found OAuth code in KV for state={state[:8]}...")

                                # Complete the auth
                                result = await self.complete_auth_by_state(code, state)

                                if "error" not in result:
                                    # Delete the KV entry after successful auth
                                    await client.delete(
                                        f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
                                        f"/storage/kv/namespaces/{namespace_id}/values/{kv_key}",
                                        headers={
                                            "Authorization": f"Bearer {api_token}",
                                        },
                                        timeout=10.0,
                                    )
                                    logger.info("Deleted OAuth code from KV after successful auth")

                                    # Emit XB_AUTH_COMPLETED event for real-time TUI update
                                    self._emit_event("XB_AUTH_COMPLETED", {
                                        "user_id": result.get("user_id", ""),
                                        "username": result.get("username", ""),
                                    })
                                else:
                                    # Emit XB_AUTH_FAILED event
                                    self._emit_event("XB_AUTH_FAILED", {
                                        "error": result.get("error", "Unknown error"),
                                    })

                                return result
                        except json.JSONDecodeError:
                            # Value might be raw text, try parsing
                            pass

                except httpx.TimeoutException:
                    logger.warning(f"Timeout polling KV for state={state[:8]}...")
                except Exception as e:
                    logger.warning(f"Error polling KV: {e}")

        return None

    async def get_auth_status(self, user_id: str | None = None) -> dict[str, Any]:
        """Get OAuth status for a user.

        Returns status dict with token info and actionable guidance when
        re-authentication is needed.

        Args:
            user_id: Specific user, or None for any configured user.

        Returns:
            Status dict with token info and guidance fields:
            - action_required: Token status code if action needed
            - message: Human-readable guidance message
        """
        try:
            tokens = await ensure_valid_token(self._pool, user_id)

            result = {
                "authenticated": True,
                "user_id": tokens.user_id,
                "username": tokens.username,
                "expires_at": (
                    tokens.expires_at.isoformat() if tokens.expires_at else None
                ),
                "scopes": tokens.scopes,
            }

            # Add actionable guidance based on token expiry
            if tokens.expires_at:
                from datetime import timedelta
                now = datetime.now(timezone.utc)
                time_remaining = tokens.expires_at - now

                if time_remaining <= timedelta(hours=0):
                    result["action_required"] = "TOKEN_EXPIRED"
                    result["message"] = (
                        "Your X API token has expired. "
                        "Re-authenticate using /x-bookmarks auth to continue syncing."
                    )
                elif time_remaining <= timedelta(hours=24):
                    hours_left = int(time_remaining.total_seconds() / 3600)
                    result["action_required"] = "TOKEN_EXPIRING"
                    result["message"] = (
                        f"Your X API token expires in ~{hours_left} hours. "
                        "Consider re-authenticating soon using /x-bookmarks auth."
                    )

            return result

        except XOAuthError as e:
            return {
                "authenticated": False,
                "error": str(e),
                "guru_code": e.guru_code,
                "action_required": "NOT_AUTHENTICATED",
                "message": (
                    "X API authentication required. "
                    "Run /x-bookmarks auth to begin OAuth authorization."
                ),
            }

    # ─────────────────────────────────────────────────────────────────────────
    # Sync Operations
    # ─────────────────────────────────────────────────────────────────────────

    async def trigger_sync(
        self, user_id: str | None = None, force: bool = False
    ) -> XSyncRun:
        """Trigger a bookmark sync using folder-first approach.

        Only syncs bookmarks that are in folders. Unfiled bookmarks are skipped.
        If folders endpoint is not available, raises XBookmarksError with
        guru code #XB.00000011.NOFOLDER.

        Args:
            user_id: Specific user, or None for any configured user.
            force: Force sync even if rate limited.

        Returns:
            XSyncRun with sync results.

        Raises:
            XBookmarksError: If folders endpoint unavailable (fail-fast).
            XOAuthError: If authentication fails.
        """
        # Get valid token
        tokens = await ensure_valid_token(self._pool, user_id)
        user_id = tokens.user_id

        # Check rate limit (unless force)
        if not force:
            can_proceed = await self._check_rate_limit(user_id)
            if not can_proceed:
                # Queue the request instead
                run_id = await self._start_sync_run(user_id)
                await self._queue_request(user_id, run_id)
                return XSyncRun(
                    run_id=run_id,
                    user_id=user_id,
                    status="queued",
                    started_at=datetime.now(timezone.utc),
                )

        # Start sync run
        run_id = await self._start_sync_run(user_id)

        try:
            # Step 1: Fetch folders (fail-fast if unavailable)
            folders = await self._fetch_folders(user_id, tokens.access_token)

            if not folders:
                logger.info("No bookmark folders found - nothing to sync")
                await self._complete_sync_run(
                    run_id,
                    status="completed",
                    bookmarks_fetched=0,
                    bookmarks_new=0,
                    folders_synced=0,
                )
                return XSyncRun(
                    run_id=run_id,
                    user_id=user_id,
                    status="completed",
                    bookmarks_fetched=0,
                    bookmarks_new=0,
                    folders_synced=0,
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                )

            # Step 2: Store folder metadata
            await self._store_folders(user_id, folders)

            # Step 3: Fetch and store bookmarks per folder
            total_fetched = 0
            total_new = 0

            for folder in folders:
                bookmarks = await self._fetch_bookmarks_in_folder(
                    user_id, folder["id"], folder["name"], tokens.access_token
                )

                new_count = await self._store_bookmarks(user_id, bookmarks)
                total_fetched += len(bookmarks)
                total_new += new_count

                # Write folder manifest to KB
                await self._write_folder_manifest_to_kb(folder["name"], bookmarks)

            # Complete sync run
            await self._complete_sync_run(
                run_id,
                status="completed",
                bookmarks_fetched=total_fetched,
                bookmarks_new=total_new,
                folders_synced=len(folders),
            )
            self._total_syncs += 1
            self._total_bookmarks += total_new
            self._last_sync_at = datetime.now(timezone.utc)

            logger.info(
                f"Sync completed: {len(folders)} folders, "
                f"{total_fetched} bookmarks fetched, {total_new} new"
            )

            # Write unsynced bookmarks to Iceberg (idempotent)
            iceberg_written = 0
            try:
                iceberg_written = await self._write_to_iceberg()
                logger.info(f"Wrote {iceberg_written} bookmarks to Iceberg raw.bookmarks")
            except Exception as e:
                logger.warning(f"Iceberg write failed (non-fatal): {e}")

            # Populate work queue for KB sync (idempotent)
            queue_items = 0
            try:
                queue_items = await self._populate_kb_work_queue()
                logger.info(f"Added {queue_items} items to KB sync work queue")
            except Exception as e:
                logger.warning(f"Work queue population failed (non-fatal): {e}")

            return XSyncRun(
                run_id=run_id,
                user_id=user_id,
                status="completed",
                bookmarks_fetched=total_fetched,
                bookmarks_new=total_new,
                folders_synced=len(folders),
                iceberg_written=iceberg_written,
                queue_items=queue_items,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )

        except (XOAuthError, XBookmarksError) as e:
            await self._complete_sync_run(
                run_id,
                status="failed",
                error_message=str(e),
            )
            raise

    async def get_sync_status(self, user_id: str | None = None) -> dict[str, Any]:
        """Get sync status for a user.

        Returns status dict with folders, counts, last sync, and actionable
        guidance when re-authentication or attention is needed.

        Args:
            user_id: Specific user, or None for any configured user.

        Returns:
            Status dict with folders, counts, last sync, and guidance fields:
            - action_required: Token status code if action needed
            - message: Human-readable guidance message
        """
        async with self._pool.acquire() as conn:
            # Get from view - use conditional query to avoid asyncpg COALESCE issue
            if user_id:
                row = await conn.fetchrow(
                    "SELECT * FROM v_x_sync_status WHERE user_id = $1 LIMIT 1",
                    user_id,
                )
            else:
                row = await conn.fetchrow(
                    "SELECT * FROM v_x_sync_status LIMIT 1"
                )

            if row is None:
                return {
                    "configured": False,
                    "action_required": "NOT_CONFIGURED",
                    "message": (
                        "X Bookmarks sync is not configured. "
                        "Run /x-bookmarks auth to begin OAuth authorization."
                    ),
                }

            result = {
                "configured": True,
                "user_id": row["user_id"],
                "username": row["username"],
                "token_status": row["token_status"],
                "folder_count": row["folder_count"],
                "bookmark_count": row["bookmark_count"],
                "queued_requests": row["queued_requests"],
                "last_sync_at": (
                    row["last_sync_at"].isoformat() if row["last_sync_at"] else None
                ),
                "last_run_status": row["last_run_status"],
            }

            # Add actionable guidance based on token status
            token_status = row["token_status"]
            if token_status == "expired":
                result["action_required"] = "TOKEN_EXPIRED"
                result["message"] = (
                    "Your X API token has expired. "
                    "Re-authenticate using /x-bookmarks auth to continue syncing."
                )
            elif token_status == "expiring_soon":
                result["action_required"] = "TOKEN_EXPIRING"
                result["message"] = (
                    "Your X API token expires within 24 hours. "
                    "Consider re-authenticating soon using /x-bookmarks auth."
                )

            # Add guidance for failed syncs (rate limiting is common)
            if row["last_run_status"] == "failed" and "action_required" not in result:
                result["action_required"] = "SYNC_FAILED"
                result["message"] = (
                    "Last sync failed. This may be due to rate limiting. "
                    "X API has strict rate limits (1 request per 15 minutes for bookmarks). "
                    "The service will automatically retry when rate limits reset."
                )

            return result

    async def get_service_status(self) -> dict[str, Any]:
        """Get overall X Bookmarks service status.

        Returns:
            Status dict with running state, total syncs, bookmarks, etc.
        """
        async with self._pool.acquire() as conn:
            # Get aggregate stats
            stats = await conn.fetchrow(
                """
                SELECT
                    COUNT(DISTINCT user_id) as total_users,
                    COUNT(*) as total_bookmarks,
                    MAX(synced_at) as last_sync_at
                FROM x_bookmarks_sync
                """
            )

            # Count completed syncs (rough estimate from folder sync times)
            sync_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM x_bookmark_folders
                WHERE last_sync_at IS NOT NULL
                """
            )

            return {
                "running": True,  # Service is running if this method is called
                "total_syncs": sync_count or 0,
                "total_bookmarks": stats["total_bookmarks"] if stats else 0,
                "total_users": stats["total_users"] if stats else 0,
                "last_sync_at": (
                    stats["last_sync_at"].isoformat()
                    if stats and stats["last_sync_at"]
                    else ""
                ),
                "queue_poll_interval_s": 60,  # Default poll interval
            }

    async def get_queue_status(self, user_id: str | None = None) -> dict[str, Any]:
        """Get queue depth and cooldown status for InitPanel display.

        Args:
            user_id: Specific user, or None for default user.

        Returns:
            Dict with:
            - queue_depth: Number of pending requests in work queue
            - cooldown_end_iso: ISO8601 timestamp when cooldown ends (empty if can request)
            - cooldown_seconds: Seconds remaining until next request allowed
            - can_request: True if rate limit allows request now
        """
        async with self._pool.acquire() as conn:
            # Get queue depth (pending bookmark_to_kb requests)
            queue_depth = await conn.fetchval("""
                SELECT COUNT(*) FROM x_api_requests
                WHERE status IN ('pending', 'queued', 'executing')
            """) or 0

            # Get rate limit status
            # First try to get user from tokens table if not provided
            if not user_id:
                user_id = await conn.fetchval(
                    "SELECT user_id FROM x_oauth_tokens LIMIT 1"
                )

            if not user_id:
                # No user configured
                return {
                    "queue_depth": queue_depth,
                    "cooldown_end_iso": "",
                    "cooldown_seconds": 0,
                    "can_request": True,
                }

            # Get rate limit from x_rate_limits table
            row = await conn.fetchrow(
                """
                SELECT reset_at, requests_remaining
                FROM x_rate_limits
                WHERE user_id = $1 AND endpoint_group = 'bookmarks'
                """,
                user_id,
            )

            if row and row["reset_at"]:
                now = datetime.now(timezone.utc)
                reset_at = row["reset_at"]

                if reset_at > now:
                    remaining = (reset_at - now).total_seconds()
                    return {
                        "queue_depth": queue_depth,
                        "cooldown_end_iso": reset_at.isoformat(),
                        "cooldown_seconds": int(remaining),
                        "can_request": False,
                    }

            return {
                "queue_depth": queue_depth,
                "cooldown_end_iso": "",
                "cooldown_seconds": 0,
                "can_request": True,
            }

    # ─────────────────────────────────────────────────────────────────────────
    # Folder Operations
    # ─────────────────────────────────────────────────────────────────────────

    async def _fetch_folders(self, user_id: str, access_token: str) -> list[dict]:
        """Fetch bookmark folders from X API.

        Returns list of {id: str, name: str} dicts.
        Raises XBookmarksError if endpoint unavailable.
        """
        url = f"https://api.x.com/2/users/{user_id}/bookmarks/folders"
        headers = {"Authorization": f"Bearer {access_token}"}

        folders = []
        pagination_token = None

        async with httpx.AsyncClient() as client:
            while True:
                params: dict[str, Any] = {"max_results": 100}
                if pagination_token:
                    params["pagination_token"] = pagination_token

                response = await client.get(
                    url, headers=headers, params=params, timeout=30.0
                )

                if response.status_code == 403:
                    self._folders_available = False
                    raise XBookmarksError(
                        "Bookmark folders not available for your API tier.\n"
                        "  X Bookmarks sync requires folder access.\n"
                        "  Feature disabled until folders endpoint is accessible.",
                        guru_code="#XB.00000011.NOFOLDER",
                    )
                elif response.status_code != 200:
                    raise XBookmarksError(
                        f"Failed to fetch folders: {response.status_code} - {response.text}",
                        guru_code="#XB.00000012.FOLDERFAIL",
                    )

                self._folders_available = True
                data = response.json()
                folders.extend(data.get("data", []))

                pagination_token = data.get("meta", {}).get("next_token")
                if not pagination_token:
                    break

        logger.info(f"Fetched {len(folders)} bookmark folders")
        return folders

    async def _fetch_bookmarks_in_folder(
        self, user_id: str, folder_id: str, folder_name: str, access_token: str
    ) -> list[XBookmark]:
        """Fetch bookmarks within a specific folder.

        The folder endpoint only returns tweet IDs, so we need a two-step approach:
        1. Get tweet IDs from the folder endpoint
        2. Use the tweets lookup endpoint to get full tweet details

        Args:
            user_id: X user ID
            folder_id: Folder ID from folders endpoint
            folder_name: Folder name (for assignment to bookmark)
            access_token: OAuth bearer token

        Returns:
            List of XBookmark with folder_id and folder_name set.
        """
        folder_url = f"https://api.x.com/2/users/{user_id}/bookmarks/folders/{folder_id}"
        headers = {"Authorization": f"Bearer {access_token}"}

        # Step 1: Collect all tweet IDs from the folder
        tweet_ids: list[str] = []
        pagination_token = None

        async with httpx.AsyncClient() as client:
            while True:
                params: dict[str, Any] = {}
                if pagination_token:
                    params["pagination_token"] = pagination_token

                response = await client.get(
                    folder_url, headers=headers, params=params, timeout=30.0
                )

                if response.status_code != 200:
                    raise XBookmarksError(
                        f"Failed to fetch bookmarks for folder {folder_name}: "
                        f"{response.status_code} - {response.text}",
                        guru_code="#XB.00000013.BOOKMARKFAIL",
                    )

                data = response.json()

                # The folder endpoint returns tweet IDs
                for item in data.get("data", []):
                    tweet_ids.append(item["id"])

                pagination_token = data.get("meta", {}).get("next_token")
                if not pagination_token:
                    break

            if not tweet_ids:
                logger.info(f"No bookmarks found in folder '{folder_name}'")
                return []

            # Step 2: Fetch full tweet details in batches of 100
            bookmarks: list[XBookmark] = []
            tweets_url = "https://api.x.com/2/tweets"

            for i in range(0, len(tweet_ids), 100):
                batch = tweet_ids[i : i + 100]

                response = await client.get(
                    tweets_url,
                    headers=headers,
                    params={
                        "ids": ",".join(batch),
                        "tweet.fields": "created_at,author_id,text,entities",
                        "expansions": "author_id",
                        "user.fields": "username",
                    },
                    timeout=30.0,
                )

                if response.status_code != 200:
                    logger.warning(
                        f"Failed to fetch tweet details for batch: "
                        f"{response.status_code} - {response.text}"
                    )
                    # Continue with partial data - create minimal bookmarks
                    for tweet_id in batch:
                        bookmarks.append(
                            XBookmark(
                                tweet_id=tweet_id,
                                folder_id=folder_id,
                                folder_name=folder_name,
                                text="[Tweet details unavailable]",
                                author_id="",
                                author_username="",
                                urls=[],
                                media_urls=[],
                                tweet_created_at=None,
                                bookmarked_at=datetime.now(timezone.utc),
                                metadata={"partial": True},
                            )
                        )
                    continue

                data = response.json()

                # Build username lookup from expansions
                users = {
                    u["id"]: u["username"]
                    for u in data.get("includes", {}).get("users", [])
                }

                # Parse tweets into XBookmark objects
                for tweet in data.get("data", []):
                    urls = []
                    entities = tweet.get("entities", {})
                    for url_entity in entities.get("urls", []):
                        expanded = url_entity.get("expanded_url", url_entity.get("url"))
                        if expanded:
                            urls.append(expanded)

                    bookmark = XBookmark(
                        tweet_id=tweet["id"],
                        folder_id=folder_id,
                        folder_name=folder_name,
                        text=tweet.get("text", ""),
                        author_id=tweet.get("author_id", ""),
                        author_username=users.get(tweet.get("author_id", ""), ""),
                        urls=urls,
                        media_urls=[],
                        tweet_created_at=datetime.fromisoformat(
                            tweet["created_at"].replace("Z", "+00:00")
                        )
                        if tweet.get("created_at")
                        else None,
                        bookmarked_at=datetime.now(timezone.utc),
                        metadata={"raw": tweet},
                    )
                    bookmarks.append(bookmark)

        logger.info(f"Fetched {len(bookmarks)} bookmarks from folder '{folder_name}'")
        return bookmarks

    async def _store_folders(self, user_id: str, folders: list[dict]) -> None:
        """Store folder metadata in database."""
        async with self._pool.acquire() as conn:
            for folder in folders:
                kb_path = f"current/bookmarks/{self._sanitize_folder_name(folder['name'])}"
                await conn.execute(
                    """
                    INSERT INTO x_bookmark_folders (x_folder_id, user_id, name, kb_path)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (x_folder_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        kb_path = EXCLUDED.kb_path,
                        updated_at = NOW()
                    """,
                    folder["id"],
                    user_id,
                    folder["name"],
                    kb_path,
                )

    async def list_folders(self, user_id: str | None = None) -> list[dict]:
        """List bookmark folders from database.

        Args:
            user_id: Specific user, or None for any configured user.

        Returns:
            List of folder dicts with id, name, kb_path, bookmark_count.
        """
        async with self._pool.acquire() as conn:
            # Use conditional query to avoid asyncpg COALESCE issue with None
            base_query = """
                SELECT
                    f.x_folder_id,
                    f.name,
                    f.kb_path,
                    COUNT(b.tweet_id) as bookmark_count
                FROM x_bookmark_folders f
                LEFT JOIN x_bookmarks_sync b ON f.x_folder_id = b.folder_id
                {where_clause}
                GROUP BY f.x_folder_id, f.name, f.kb_path
                ORDER BY f.name
            """
            if user_id:
                rows = await conn.fetch(
                    base_query.format(where_clause="WHERE f.user_id = $1"),
                    user_id,
                )
            else:
                rows = await conn.fetch(
                    base_query.format(where_clause="")
                )
            return [
                {
                    "id": row["x_folder_id"],
                    "name": row["name"],
                    "kb_path": row["kb_path"],
                    "bookmark_count": row["bookmark_count"],
                }
                for row in rows
            ]

    async def check_folders_available(self) -> bool:
        """Check if folders endpoint is accessible.

        Returns:
            True if folders can be synced, False if disabled.
        """
        if self._folders_available is not None:
            return self._folders_available

        try:
            tokens = await ensure_valid_token(self._pool)
            await self._fetch_folders(tokens.user_id, tokens.access_token)
            return True
        except XBookmarksError as e:
            if e.guru_code == "#XB.00000011.NOFOLDER":
                logger.warning("X Bookmarks folders not available - feature disabled")
                return False
            raise
        except XOAuthError:
            # Not authenticated - can't check
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # API Calls (Legacy - unfiled bookmarks, kept for reference)
    # ─────────────────────────────────────────────────────────────────────────

    async def _fetch_bookmarks_unfiled(
        self, user_id: str, access_token: str
    ) -> dict[str, Any]:
        """Fetch unfiled bookmarks from X API (legacy method).

        NOTE: This fetches ALL bookmarks without folder info.
        The folder-first sync uses _fetch_bookmarks_in_folder instead.

        Args:
            user_id: X user ID.
            access_token: Valid access token.

        Returns:
            Dict with bookmarks_fetched, bookmarks_new, folders_synced.
        """
        bookmarks: list[XBookmark] = []
        pagination_token: str | None = None
        pages_fetched = 0

        async with httpx.AsyncClient() as client:
            while True:
                # Build request URL
                url = f"https://api.twitter.com/2/users/{user_id}/bookmarks"
                params = {
                    "max_results": str(self._config.sync_batch_size),
                    "tweet.fields": "created_at,author_id,text,entities",
                    "expansions": "author_id",
                    "user.fields": "username",
                }
                if pagination_token:
                    params["pagination_token"] = pagination_token

                # Make request
                response = await client.get(
                    url,
                    params=params,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=30.0,
                )

                # Handle rate limiting
                if response.status_code == 429:
                    reset_at = response.headers.get("x-rate-limit-reset")
                    await self._record_rate_limit(
                        user_id,
                        remaining=0,
                        limit=1,
                        reset_at=datetime.fromtimestamp(
                            int(reset_at), tz=timezone.utc
                        )
                        if reset_at
                        else None,
                    )
                    raise XOAuthError(
                        "Rate limit exceeded. Request queued for later.",
                        guru_code="#XB.00000004.RATELIMIT",
                    )

                if response.status_code != 200:
                    raise XOAuthError(
                        f"API error: {response.text}",
                        guru_code="#XB.00000005.APIERROR",
                    )

                # Record rate limit headers
                await self._record_rate_limit(
                    user_id,
                    remaining=int(response.headers.get("x-rate-limit-remaining", 0)),
                    limit=int(response.headers.get("x-rate-limit-limit", 1)),
                    reset_at=datetime.fromtimestamp(
                        int(response.headers.get("x-rate-limit-reset", 0)),
                        tz=timezone.utc,
                    )
                    if response.headers.get("x-rate-limit-reset")
                    else None,
                )

                data = response.json()
                pages_fetched += 1

                # Parse bookmarks
                users = {
                    u["id"]: u["username"]
                    for u in data.get("includes", {}).get("users", [])
                }

                for tweet in data.get("data", []):
                    urls = []
                    media_urls = []
                    entities = tweet.get("entities", {})
                    for url_entity in entities.get("urls", []):
                        expanded = url_entity.get("expanded_url", url_entity.get("url"))
                        if expanded:
                            urls.append(expanded)

                    bookmarks.append(
                        XBookmark(
                            tweet_id=tweet["id"],
                            folder_id=None,  # Folder support requires separate API call
                            folder_name=None,
                            text=tweet.get("text", ""),
                            author_id=tweet.get("author_id", ""),
                            author_username=users.get(tweet.get("author_id", ""), ""),
                            urls=urls,
                            media_urls=media_urls,
                            tweet_created_at=datetime.fromisoformat(
                                tweet["created_at"].replace("Z", "+00:00")
                            )
                            if tweet.get("created_at")
                            else None,
                            bookmarked_at=datetime.now(timezone.utc),
                            metadata={"raw": tweet},
                        )
                    )

                # Check for next page
                meta = data.get("meta", {})
                pagination_token = meta.get("next_token")
                if not pagination_token:
                    break

        # Store bookmarks
        new_count = await self._store_bookmarks(user_id, bookmarks)

        return {
            "bookmarks_fetched": len(bookmarks),
            "bookmarks_new": new_count,
            "folders_synced": 0,  # TODO: folder support
            "pages_fetched": pages_fetched,
        }

    async def _store_bookmarks(
        self, user_id: str, bookmarks: list[XBookmark]
    ) -> int:
        """Store bookmarks in database.

        All bookmarks are expected to have folder_id and folder_name set
        (enforced by folder-first sync flow).

        Args:
            user_id: X user ID.
            bookmarks: List of bookmarks to store (all from folder).

        Returns:
            Number of new bookmarks stored.
        """
        new_count = 0

        async with self._pool.acquire() as conn:
            for bookmark in bookmarks:
                # Check if exists
                exists = await conn.fetchval(
                    "SELECT 1 FROM x_bookmarks_sync WHERE tweet_id = $1",
                    bookmark.tweet_id,
                )

                if not exists:
                    await conn.execute(
                        """
                        INSERT INTO x_bookmarks_sync (
                            tweet_id, folder_id, user_id, content_hash,
                            bookmarked_at, synced_at, metadata
                        ) VALUES ($1, $2, $3, $4, $5, NOW(), $6)
                        """,
                        bookmark.tweet_id,
                        bookmark.folder_id,
                        user_id,
                        bookmark.content_hash,
                        bookmark.bookmarked_at,
                        json.dumps(bookmark.to_dict()),
                    )
                    new_count += 1

        return new_count

    async def _write_folder_manifest_to_kb(
        self, folder_name: str, bookmarks: list[XBookmark]
    ) -> None:
        """Write a folder manifest to KB as a weekly zettelkasten markdown file.

        Creates/updates a manifest file at:
        current/bookmarks/{folder_name}/{YYYY}-W{WW}_{folder_name}.md

        The manifest aggregates all bookmarks synced during the ISO week.

        Args:
            folder_name: Name of the bookmark folder.
            bookmarks: List of bookmarks in the folder.
        """
        kb_root = Path(self._config.kb_root)
        bookmarks_dir = kb_root / "current" / "bookmarks"

        # Sanitize folder name for filesystem
        safe_folder = self._sanitize_folder_name(folder_name)
        target_dir = bookmarks_dir / safe_folder

        # Create directory if needed
        target_dir.mkdir(parents=True, exist_ok=True)

        # Generate weekly filename: YYYY-Www_folder_name.md
        now = datetime.now(timezone.utc)
        iso_year, iso_week, _ = now.isocalendar()
        week_id = f"{iso_year}-W{iso_week:02d}"
        file_path = target_dir / f"{week_id}_{safe_folder}.md"

        # Load existing bookmarks from file if it exists
        existing_tweet_ids: set[str] = set()
        existing_content = ""
        if file_path.exists():
            existing_content = file_path.read_text(encoding="utf-8")
            # Extract existing tweet IDs to avoid duplicates
            import re
            existing_tweet_ids = set(re.findall(r"/status/(\d+)\)", existing_content))

        # Filter to only new bookmarks
        new_bookmarks = [b for b in bookmarks if b.tweet_id not in existing_tweet_ids]
        if not new_bookmarks:
            logger.debug(f"No new bookmarks for {folder_name} this week")
            return

        # Sort new bookmarks by date (newest first)
        sorted_new = sorted(
            new_bookmarks,
            key=lambda b: b.tweet_created_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        # Count total bookmarks (existing + new)
        total_count = len(existing_tweet_ids) + len(new_bookmarks)

        # Build new entries
        new_entries = []
        for bookmark in sorted_new:
            tweet_date = ""
            if bookmark.tweet_created_at:
                tweet_date = bookmark.tweet_created_at.strftime("%Y-%m-%d")

            entry_lines = [
                f"### @{bookmark.author_username}",
                "",
                f"> {bookmark.text}",
                "",
            ]
            if tweet_date:
                entry_lines.append(f"- Posted: {tweet_date}")
            entry_lines.append(
                f"- [View on X](https://x.com/{bookmark.author_username}/status/{bookmark.tweet_id})"
            )

            # Add URLs if present
            if bookmark.urls:
                entry_lines.append("- Links:")
                for url in bookmark.urls:
                    entry_lines.append(f"  - {url}")

            entry_lines.append("")
            new_entries.append("\n".join(entry_lines))

        # Build or update manifest
        if existing_content:
            # Append new entries before the footer
            # Find the footer marker
            footer_marker = "\n---\n\n*Synced from X"
            if footer_marker in existing_content:
                # Insert new entries before footer
                parts = existing_content.rsplit(footer_marker, 1)
                # Update the count in header
                updated_header = re.sub(
                    r"Contains \d+ bookmarked posts",
                    f"Contains {total_count} bookmarked posts",
                    parts[0],
                )
                # Update last sync time
                updated_header = re.sub(
                    r"Last synced: .+",
                    f"Last synced: {now.strftime('%Y-%m-%d %H:%M UTC')}",
                    updated_header,
                )
                content = (
                    updated_header
                    + "\n".join(new_entries)
                    + footer_marker
                    + parts[1]
                )
            else:
                # No footer found, just append
                content = existing_content + "\n" + "\n".join(new_entries)
        else:
            # Create new manifest
            lines = [
                f"# {folder_name}",
                "",
                f"Week {week_id} X Bookmarks",
                f"Contains {total_count} bookmarked posts.",
                f"Last synced: {now.strftime('%Y-%m-%d %H:%M UTC')}",
                "",
                "---",
                "",
            ]
            lines.append("\n".join(new_entries))
            lines.extend([
                "---",
                "",
                f"*Synced from X bookmark folder: {folder_name}*",
            ])
            content = "\n".join(lines)

        # Write file
        file_path.write_text(content, encoding="utf-8")
        logger.info(
            f"Updated weekly manifest: {file_path} "
            f"(+{len(new_bookmarks)} new, {total_count} total)"
        )

    def _sanitize_folder_name(self, name: str) -> str:
        """Sanitize folder name for filesystem use.

        Args:
            name: Original folder name.

        Returns:
            Filesystem-safe folder name.
        """
        import re
        # Replace spaces and special chars with underscores
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", name.lower())
        # Collapse multiple underscores
        safe = re.sub(r"_+", "_", safe)
        # Remove leading/trailing underscores
        return safe.strip("_") or "unfiled"

    # ─────────────────────────────────────────────────────────────────────────
    # Rate Limiting
    # ─────────────────────────────────────────────────────────────────────────

    async def _check_rate_limit(self, user_id: str) -> bool:
        """Check if we can make an API request.

        Args:
            user_id: X user ID.

        Returns:
            True if request can proceed.
        """
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT x_can_request($1)",
                user_id,
            )

    async def _record_rate_limit(
        self,
        user_id: str,
        remaining: int,
        limit: int,
        reset_at: datetime | None,
    ) -> None:
        """Record rate limit state from API response.

        Args:
            user_id: X user ID.
            remaining: Requests remaining.
            limit: Request limit.
            reset_at: When limit resets.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                "SELECT x_record_request($1, $2, $3, $4, $5)",
                user_id,
                "bookmarks",
                remaining,
                limit,
                reset_at,
            )

    async def _queue_request(self, user_id: str, sync_run_id: int) -> int:
        """Queue an API request for later processing.

        Args:
            user_id: X user ID.
            sync_run_id: Associated sync run.

        Returns:
            Request ID.
        """
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT x_queue_bookmark_sync($1, $2)",
                user_id,
                sync_run_id,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Sync Run Management
    # ─────────────────────────────────────────────────────────────────────────

    async def _start_sync_run(self, user_id: str) -> int:
        """Start a sync run.

        Args:
            user_id: X user ID.

        Returns:
            Run ID.
        """
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT x_start_sync_run($1)",
                user_id,
            )

    async def _complete_sync_run(
        self,
        run_id: int,
        status: str,
        bookmarks_fetched: int = 0,
        bookmarks_new: int = 0,
        folders_synced: int = 0,
        pagination_token: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Complete a sync run.

        Args:
            run_id: Run ID.
            status: Final status.
            bookmarks_fetched: Total bookmarks fetched.
            bookmarks_new: New bookmarks stored.
            folders_synced: Folders processed.
            pagination_token: Resume token for rate-limited runs.
            error_message: Error message if failed.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                "SELECT x_complete_sync_run($1, $2, $3, $4, $5, $6, $7)",
                run_id,
                status,
                bookmarks_fetched,
                bookmarks_new,
                folders_synced,
                pagination_token,
                error_message,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Background Queue Processing
    # ─────────────────────────────────────────────────────────────────────────

    async def _has_pending_auth(self) -> bool:
        """Quick check if there are any pending OAuth flows.

        This is a lightweight query to avoid unnecessary KV polling.
        Pending auths have a 5-minute expiry, so we only poll during
        the active auth window.
        """
        async with self._pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM x_oauth_pending WHERE expires_at > NOW()"
            )
            return count > 0

    async def _queue_processor_loop(self) -> None:
        """Background loop to process queued requests and poll for OAuth codes."""
        # OAuth polling state - only poll when auth is potentially active
        oauth_poll_interval = 5  # seconds between KV polls during active auth
        no_auth_check_interval = 30  # seconds between DB checks when no auth active
        last_auth_check = 0.0
        has_pending = False

        while self._running:
            try:
                # Process regular sync queue
                await self._process_queue()
            except Exception as e:
                logger.error(f"Queue processing error: {e}")

            # Check for pending auth flows periodically
            import time
            now = time.time()
            if now - last_auth_check > no_auth_check_interval or has_pending:
                last_auth_check = now
                try:
                    has_pending = await self._has_pending_auth()
                except Exception as e:
                    logger.debug(f"Pending auth check error: {e}")
                    has_pending = False

            # Only poll KV if there's an active auth flow
            if has_pending:
                try:
                    result = await self.poll_kv_for_pending_auth()
                    if result and "error" not in result:
                        logger.info(
                            f"OAuth completed via KV polling: user={result.get('username')}"
                        )
                        # Auth completed, re-check pending status
                        has_pending = await self._has_pending_auth()
                except Exception as e:
                    logger.debug(f"OAuth KV poll error: {e}")
                # Fast poll during active auth
                await asyncio.sleep(oauth_poll_interval)
            else:
                # Slow poll when no auth pending
                await asyncio.sleep(no_auth_check_interval)

    async def _process_queue(self) -> None:
        """Process next queued request if rate limit allows."""
        async with self._pool.acquire() as conn:
            # Mark executing requests
            count = await conn.fetchval("SELECT x_process_request_queue()")
            if count > 0:
                logger.info(f"Marked {count} requests for processing")

            # Get requests to execute
            rows = await conn.fetch(
                """
                SELECT id, user_id, sync_run_id, pagination_token
                FROM x_api_requests
                WHERE status = 'executing'
                """
            )

            for row in rows:
                try:
                    # Get token
                    tokens = await ensure_valid_token(self._pool, row["user_id"])

                    # Execute fetch (using legacy unfiled method)
                    result = await self._fetch_bookmarks_unfiled(
                        row["user_id"], tokens.access_token
                    )

                    # Complete request
                    await conn.execute(
                        """
                        UPDATE x_api_requests
                        SET status = 'completed', completed_at = NOW(), response_status = 200
                        WHERE id = $1
                        """,
                        row["id"],
                    )

                    # Complete sync run
                    if row["sync_run_id"]:
                        await self._complete_sync_run(
                            row["sync_run_id"],
                            status="completed",
                            bookmarks_fetched=result["bookmarks_fetched"],
                            bookmarks_new=result["bookmarks_new"],
                        )

                    logger.info(
                        f"Processed queued request {row['id']}: "
                        f"{result['bookmarks_new']} new bookmarks"
                    )

                except XOAuthError as e:
                    await conn.execute(
                        """
                        UPDATE x_api_requests
                        SET status = 'failed', completed_at = NOW(), error_message = $2
                        WHERE id = $1
                        """,
                        row["id"],
                        str(e),
                    )
                    logger.error(f"Request {row['id']} failed: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Iceberg and Work Queue
    # ─────────────────────────────────────────────────────────────────────────

    async def _write_to_iceberg(self) -> int:
        """Write unsynced bookmarks to Iceberg raw.bookmarks table.

        Uses write_x_bookmarks_to_iceberg from gaius.hx which:
        - Selects bookmarks where iceberg_id IS NULL
        - Writes them to Iceberg raw.bookmarks partition
        - Updates PostgreSQL with iceberg_id

        Idempotent: only writes bookmarks not yet in Iceberg.

        Returns:
            Number of records written.
        """
        from gaius.hx import get_catalog, write_x_bookmarks_to_iceberg

        catalog = get_catalog()
        return await write_x_bookmarks_to_iceberg(self._pool, catalog)

    async def _populate_kb_work_queue(self) -> int:
        """Populate work queue for KB sync.

        Adds bookmarks not yet in KB work queue to x_api_requests table
        for rate-limited processing.

        Idempotent: skips bookmarks already queued or completed.

        Returns:
            Number of items added to queue.
        """
        async with self._pool.acquire() as conn:
            # Insert bookmarks not yet in queue
            result = await conn.execute("""
                INSERT INTO x_api_requests (request_type, request_id, priority, status, metadata)
                SELECT
                    'bookmark_to_kb',
                    tweet_id,
                    1,  -- normal priority
                    'pending',
                    jsonb_build_object(
                        'folder_id', folder_id,
                        'user_id', user_id
                    )
                FROM x_bookmarks_sync
                WHERE kb_manifest_path IS NULL
                AND tweet_id NOT IN (
                    SELECT request_id FROM x_api_requests
                    WHERE request_type = 'bookmark_to_kb'
                )
            """)
            # Parse INSERT result like "INSERT 0 5"
            if result and " " in result:
                parts = result.split()
                if len(parts) >= 3:
                    try:
                        return int(parts[2])
                    except ValueError:
                        pass
            return 0

    # ─────────────────────────────────────────────────────────────────────────
    # Status
    # ─────────────────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Get service status.

        Returns:
            Status dict.
        """
        return {
            "running": self._running,
            "total_syncs": self._total_syncs,
            "total_bookmarks": self._total_bookmarks,
            "last_sync_at": (
                self._last_sync_at.isoformat() if self._last_sync_at else None
            ),
            "queue_poll_interval_s": self._config.queue_poll_interval_s,
        }

    @property
    def is_running(self) -> bool:
        """Whether service is running."""
        return self._running

    # ─────────────────────────────────────────────────────────────────────────
    # Test/Debug
    # ─────────────────────────────────────────────────────────────────────────

    async def emit_test_event(
        self, event_type: str = "XB_AUTH_COMPLETED"
    ) -> dict[str, Any]:
        """Fire a simulated XB event for testing the event propagation chain.

        This allows verifying the complete flow without requiring actual OAuth.
        The event will be fully traced via OTel:
          trigger -> emit -> broadcast -> panel_update

        Args:
            event_type: Event type to simulate (XB_AUTH_COMPLETED, XB_AUTH_FAILED,
                       XB_STATUS_CHANGED). Defaults to XB_AUTH_COMPLETED.

        Returns:
            Dict with success status and event details.
        """
        from gaius.core.telemetry import get_tracer, XBAuthAttrs

        tracer = get_tracer()
        with tracer.start_as_current_span("xb.auth_event.trigger") as span:
            span.set_attribute(XBAuthAttrs.EVENT_TYPE, event_type)
            span.set_attribute(XBAuthAttrs.IS_TEST, True)

            test_data: dict[str, Any] = {
                "user_id": "test_user_123",
                "username": "test_user",
                "is_test": True,
            }

            span.add_event("xb.test_event.emitting")
            self._emit_event(event_type, test_data)
            span.add_event("xb.test_event.emitted")

            logger.info(f"Emitted test event: {event_type}")

            return {
                "success": True,
                "event_type": event_type,
                "data": test_data,
            }
