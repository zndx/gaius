"""R2 upload and card image_url persistence.

Uploads rendered PNG visualizations to Cloudflare R2 (S3-compatible)
and updates the card's image_url in the database.

Configuration is read from HOCON config (config/base.conf) via get_config().
Environment variables are resolved at config-load time via ${?VAR} substitution.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _get_r2_config() -> dict[str, str]:
    """Read R2 configuration from HOCON config.

    Raises:
        RuntimeError: If required credentials are missing (#VIZ.00000005.UPLOADFAIL)
    """
    from gaius.core.config import get_config

    cfg = get_config().cloudflare
    endpoint = cfg.r2_endpoint
    access_key = cfg.r2.access_key_id
    secret_key = cfg.r2.secret_access_key

    if not all([endpoint, access_key, secret_key]):
        raise RuntimeError(
            "R2 credentials not configured.\n"
            "  #VIZ.00000005.UPLOADFAIL\n"
            "  Set: CF_R2_ACCESS_KEY_ID, CF_R2_SECRET_ACCESS_KEY, CLOUDFLARE_ACCOUNT_ID\n"
            "  Or configure cloudflare section in config/base.conf"
        )

    return {
        "endpoint": endpoint,
        "access_key": access_key,
        "secret_key": secret_key,
        "bucket": cfg.r2.bucket,
        "public_url": cfg.r2.public_url,
    }


async def upload_to_r2(card_id: str, image_path: Path) -> str:
    """Upload a rendered PNG to Cloudflare R2.

    Args:
        card_id: Card identifier (used in object key)
        image_path: Local path to PNG file

    Returns:
        Public URL of the uploaded image

    Raises:
        RuntimeError: On upload failure (#VIZ.00000005.UPLOADFAIL)
    """
    import asyncio

    config = _get_r2_config()

    object_key = f"viz/cards/{card_id}.png"

    # Run boto3 upload in executor (boto3 is sync)
    loop = asyncio.get_event_loop()
    url = await loop.run_in_executor(
        None,
        _upload_sync,
        config,
        object_key,
        image_path,
    )

    logger.info(f"Uploaded {card_id} → {url}")
    return url


def _upload_sync(config: dict[str, str], object_key: str, image_path: Path) -> str:
    """Synchronous R2 upload via boto3."""
    import boto3

    s3 = boto3.client(
        "s3",
        endpoint_url=config["endpoint"],
        aws_access_key_id=config["access_key"],
        aws_secret_access_key=config["secret_key"],
        region_name="auto",
    )

    try:
        s3.upload_file(
            str(image_path),
            config["bucket"],
            object_key,
            ExtraArgs={
                "ContentType": "image/png",
                "CacheControl": "public, max-age=31536000, immutable",
            },
        )
    except Exception as e:
        raise RuntimeError(
            f"R2 upload failed for {object_key}: {e}\n"
            "  #VIZ.00000005.UPLOADFAIL\n"
            "  Check: CF_R2_ACCESS_KEY_ID, CF_R2_SECRET_ACCESS_KEY, CF_R2_BUCKET"
        ) from e

    # Construct public URL
    public_url = config["public_url"]
    if public_url:
        return f"{public_url.rstrip('/')}/{object_key}"
    else:
        return f"{config['endpoint']}/{config['bucket']}/{object_key}"


async def upload_variant_to_r2(card_id: str, variant: str, image_path: Path) -> str:
    """Upload a single resolution variant to R2.

    Args:
        card_id: Card identifier
        variant: Variant name (e.g. "display", "og")
        image_path: Local path to PNG file

    Returns:
        Public URL of the uploaded variant
    """
    import asyncio

    config = _get_r2_config()
    object_key = f"viz/cards/{card_id}/{variant}.png"

    loop = asyncio.get_event_loop()
    url = await loop.run_in_executor(
        None,
        _upload_sync,
        config,
        object_key,
        image_path,
    )

    logger.info(f"Uploaded {card_id}/{variant} → {url}")
    return url


async def upload_card_variants(
    card_id: str, variant_paths: dict[str, Path]
) -> dict[str, str]:
    """Upload all resolution variants for a card to R2.

    Args:
        card_id: Card identifier
        variant_paths: Mapping of variant name to local PNG path

    Returns:
        Mapping of variant name to public URL
    """
    urls: dict[str, str] = {}
    for variant, path in variant_paths.items():
        urls[variant] = await upload_variant_to_r2(card_id, variant, path)
    return urls


async def update_card_image_url(pool: Any, card_id: str, image_url: str) -> None:
    """Update a card's image_url in the database.

    Args:
        pool: asyncpg connection pool
        card_id: Card to update
        image_url: Public URL of the visualization
    """
    await pool.execute(
        """
        UPDATE collections.cards
        SET image_url = $2
        WHERE card_id = $1
        """,
        card_id,
        image_url,
    )
    logger.info(f"Updated card {card_id} image_url = {image_url}")
