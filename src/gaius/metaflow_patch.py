"""
Monkeypatch for Metaflow service metadata provider.

Fixes race condition where heartbeat requests return 404 because
the run/task hasn't been committed to the database yet.

The upstream client only retries on 503, but we also need to retry on 404
for newly-created runs/tasks that haven't been committed yet.

Usage:
    import gaius.metaflow_patch  # Must import before running flow
    from metaflow import FlowSpec, step
"""
import os
import sys
import time
import logging

logger = logging.getLogger(__name__)

# Only apply patch once
_patched = False

# Configuration for 404 retries (race condition fix)
RETRY_404_MAX_ATTEMPTS = 15  # 15 attempts = 30 seconds with 2s delay
RETRY_404_DELAY = 2.0  # Fixed 2 second delay between retries


def patch_service_provider():
    """Patch ServiceMetadataProvider._request to retry on 404."""
    global _patched
    if _patched:
        return

    try:
        from metaflow.plugins.metadata_providers.service import (  # type: ignore[import-untyped] - metaflow lacks type stubs
            ServiceMetadataProvider,
        )
        from metaflow.plugins.metadata_providers.service import ServiceException  # type: ignore[attr-defined] - ServiceException exists but not in stubs
        from metaflow.exception import MetaflowInternalError
        from metaflow.metaflow_config import SERVICE_HEADERS, SERVICE_RETRY_COUNT  # type: ignore[import-untyped] - metaflow lacks type stubs
    except ImportError:
        logger.warning("Could not import metaflow service provider, patch not applied")
        return

    @classmethod
    def patched_request(
        cls,
        monitor,
        path,
        method,
        data=None,
        retry_409_path=None,
        return_raw_resp=False,
    ):
        """Patched _request that retries on 404 for metadata/heartbeat endpoints."""
        from metaflow.exception import MetaflowException

        if cls.INFO is None:
            raise MetaflowException(
                "Missing Metaflow Service URL. "
                "Specify with METAFLOW_SERVICE_URL environment variable"
            )

        supported_methods = ("GET", "PATCH", "POST")
        if method not in supported_methods:
            raise MetaflowException(
                "Only these methods are supported: %s, but got %s"
                % (supported_methods, method)
            )

        url = os.path.join(cls.INFO, path.lstrip("/"))

        # Determine if this is a path where 404 retry makes sense
        # (metadata and heartbeat endpoints for recently created runs/tasks)
        is_retryable_path = any(x in path for x in ["/metadata", "/heartbeat"])

        def _do_request():
            """Execute the HTTP request."""
            if method == "GET":
                if monitor:
                    with monitor.measure("metaflow.service_metadata.get"):
                        return cls._session.get(url, headers=SERVICE_HEADERS.copy())
                else:
                    return cls._session.get(url, headers=SERVICE_HEADERS.copy())
            elif method == "POST":
                if monitor:
                    with monitor.measure("metaflow.service_metadata.post"):
                        return cls._session.post(
                            url, headers=SERVICE_HEADERS.copy(), json=data
                        )
                else:
                    return cls._session.post(
                        url, headers=SERVICE_HEADERS.copy(), json=data
                    )
            elif method == "PATCH":
                if monitor:
                    with monitor.measure("metaflow.service_metadata.patch"):
                        return cls._session.patch(
                            url, headers=SERVICE_HEADERS.copy(), json=data
                        )
                else:
                    return cls._session.patch(
                        url, headers=SERVICE_HEADERS.copy(), json=data
                    )
            else:
                raise MetaflowInternalError("Unexpected HTTP method %s" % (method,))

        # For retryable paths, use our extended 404 retry logic
        if is_retryable_path:
            max_attempts = RETRY_404_MAX_ATTEMPTS
        else:
            max_attempts = SERVICE_RETRY_COUNT

        resp = None
        for i in range(max_attempts):
            try:
                resp = _do_request()
            except MetaflowInternalError:
                raise
            except Exception:
                if monitor:
                    with monitor.count("metaflow.service_metadata.failed_request"):
                        pass
                if i == max_attempts - 1:
                    raise
                resp = None
                time.sleep(RETRY_404_DELAY if is_retryable_path else 2**i)
                continue

            # Handle response
            if return_raw_resp:
                return resp, True

            if resp.status_code < 300:
                return resp.json(), True

            elif resp.status_code == 409 and data is not None:
                # Handle conflict - object already exists
                if retry_409_path:
                    v, _ = cls._request(monitor, retry_409_path, "GET")
                    return v, False
                else:
                    return None, False

            elif resp.status_code == 404:
                if is_retryable_path and i < max_attempts - 1:
                    # PATCH: Retry 404 on metadata/heartbeat - race condition fix
                    print(
                        f"[GU-PATCH-001] Retrying 404 on {path} (attempt {i + 1}/{max_attempts}) - race condition",
                        file=sys.stderr, flush=True
                    )
                    with open("/tmp/gaius_debug.log", "a") as f:
                        f.write(f"[GU-PATCH-001] Retrying 404 on {path} (attempt {i + 1}/{max_attempts})\n")
                    time.sleep(RETRY_404_DELAY)
                    continue
                else:
                    # Non-retryable 404 or retries exhausted - raise
                    raise ServiceException(
                        "Metadata request (%s) failed (code %s): %s"
                        % (path, resp.status_code, resp.text),
                        resp.status_code,
                        resp.text,
                    )

            elif resp.status_code == 503:
                # Service unavailable - retry with exponential backoff
                if i < max_attempts - 1:
                    time.sleep(2**i)
                    continue

            else:
                # Any other error - raise immediately
                raise ServiceException(
                    "Metadata request (%s) failed (code %s): %s"
                    % (path, resp.status_code, resp.text),
                    resp.status_code,
                    resp.text,
                )

        # Exhausted all retries
        if resp:
            raise ServiceException(
                "Metadata request (%s) failed (code %s): %s"
                % (path, resp.status_code, resp.text),
                resp.status_code,
                resp.text,
            )
        else:
            raise ServiceException("Metadata request (%s) failed" % path)

    # Apply patch
    ServiceMetadataProvider._request = patched_request
    _patched = True
    logger.info("Metaflow service provider patched to retry 404 on metadata endpoints (max %d attempts)", RETRY_404_MAX_ATTEMPTS)


