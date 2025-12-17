"""Card Server Service - Serves Metaflow cards from MinIO/S3.

This service provides HTTP endpoints for viewing Metaflow cards stored in S3,
bypassing the buggy Metaflow UI backend card endpoint.

Endpoints:
- GET /cards/{flow}/{run_id} - List cards for a run
- GET /cards/{flow}/{run_id}/{step}/{task}/{card_id} - Get card HTML
"""

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from aiohttp import web

logger = logging.getLogger(__name__)


@dataclass
class CardServerConfig:
    """Configuration for card server."""

    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8084

    # S3/MinIO configuration
    s3_endpoint: str = field(
        default_factory=lambda: os.environ.get(
            "METAFLOW_S3_ENDPOINT_URL", "http://localhost:9010"
        )
    )
    s3_bucket: str = "metaflow-artifacts"
    s3_card_prefix: str = "metaflow/mf.cards"
    aws_access_key: str = field(
        default_factory=lambda: os.environ.get("AWS_ACCESS_KEY_ID", "minioadmin")
    )
    aws_secret_key: str = field(
        default_factory=lambda: os.environ.get("AWS_SECRET_ACCESS_KEY", "minioadmin")
    )


class CardServerService:
    """HTTP server for serving Metaflow cards from S3."""

    def __init__(self, config: Optional[CardServerConfig] = None):
        self.config = config or CardServerConfig()
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._s3_client = None

    async def start(self) -> None:
        """Start the card server."""
        if not self.config.enabled:
            logger.info("Card server disabled")
            return

        # Initialize S3 client
        try:
            import aioboto3

            self._session = aioboto3.Session()
        except ImportError:
            logger.warning("aioboto3 not available, using boto3 sync client")
            self._session = None

        # Create aiohttp app
        self._app = web.Application()
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/cards", self._handle_list_flows)
        self._app.router.add_get("/cards/{flow}", self._handle_list_runs)
        self._app.router.add_get("/cards/{flow}/{run_id}", self._handle_list_cards)
        self._app.router.add_get(
            "/cards/{flow}/{run_id}/{step}/{task}/{card_id}",
            self._handle_get_card,
        )

        # Start server
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(
            self._runner, self.config.host, self.config.port
        )
        await self._site.start()

        logger.info(f"Card server started on http://{self.config.host}:{self.config.port}")

    async def stop(self) -> None:
        """Stop the card server."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            self._app = None
        logger.info("Card server stopped")

    def _get_s3_client(self):
        """Get synchronous boto3 S3 client."""
        import boto3

        return boto3.client(
            "s3",
            endpoint_url=self.config.s3_endpoint,
            aws_access_key_id=self.config.aws_access_key,
            aws_secret_access_key=self.config.aws_secret_key,
        )

    async def _handle_index(self, request: web.Request) -> web.Response:
        """Index page with links."""
        html = """
<!DOCTYPE html>
<html>
<head><title>Gaius Card Server</title></head>
<body>
<h1>Gaius Card Server</h1>
<p>Serves Metaflow cards from MinIO storage.</p>
<ul>
<li><a href="/cards">Browse Flows</a></li>
</ul>
</body>
</html>
"""
        return web.Response(text=html, content_type="text/html")

    async def _handle_list_flows(self, request: web.Request) -> web.Response:
        """List all flows with cards."""
        try:
            client = self._get_s3_client()
            prefix = f"{self.config.s3_card_prefix}/"

            # List top-level "directories" (flows)
            result = client.list_objects_v2(
                Bucket=self.config.s3_bucket,
                Prefix=prefix,
                Delimiter="/",
            )

            flows = []
            for p in result.get("CommonPrefixes", []):
                flow_name = p["Prefix"].replace(prefix, "").rstrip("/")
                if flow_name:
                    flows.append(flow_name)

            # Generate HTML
            html = f"""
<!DOCTYPE html>
<html>
<head><title>Flows - Gaius Card Server</title></head>
<body>
<h1>Flows with Cards</h1>
<ul>
{"".join(f'<li><a href="/cards/{f}">{f}</a></li>' for f in sorted(flows))}
</ul>
<p><a href="/">Back</a></p>
</body>
</html>
"""
            return web.Response(text=html, content_type="text/html")

        except Exception as e:
            logger.error(f"Error listing flows: {e}")
            return web.Response(text=f"Error: {e}", status=500)

    async def _handle_list_runs(self, request: web.Request) -> web.Response:
        """List runs for a flow."""
        flow = request.match_info["flow"]

        try:
            client = self._get_s3_client()
            prefix = f"{self.config.s3_card_prefix}/{flow}/runs/"

            # List run directories
            result = client.list_objects_v2(
                Bucket=self.config.s3_bucket,
                Prefix=prefix,
                Delimiter="/",
            )

            runs = []
            for p in result.get("CommonPrefixes", []):
                run_id = p["Prefix"].replace(prefix, "").rstrip("/")
                if run_id:
                    runs.append(run_id)

            # Sort numerically if possible
            try:
                runs = sorted(runs, key=lambda x: int(x), reverse=True)
            except ValueError:
                runs = sorted(runs, reverse=True)

            html = f"""
