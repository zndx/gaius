"""Profile and domain database operations.

Provides functions for managing profiles and domains:
- list_profiles(): List available profiles
- list_domains(): List domains for a profile
- get_active_domain(): Get current active domain
- set_active_domain(): Set/create active domain
- get_profile_context(): Get combined profile+domain text for agents

Configuration:
    DATABASE_URL=postgresql://user:pass@host:port/db
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

# Lazy import to avoid hard dependency
_asyncpg = None


def _get_asyncpg():
    """Lazy import asyncpg."""
    global _asyncpg
    if _asyncpg is None:
        import asyncpg
        _asyncpg = asyncpg
    return _asyncpg


def get_database_url() -> str:
    """Get database URL from environment.

    Checks GAIUS_DATABASE_URL first (preferred), then falls back to DATABASE_URL.
    Default is the zndx_gaius database at localhost:5438.
    """
    return os.getenv(
        "GAIUS_DATABASE_URL",
        os.getenv("DATABASE_URL", "postgres://gaius:gaius@localhost:5438/zndx_gaius")
    )


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class Profile:
    """Profile configuration."""
    id: int
    name: str
    description: str | None
    profile_text: str | None
    kb_path_prefixes: list[str]
    search_boost: float
    active: bool


@dataclass
class Domain:
    """Domain within a profile."""
    id: int
    profile_id: int
    name: str
    display_name: str | None
    description: str | None
    domain_text: str | None
    kb_path_prefixes: list[str]
    search_boost: float
    is_active: bool


@dataclass
class ProfileContext:
    """Combined profile and domain context for agent prompting."""
    profile: str
    profile_text: str
    profile_prefixes: list[str]
    domain: str | None = None
    domain_text: str | None = None
    domain_prefixes: list[str] = field(default_factory=list)

    def combined_text(self) -> str:
        """Get combined profile + domain text for agent prompting."""
        parts = []
        if self.profile_text:
            parts.append(f"Profile ({self.profile}):\n{self.profile_text}")
        if self.domain and self.domain_text:
            parts.append(f"\nDomain ({self.domain}):\n{self.domain_text}")
        return "\n".join(parts) if parts else ""

    def all_prefixes(self) -> list[str]:
        """Get all KB path prefixes (profile + domain)."""
        return self.profile_prefixes + self.domain_prefixes


# =============================================================================
# Profile Queries
# =============================================================================

async def list_profiles() -> list[Profile]:
    """List all available profiles.

    Returns:
        List of Profile records
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            rows = await conn.fetch("""
                SELECT id, name, description, profile_text,
                       kb_path_prefixes, search_boost, active
                FROM profiles
                WHERE active = TRUE
                ORDER BY name
            """)
            return [
                Profile(
                    id=row["id"],
                    name=row["name"],
                    description=row["description"],
                    profile_text=row["profile_text"],
                    kb_path_prefixes=list(row["kb_path_prefixes"] or []),
                    search_boost=row["search_boost"] or 1.0,
                    active=row["active"],
                )
                for row in rows
            ]
        finally:
            await conn.close()
    except Exception:
        return []


async def get_profile(name: str) -> Profile | None:
    """Get a single profile by name.

    Args:
        name: Profile name

    Returns:
        Profile or None if not found
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            row = await conn.fetchrow("""
                SELECT id, name, description, profile_text,
                       kb_path_prefixes, search_boost, active
                FROM profiles
                WHERE name = $1
            """, name)
            if row:
                return Profile(
                    id=row["id"],
                    name=row["name"],
                    description=row["description"],
                    profile_text=row["profile_text"],
                    kb_path_prefixes=list(row["kb_path_prefixes"] or []),
                    search_boost=row["search_boost"] or 1.0,
                    active=row["active"],
                )
            return None
        finally:
            await conn.close()
    except Exception:
        return None


# =============================================================================
# Domain Queries
# =============================================================================

async def list_domains(profile: str) -> list[Domain]:
    """List domains for a profile.

    Args:
        profile: Profile name

    Returns:
        List of Domain records for the profile
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            rows = await conn.fetch("""
                SELECT pd.id, pd.profile_id, pd.name, pd.display_name,
                       pd.description, pd.domain_text, pd.kb_path_prefixes,
                       pd.search_boost, pd.is_active
                FROM profile_domains pd
                JOIN profiles p ON pd.profile_id = p.id
                WHERE p.name = $1
                ORDER BY pd.name
            """, profile)
            return [
                Domain(
                    id=row["id"],
                    profile_id=row["profile_id"],
                    name=row["name"],
                    display_name=row["display_name"],
                    description=row["description"],
                    domain_text=row["domain_text"],
                    kb_path_prefixes=list(row["kb_path_prefixes"] or []),
                    search_boost=row["search_boost"] or 1.0,
                    is_active=row["is_active"],
                )
                for row in rows
            ]
        finally:
            await conn.close()
    except Exception:
        return []


async def get_active_domain(profile: str) -> str | None:
    """Get the currently active domain for a profile.

    Args:
        profile: Profile name

    Returns:
        Domain name or None if no domain is active
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            row = await conn.fetchrow("""
                SELECT get_active_domain($1) as domain
            """, profile)
            return row["domain"] if row else None
        finally:
            await conn.close()
    except Exception:
        return None


async def get_default_profile() -> str | None:
    """Get the default profile to use when none is specified.

    Uses the database function get_default_profile() which returns
    the profile with is_default=TRUE, or falls back to the first
    active profile if no default is set.

    Returns:
        Profile name or None if no profiles are configured.
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            row = await conn.fetchrow("""
                SELECT get_default_profile() as profile
            """)
            return row["profile"] if row else None
        finally:
            await conn.close()
    except Exception:
        return None