def patch_heartbeat():
    """Patch MetadataHeartBeat._heartbeat to be more tolerant of 404s."""
    try:
        from metaflow.metadata_provider.heartbeat import MetadataHeartBeat, HeartBeatException  # type: ignore[import-untyped] - metaflow lacks type stubs
    except ImportError:
        logger.warning("Could not import heartbeat module, patch not applied")
        return

    original_heartbeat = MetadataHeartBeat._heartbeat

    def patched_heartbeat(self):
        """Patched heartbeat that treats 404 as transient."""
        import requests
        import json

        if self.hb_url is not None:
            try:
                response = requests.post(
                    url=self.hb_url, data="{}", headers=self.headers.copy()
                )
            except requests.exceptions.ConnectionError:
                raise HeartBeatException(
                    "HeartBeat request (%s) failed (ConnectionError)" % self.hb_url
                )
            except requests.exceptions.Timeout:
                raise HeartBeatException(
                    "HeartBeat request (%s) failed (Timeout)" % self.hb_url
                )
            except requests.exceptions.RequestException as e:
                raise HeartBeatException(
                    "HeartBeat request (%s) failed (RequestException) %s" % (self.hb_url, str(e))
                )

            if response.status_code == 200:
                return json.loads(response.json()).get("wait_time_in_seconds")
            elif response.status_code == 404:
                # PATCH: Treat 404 as transient - run/task may not be committed yet
                logger.debug("Heartbeat got 404 (run not committed yet), will retry")
                raise HeartBeatException(
                    "HeartBeat request (%s) got 404 (transient, will retry)" % self.hb_url
                )
            else:
                raise HeartBeatException(
                    "HeartBeat request (%s) failed (code %s): %s"
                    % (self.hb_url, response.status_code, response.text)
                )
        return None

    MetadataHeartBeat._heartbeat = patched_heartbeat
    logger.info("Metaflow heartbeat patched to treat 404 as transient")


# Auto-apply patches on import
patch_service_provider()
patch_heartbeat()