<!DOCTYPE html>
<html>
<head><title>{flow} Runs - Gaius Card Server</title></head>
<body>
<h1>Runs for {flow}</h1>
<ul>
{"".join(f'<li><a href="/cards/{flow}/{r}">Run {r}</a></li>' for r in runs)}
</ul>
<p><a href="/cards">Back to Flows</a></p>
</body>
</html>
"""
            return web.Response(text=html, content_type="text/html")

        except Exception as e:
            logger.error(f"Error listing runs: {e}")
            return web.Response(text=f"Error: {e}", status=500)

    async def _handle_list_cards(self, request: web.Request) -> web.Response:
        """List cards for a specific run."""
        flow = request.match_info["flow"]
        run_id = request.match_info["run_id"]

        try:
            client = self._get_s3_client()
            prefix = f"{self.config.s3_card_prefix}/{flow}/runs/{run_id}/"

            # List all objects under the run
            paginator = client.get_paginator("list_objects_v2")
            cards = []

            for page in paginator.paginate(Bucket=self.config.s3_bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    # Only include .html files (actual cards)
                    if key.endswith(".html"):
                        # Parse path: steps/{step}/tasks/{task}/cards/{card_id}.html
                        match = re.search(
                            r"steps/([^/]+)/tasks/([^/]+)/cards/([^/]+)\.html$",
                            key,
                        )
                        if match:
                            step, task, card_id = match.groups()
                            cards.append({
                                "step": step,
                                "task": task,
                                "card_id": card_id,
                                "size_kb": obj["Size"] // 1024,
                                "modified": obj["LastModified"].isoformat(),
                            })

            # Sort by step order (roughly)
            step_order = {"start": 0, "download_pdf": 1, "convert_to_markdown": 2,
                          "extract_topics": 3, "score_relevance": 4, "save_to_kb": 5, "end": 6}
            cards.sort(key=lambda c: (step_order.get(c["step"], 99), c["task"]))

            # Generate HTML
            card_links = []
            for c in cards:
                url = f"/cards/{flow}/{run_id}/{c['step']}/{c['task']}/{c['card_id']}"
                card_links.append(
                    f'<li><a href="{url}">{c["step"]} (task {c["task"]})</a> '
                    f'- {c["size_kb"]}KB - {c["modified"]}</li>'
                )

            html = f"""
<!DOCTYPE html>
<html>
<head><title>{flow} Run {run_id} Cards - Gaius Card Server</title></head>
<body>
<h1>Cards for {flow} Run {run_id}</h1>
<ul>
{"".join(card_links) if card_links else "<li>No cards found</li>"}
</ul>
<p><a href="/cards/{flow}">Back to Runs</a></p>
</body>
</html>
"""
            return web.Response(text=html, content_type="text/html")

        except Exception as e:
            logger.error(f"Error listing cards: {e}")
            return web.Response(text=f"Error: {e}", status=500)

    async def _handle_get_card(self, request: web.Request) -> web.Response:
        """Get a specific card HTML."""
        flow = request.match_info["flow"]
        run_id = request.match_info["run_id"]
        step = request.match_info["step"]
        task = request.match_info["task"]
        card_id = request.match_info["card_id"]

        try:
            client = self._get_s3_client()
            key = (
                f"{self.config.s3_card_prefix}/{flow}/runs/{run_id}/"
                f"steps/{step}/tasks/{task}/cards/{card_id}.html"
            )

            # Get the card content
            response = client.get_object(Bucket=self.config.s3_bucket, Key=key)
            content = response["Body"].read().decode("utf-8")

            return web.Response(text=content, content_type="text/html")

        except client.exceptions.NoSuchKey:
            return web.Response(text="Card not found", status=404)
        except Exception as e:
            logger.error(f"Error getting card: {e}")
            return web.Response(text=f"Error: {e}", status=500)


async def main():
    """Run card server standalone."""
    logging.basicConfig(level=logging.INFO)

    config = CardServerConfig()
    server = CardServerService(config)

    await server.start()

    try:
        # Keep running
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