async def get_default_profile_and_domain() -> tuple[str | None, str | None]:
    """Get the default profile and its active domain.

    Uses the database function get_default_profile_and_domain() which
    returns the default profile and its active domain in a single query.

    Returns:
        Tuple of (profile_name, domain_name) - either may be None.
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            row = await conn.fetchrow("""
                SELECT * FROM get_default_profile_and_domain()
            """)
            if row:
                return row["profile_name"], row["domain_name"]
            return None, None
        finally:
            await conn.close()
    except Exception:
        return None, None


async def set_active_domain(profile: str, domain: str | None) -> bool:
    """Set the active domain for a profile.

    Creates the domain if it doesn't exist. Pass None, "", or "open"
    to clear the active domain.

    Args:
        profile: Profile name
        domain: Domain name to activate, or None/"open" to clear

    Returns:
        True if successful, False otherwise
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    # Normalize "open" to clearing the domain
    if domain == "open":
        domain = None

    try:
        conn = await asyncpg.connect(url)
        try:
            result = await conn.fetchval("""
                SELECT set_active_domain($1, $2)
            """, profile, domain or "")
            return bool(result)
        finally:
            await conn.close()
    except Exception:
        return False


# =============================================================================
# Context Queries
# =============================================================================

async def get_profile_context(
    profile: str,
    domain: str | None = None
) -> ProfileContext | None:
    """Get combined profile and domain context for agent prompting.

    Args:
        profile: Profile name
        domain: Optional domain name (None = "open", no domain constraint)

    Returns:
        ProfileContext with combined text and prefixes, or None if profile not found
    """
    asyncpg = _get_asyncpg()
    url = get_database_url()

    try:
        conn = await asyncpg.connect(url)
        try:
            # Get profile info
            profile_row = await conn.fetchrow("""
                SELECT profile_text, kb_path_prefixes
                FROM profiles
                WHERE name = $1
            """, profile)

            if not profile_row:
                return None

            context = ProfileContext(
                profile=profile,
                profile_text=profile_row["profile_text"] or "",
                profile_prefixes=list(profile_row["kb_path_prefixes"] or []),
            )

            # Get domain info if specified
            if domain and domain != "open":
                domain_row = await conn.fetchrow("""
                    SELECT pd.domain_text, pd.kb_path_prefixes
                    FROM profile_domains pd
                    JOIN profiles p ON pd.profile_id = p.id
                    WHERE p.name = $1 AND pd.name = $2
                """, profile, domain)

                if domain_row:
                    context.domain = domain
                    context.domain_text = domain_row["domain_text"]
                    context.domain_prefixes = list(domain_row["kb_path_prefixes"] or [])

            return context
        finally:
            await conn.close()
    except Exception:
        return None


# =============================================================================
# Sync Wrappers (for non-async contexts)
# =============================================================================

def list_profiles_sync() -> list[Profile]:
    """Sync wrapper for list_profiles."""
    import asyncio
    return asyncio.get_event_loop().run_until_complete(list_profiles())


def list_domains_sync(profile: str) -> list[Domain]:
    """Sync wrapper for list_domains."""
    import asyncio
    return asyncio.get_event_loop().run_until_complete(list_domains(profile))


def get_active_domain_sync(profile: str) -> str | None:
    """Sync wrapper for get_active_domain."""
    import asyncio
    return asyncio.get_event_loop().run_until_complete(get_active_domain(profile))


def set_active_domain_sync(profile: str, domain: str | None) -> bool:
    """Sync wrapper for set_active_domain."""
    import asyncio
    return asyncio.get_event_loop().run_until_complete(set_active_domain(profile, domain))


def get_profile_context_sync(profile: str, domain: str | None = None) -> ProfileContext | None:
    """Sync wrapper for get_profile_context."""
    import asyncio
    return asyncio.get_event_loop().run_until_complete(get_profile_context(profile, domain))


def get_default_profile_sync() -> str | None:
    """Sync wrapper for get_default_profile."""
    import asyncio
    return asyncio.get_event_loop().run_until_complete(get_default_profile())


def get_default_profile_and_domain_sync() -> tuple[str | None, str | None]:
    """Sync wrapper for get_default_profile_and_domain."""
    import asyncio
    return asyncio.get_event_loop().run_until_complete(get_default_profile_and_domain())


# =============================================================================
# Profile Config Files (for --profile flag resolution)
# =============================================================================

def list_profile_configs(config_dir: str = "config/profiles") -> list[str]:
    """List available profile config files.

    Profile configs are HOCON files in config/profiles/*.conf

    Args:
        config_dir: Directory containing profile configs

    Returns:
        List of profile names (without .conf extension)
    """
    config_path = Path(config_dir)
    if not config_path.exists():
        return []

    return sorted([
        p.stem for p in config_path.glob("*.conf")
    ])


def get_profile_config_path(profile: str, config_dir: str = "config/profiles") -> Path | None:
    """Get the config file path for a profile.

    Args:
        profile: Profile name
        config_dir: Directory containing profile configs

    Returns:
        Path to config file, or None if not found
    """
    config_path = Path(config_dir) / f"{profile}.conf"
    return config_path if config_path.exists() else None
