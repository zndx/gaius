"""Security controls for ACP GitHub integration.

This module implements multi-layer protection against information leakage
and prompt injection attacks via GitHub issue workflows:

1. **HOCON Configuration**: Repository must be explicitly configured
2. **Visibility Verification**: Repository must have private visibility
3. **Allowlist Validation**: Repository must be in explicit allowlist
4. **Runtime Checks**: Continuous verification during ACP sessions

Attack Vectors Mitigated:
- Information leakage via issues opened on public repos
- Prompt injection from issues on attacker-controlled public repos
- Credential exposure in issue comments
- Repository confusion attacks

Guru Meditation: #ACP.SEC.* for security-related failures
"""

import asyncio
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# Git Remote Helper
# =============================================================================


def get_github_repo_from_remote(remote_name: str = "internal") -> str | None:
    """Read GitHub repo URL from git remote.

    Parses git remote URLs and returns in normalized format:
    - "github.com/owner/repo" for github.com
    - "github.example.com/owner/repo" for on-prem GitHub Enterprise

    Supports:
    - git@github.com:owner/repo.git (SSH)
    - https://github.com/owner/repo.git (HTTPS)
    - git@github.example.com:owner/repo.git (on-prem SSH)
    - https://github.example.com/owner/repo (on-prem HTTPS)

    Args:
        remote_name: Git remote name to read (default: "internal")

    Returns:
        Normalized repo URL like "github.com/owner/repo" or None if not found
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", remote_name],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=Path(__file__).parent.parent.parent.parent,  # Project root
        )
        if result.returncode != 0:
            logger.debug(f"Git remote '{remote_name}' not found: {result.stderr}")
            return None

        url = result.stdout.strip()
        return parse_git_remote_url(url)

    except subprocess.TimeoutExpired:
        logger.warning(f"Timeout reading git remote '{remote_name}'")
        return None
    except FileNotFoundError:
        logger.debug("Git command not found")
        return None
    except Exception as e:
        logger.debug(f"Error reading git remote '{remote_name}': {e}")
        return None


def parse_git_remote_url(url: str) -> str | None:
    """Parse git remote URL and return normalized format.

    Args:
        url: Git remote URL (SSH or HTTPS format)

    Returns:
        Normalized format "host/owner/repo" or None if unparseable
    """
    # SSH format: git@github.com:owner/repo.git
    ssh_pattern = r"^git@([^:]+):([^/]+)/([^/]+?)(?:\.git)?$"
    ssh_match = re.match(ssh_pattern, url)
    if ssh_match:
        host, owner, repo = ssh_match.groups()
        return f"{host}/{owner}/{repo}"

    # HTTPS format: https://github.com/owner/repo.git or https://github.com/owner/repo
    https_pattern = r"^https?://([^/]+)/([^/]+)/([^/]+?)(?:\.git)?$"
    https_match = re.match(https_pattern, url)
    if https_match:
        host, owner, repo = https_match.groups()
        return f"{host}/{owner}/{repo}"

    logger.debug(f"Could not parse git remote URL: {url}")
    return None


class GitHubSecurityError(Exception):
    """Security violation in GitHub operations.

    Guru Meditation: #ACP.SEC.00000001.GHSEC
    """

    pass


class RepositoryNotAllowedError(GitHubSecurityError):
    """Repository not in allowlist.

    Guru Meditation: #ACP.SEC.00000002.NOTALLOWED
    """

    pass


class RepositoryNotPrivateError(GitHubSecurityError):
    """Repository is not private.

    Guru Meditation: #ACP.SEC.00000003.NOTPRIVATE
    """

    pass


class RepositoryNotConfiguredError(GitHubSecurityError):
    """Repository not configured in HOCON.

    Guru Meditation: #ACP.SEC.00000004.NOTCONFIGURED
    """

    pass


@dataclass
class GitHubSecurityConfig:
    """Security configuration for GitHub integration.

    Attributes:
        allowed_repos: Explicit allowlist of owner/repo patterns
        require_private: Require private visibility (strongly recommended)
        verify_on_each_operation: Re-verify visibility on each gh operation
        config_file: Path to HOCON config file with repository settings
        cache_visibility_seconds: How long to cache visibility checks
    """

    allowed_repos: list[str] = field(default_factory=list)
    require_private: bool = True
    verify_on_each_operation: bool = True
    config_file: Path | None = None
    cache_visibility_seconds: int = 300  # 5 minutes

    # Internal state
    _visibility_cache: dict[str, tuple[str, float]] = field(
        default_factory=dict, repr=False
    )


def load_security_config(config_path: Path | None = None) -> GitHubSecurityConfig:
    """Load GitHub security configuration from HOCON file.

    The HOCON config should have a section like:

    ```hocon
    acp {
      github {
        # Explicit allowlist - only these repos can be used
        allowed_repos = [
          "zndx/gaius-internal"
          "zndx/gaius-acp-issues"
        ]

        # Require private visibility (recommended: true)
        require_private = true

        # Re-verify on each operation (recommended: true)
        verify_on_each_operation = true
      }
    }
    ```

    Args:
        config_path: Path to HOCON config file. If None, uses defaults.

    Returns:
        GitHubSecurityConfig with loaded settings
    """
    config = GitHubSecurityConfig()

    if config_path is None:
        # Check default locations
        candidates = [
            Path.home() / ".config/gaius/acp.conf",
            Path.home() / ".gaius/acp.conf",
            Path.cwd() / "config/acp.conf",
            Path.cwd() / ".gaius/acp.conf",
        ]
        for candidate in candidates:
            if candidate.exists():
                config_path = candidate
                break

    if config_path is None or not config_path.exists():
        logger.warning(
            "No ACP security config found. Using restrictive defaults. "
            "Create config at ~/.config/gaius/acp.conf"
        )
        # Default: empty allowlist means no repos allowed
        return config

    config.config_file = config_path

    try:
        # Try pyhocon for HOCON parsing
        from pyhocon import ConfigFactory

        hocon = ConfigFactory.parse_file(str(config_path))

        acp_section = hocon.get("acp", {})
        gh_section = acp_section.get("github", {})

        config.allowed_repos = gh_section.get("allowed_repos", [])
        config.require_private = gh_section.get("require_private", True)
        config.verify_on_each_operation = gh_section.get(
            "verify_on_each_operation", True
        )
        config.cache_visibility_seconds = gh_section.get(
            "cache_visibility_seconds", 300
        )

        logger.info(
            f"Loaded ACP security config from {config_path}: "
            f"{len(config.allowed_repos)} allowed repos, "
            f"require_private={config.require_private}"
        )

    except ImportError:
        logger.warning("pyhocon not installed. Using JSON fallback for config.")
        # Fallback to JSON parsing (subset of HOCON)
        try:
            with open(config_path) as f:
                data = json.load(f)
            gh_section = data.get("acp", {}).get("github", {})
            config.allowed_repos = gh_section.get("allowed_repos", [])
            config.require_private = gh_section.get("require_private", True)
            config.verify_on_each_operation = gh_section.get(
                "verify_on_each_operation", True
            )
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse config as JSON: {e}")

    except Exception as e:
        logger.error(f"Failed to load ACP security config: {e}")

    return config


def validate_repo_format(repo: str) -> tuple[str | None, str, str]:
    """Validate and parse repository format.

    Supports two formats:
    - "owner/repo" - legacy format (github.com assumed)
    - "host/owner/repo" - full URL format for on-prem GitHub Enterprise

    Args:
        repo: Repository in "owner/repo" or "host/owner/repo" format

    Returns:
        Tuple of (host, owner, repo_name) where host is None for legacy format

    Raises:
        GitHubSecurityError: If format is invalid
    """
    # Full URL format: host/owner/repo (e.g., github.com/zndx/gaius-acp)
    full_url_pattern = r"^([a-zA-Z0-9][-a-zA-Z0-9.]*\.[a-zA-Z]{2,})/([a-zA-Z0-9][-a-zA-Z0-9]*)/([a-zA-Z0-9][-a-zA-Z0-9_.]*)$"
    full_match = re.match(full_url_pattern, repo)
    if full_match:
        host, owner, repo_name = full_match.groups()
        return host, owner, repo_name

    # Legacy format: owner/repo (github.com assumed)
    legacy_pattern = r"^([a-zA-Z0-9][-a-zA-Z0-9]*)/([a-zA-Z0-9][-a-zA-Z0-9_.]*)$"
    legacy_match = re.match(legacy_pattern, repo)
    if legacy_match:
        owner, repo_name = legacy_match.groups()
        return None, owner, repo_name

    raise GitHubSecurityError(
        f"Invalid repository format: {repo!r}. "
        f"Expected 'owner/repo' or 'host/owner/repo' with alphanumeric characters.\n"
        f"Guru Meditation: #ACP.SEC.00000005.BADFORMAT"
    )


def is_repo_in_allowlist(repo: str, allowed_repos: list[str]) -> bool:
    """Check if repository is in the allowlist.

    Supports exact matches and glob patterns for both formats:

    Full URL format (recommended for on-prem support):
    - "github.com/zndx/gaius-acp" - exact match
    - "github.com/zndx/*" - any repo under zndx org on github.com
    - "github.example.com/*/gaius-*" - any gaius-prefixed repo on on-prem

    Legacy format (github.com assumed):
    - "zndx/gaius-internal" - exact match
    - "zndx/*" - any repo under zndx org

    Args:
        repo: Repository to check ("owner/repo" or "host/owner/repo")
        allowed_repos: List of allowed patterns

    Returns:
        True if repo matches any pattern
    """
    repo_host, repo_owner, repo_name = validate_repo_format(repo)

    for pattern in allowed_repos:
        parts = pattern.split("/")

        if len(parts) == 3:
            # Full URL pattern: host/owner/repo
            pattern_host, pattern_owner, pattern_name = parts
        elif len(parts) == 2:
            # Legacy pattern: owner/repo (github.com assumed)
            pattern_host = None
            pattern_owner, pattern_name = parts
        else:
            logger.warning(f"Invalid allowlist pattern: {pattern}")
            continue

        # Check host (None matches github.com or None)
        if pattern_host is not None and repo_host is not None:
            if pattern_host != "*" and pattern_host != repo_host:
                continue
        elif pattern_host is not None and repo_host is None:
            # Pattern has host but repo doesn't - repo assumes github.com
            if pattern_host != "*" and pattern_host != "github.com":
                continue
        elif pattern_host is None and repo_host is not None:
            # Pattern is legacy, repo has explicit host - only match github.com
            if repo_host != "github.com":
                continue

        # Check owner
        if pattern_owner != "*" and pattern_owner != repo_owner:
            continue

        # Check name (support * suffix for prefix matching)
        if pattern_name == "*":
            return True
        if pattern_name.endswith("*"):
            prefix = pattern_name[:-1]
            if repo_name.startswith(prefix):
                return True
        elif pattern_name == repo_name:
            return True

    return False


async def verify_repo_visibility(repo: str, timeout: float = 10.0) -> str:
    """Verify repository visibility using gh CLI.

    Args:
        repo: Repository in "owner/repo" or "host/owner/repo" format
        timeout: Timeout in seconds for gh command

    Returns:
        Visibility string: "private", "public", "internal"

    Raises:
        GitHubSecurityError: If verification fails
    """
    host, owner, name = validate_repo_format(repo)

    try:
        # Build gh api command - host is used for GH_HOST env var if on-prem
        env = None
        if host and host != "github.com":
            env = {**os.environ, "GH_HOST": host}

        # Use gh api to get repository info
        proc = await asyncio.create_subprocess_exec(
            "gh",
            "api",
            f"repos/{owner}/{name}",
            "--jq",
            ".visibility",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        if proc.returncode != 0:
            error_msg = stderr.decode().strip()
            raise GitHubSecurityError(
                f"Failed to verify repository visibility for {repo}: {error_msg}\n"
                f"Guru Meditation: #ACP.SEC.00000006.GHAPIFAIL"
            )

        visibility = stdout.decode().strip().lower()

        if visibility not in ("private", "public", "internal"):
            raise GitHubSecurityError(
                f"Unknown visibility {visibility!r} for {repo}\n"
                f"Guru Meditation: #ACP.SEC.00000007.UNKNOWNVIS"
            )

        return visibility

    except asyncio.TimeoutError:
        raise GitHubSecurityError(
            f"Timeout verifying repository visibility for {repo}\n"
            f"Guru Meditation: #ACP.SEC.00000008.TIMEOUT"
        )
    except FileNotFoundError:
        raise GitHubSecurityError(
            "gh CLI not found. Install with: brew install gh\n"
            "Guru Meditation: #ACP.SEC.00000009.NOCLI"
        )


def verify_repo_visibility_sync(repo: str, timeout: float = 10.0) -> str:
    """Synchronous version of verify_repo_visibility.

    Args:
        repo: Repository in "owner/repo" or "host/owner/repo" format
        timeout: Timeout in seconds

    Returns:
        Visibility string: "private", "public", "internal"
    """
    host, owner, name = validate_repo_format(repo)

    # Build environment for on-prem GitHub
    env = None
    if host and host != "github.com":
        env = {**os.environ, "GH_HOST": host}

    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{owner}/{name}", "--jq", ".visibility"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

        if result.returncode != 0:
            raise GitHubSecurityError(
                f"Failed to verify repository visibility for {repo}: {result.stderr}\n"
                f"Guru Meditation: #ACP.SEC.00000006.GHAPIFAIL"
            )

        visibility = result.stdout.strip().lower()

        if visibility not in ("private", "public", "internal"):
            raise GitHubSecurityError(
                f"Unknown visibility {visibility!r} for {repo}\n"
                f"Guru Meditation: #ACP.SEC.00000007.UNKNOWNVIS"
            )

        return visibility

    except subprocess.TimeoutExpired:
        raise GitHubSecurityError(
            f"Timeout verifying repository visibility for {repo}\n"
            f"Guru Meditation: #ACP.SEC.00000008.TIMEOUT"
        )
    except FileNotFoundError:
        raise GitHubSecurityError(
            "gh CLI not found. Install with: brew install gh\n"
            "Guru Meditation: #ACP.SEC.00000009.NOCLI"
        )


class GitHubSecurityGuard:
    """Multi-layer security guard for GitHub operations.

    Usage:
        guard = GitHubSecurityGuard.from_config()

        # Verify before any GitHub operation
        await guard.verify_repo("zndx/gaius-internal")

        # Or synchronously
        guard.verify_repo_sync("zndx/gaius-internal")

    All GitHub operations in ACP should go through this guard.
    """

    def __init__(self, config: GitHubSecurityConfig):
        self.config = config
        self._visibility_cache: dict[str, tuple[str, float]] = {}

    @classmethod
    def from_config(cls, config_path: Path | None = None) -> "GitHubSecurityGuard":
        """Create guard from HOCON configuration."""
        config = load_security_config(config_path)
        return cls(config)

    def _check_allowlist(self, repo: str) -> None:
        """Layer 1: Check explicit allowlist."""
        if not self.config.allowed_repos:
            raise RepositoryNotConfiguredError(
                f"No repositories configured in allowlist. "
                f"Add {repo!r} to acp.github.allowed_repos in config.\n"
                f"Guru Meditation: #ACP.SEC.00000004.NOTCONFIGURED"
            )

        if not is_repo_in_allowlist(repo, self.config.allowed_repos):
            raise RepositoryNotAllowedError(
                f"Repository {repo!r} not in allowlist. "
                f"Allowed: {self.config.allowed_repos}\n"
                f"Guru Meditation: #ACP.SEC.00000002.NOTALLOWED"
            )

    async def _check_visibility(self, repo: str) -> None:
        """Layer 2: Verify private visibility."""
        if not self.config.require_private:
            return

        # Check cache
        import time

        now = time.time()
        if repo in self._visibility_cache:
            visibility, cached_at = self._visibility_cache[repo]
            if now - cached_at < self.config.cache_visibility_seconds:
                if visibility != "private":
                    raise RepositoryNotPrivateError(
                        f"Repository {repo!r} has visibility {visibility!r}, "
                        f"but private is required.\n"
                        f"Guru Meditation: #ACP.SEC.00000003.NOTPRIVATE"
                    )
                return

        # Verify visibility
        visibility = await verify_repo_visibility(repo)
        self._visibility_cache[repo] = (visibility, now)

        if visibility != "private":
            raise RepositoryNotPrivateError(
                f"Repository {repo!r} has visibility {visibility!r}, "
                f"but private is required.\n"
                f"Guru Meditation: #ACP.SEC.00000003.NOTPRIVATE"
            )

        logger.info(f"Verified {repo} is private")

    def _check_visibility_sync(self, repo: str) -> None:
        """Synchronous visibility check."""
        if not self.config.require_private:
            return

        import time

        now = time.time()
        if repo in self._visibility_cache:
            visibility, cached_at = self._visibility_cache[repo]
            if now - cached_at < self.config.cache_visibility_seconds:
                if visibility != "private":
                    raise RepositoryNotPrivateError(
                        f"Repository {repo!r} has visibility {visibility!r}, "
                        f"but private is required.\n"
                        f"Guru Meditation: #ACP.SEC.00000003.NOTPRIVATE"
                    )
                return

        visibility = verify_repo_visibility_sync(repo)
        self._visibility_cache[repo] = (visibility, now)

        if visibility != "private":
            raise RepositoryNotPrivateError(
                f"Repository {repo!r} has visibility {visibility!r}, "
                f"but private is required.\n"
                f"Guru Meditation: #ACP.SEC.00000003.NOTPRIVATE"
            )

        logger.info(f"Verified {repo} is private")

    async def verify_repo(self, repo: str) -> None:
        """Verify repository passes all security checks.

        Args:
            repo: Repository in "owner/repo" format

        Raises:
            GitHubSecurityError: If any security check fails
        """
        # Layer 0: Format validation
        validate_repo_format(repo)

        # Layer 1: Allowlist check
        self._check_allowlist(repo)

        # Layer 2: Visibility check
        await self._check_visibility(repo)

        logger.debug(f"Repository {repo} passed all security checks")

    def verify_repo_sync(self, repo: str) -> None:
        """Synchronous version of verify_repo."""
        validate_repo_format(repo)
        self._check_allowlist(repo)
        self._check_visibility_sync(repo)
        logger.debug(f"Repository {repo} passed all security checks")

    def clear_cache(self) -> None:
        """Clear visibility cache (for testing or after config change)."""
        self._visibility_cache.clear()


# =============================================================================
# Issue Content Sanitization
# =============================================================================


def sanitize_issue_content(content: str) -> str:
    """Sanitize content before including in GitHub issues.

    Removes or redacts:
    - API keys and tokens
    - Passwords and secrets
    - Internal paths that might leak info
    - Potential prompt injection markers

    Args:
        content: Raw content to sanitize

    Returns:
        Sanitized content safe for issue body/comments
    """
    # Pattern for common secrets
    # Note: Order matters! Specific patterns should come before generic ones
    secret_patterns = [
        # Anthropic API keys: sk-ant-api03-... (before generic sk- patterns)
        (r"sk-ant-[a-zA-Z0-9_-]{20,}", r"[REDACTED_ANTHROPIC_KEY]"),
        # OpenAI keys: sk-... or sk-proj-... (project keys)
        (r"sk-proj-[a-zA-Z0-9_-]+", r"[REDACTED_OPENAI_KEY]"),
        (r"sk-[a-zA-Z0-9]{20,}", r"[REDACTED_OPENAI_KEY]"),
        # GitHub tokens (various lengths) - before generic token pattern
        (r"ghp_[a-zA-Z0-9]+", r"[REDACTED_GH_PAT]"),
        (r"gho_[a-zA-Z0-9]+", r"[REDACTED_GH_OAUTH]"),
        (r"ghs_[a-zA-Z0-9]+", r"[REDACTED_GH_APP]"),
        (r"ghr_[a-zA-Z0-9]+", r"[REDACTED_GH_REFRESH]"),
        # AWS keys
        (r"AKIA[A-Z0-9]{16}", r"[REDACTED_AWS_KEY]"),
        # Generic bearer tokens
        (r"(Bearer\s+)[a-zA-Z0-9_.-]{20,}", r"\1[REDACTED_BEARER]"),
        # Generic patterns (after specific ones)
        (r"(ANTHROPIC_API_KEY\s*=\s*)[^\s]+", r"\1[REDACTED]"),
        (r"(api[_-]?key\s*[=:]\s*)['\"]?[\w-]{20,}['\"]?", r"\1[REDACTED]"),
        (r"(token\s*[=:]\s*)['\"]?[\w-]{20,}['\"]?", r"\1[REDACTED]"),
        (r"(password\s*[=:]\s*)['\"]?[^\s'\"]+['\"]?", r"\1[REDACTED]"),
        (r"(secret\s*[=:]\s*)['\"]?[^\s'\"]+['\"]?", r"\1[REDACTED]"),
    ]

    result = content
    for pattern, replacement in secret_patterns:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    # Remove potential prompt injection markers
    # These patterns could be used to inject instructions into the issue
    injection_patterns = [
        r"<\|system\|>",
        r"<\|user\|>",
        r"<\|assistant\|>",
        r"\[INST\]",
        r"\[/INST\]",
        r"<<SYS>>",
        r"<</SYS>>",
        r"Human:",
        r"Assistant:",
        # Common prompt injection attempts
        r"IGNORE\s+(ALL\s+)?(PREVIOUS|PRIOR|ABOVE)\s+(INSTRUCTIONS?|PROMPTS?|CONTEXT)",
        r"DISREGARD\s+(ALL\s+)?(PREVIOUS|PRIOR|ABOVE)\s+(INSTRUCTIONS?|PROMPTS?|CONTEXT)",
        r"FORGET\s+(ALL\s+)?(PREVIOUS|PRIOR|ABOVE)\s+(INSTRUCTIONS?|PROMPTS?|CONTEXT)",
        r"NEW\s+INSTRUCTIONS?:",
        r"SYSTEM\s+OVERRIDE:",
        r"ADMIN\s+MODE:",
        r"DEVELOPER\s+MODE:",
        r"JAILBREAK",
        r"DAN\s+MODE",
    ]

    for pattern in injection_patterns:
        result = re.sub(pattern, "[SANITIZED]", result, flags=re.IGNORECASE)

    return result


def validate_issue_title(title: str) -> str:
    """Validate and sanitize issue title.

    Args:
        title: Proposed issue title

    Returns:
        Validated title

    Raises:
        GitHubSecurityError: If title is suspicious
    """
    # Must start with [HEALTH-FIX] prefix
    if not title.startswith("[HEALTH-FIX]"):
        raise GitHubSecurityError(
            f"Issue title must start with [HEALTH-FIX] prefix: {title!r}\n"
            f"Guru Meditation: #ACP.SEC.00000010.BADTITLE"
        )

    # Limit length
    if len(title) > 200:
        title = title[:197] + "..."

    # Remove control characters
    title = "".join(c for c in title if c.isprintable() or c == " ")

    return title
