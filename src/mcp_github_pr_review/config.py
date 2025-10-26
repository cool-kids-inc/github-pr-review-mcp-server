"""Configuration management using Pydantic BaseSettings.

This module provides a unified configuration system for the MCP GitHub PR Review server
using Pydantic BaseSettings for validation, type safety, and automatic environment
variable loading.
"""

import logging
import math
from collections.abc import Callable
from functools import lru_cache
from typing import Any, TypeVar, cast

from annotated_types import Ge, Le
from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic.fields import FieldInfo
from pydantic_core import Url
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Type variable for numeric clamping (int or float)
T = TypeVar("T", int, float)


def _clamp_numeric_value(
    v: Any,
    field_info: FieldInfo,
    cast_fn: Callable[[Any], T],
    validity_check: Callable[[T], bool] = lambda x: True,
) -> T:
    """Generic clamping logic for numeric values (int and float).

    This helper consolidates the identical clamping logic previously duplicated
    between clamp_int_values and clamp_float_values validators.

    Args:
        v: The value to validate and clamp
        field_info: Field metadata containing default and constraints
        cast_fn: Function to cast value to target type (int or float)
        validity_check: Optional predicate to check validity (e.g., math.isfinite)

    Returns:
        Clamped numeric value within field constraints
    """
    # Get constraints from field metadata
    ge = _get_ge_constraint(field_info)
    le = _get_le_constraint(field_info)

    # Handle None or missing values -> use default
    if v is None:
        default_val: T = field_info.default
        return default_val

    # Try to convert to target type
    try:
        numeric_val = cast_fn(v)
    except (TypeError, ValueError):
        default_val = field_info.default
        return default_val

    # Type-specific validity check (e.g., reject NaN/inf for floats)
    if not validity_check(numeric_val):
        default_val = field_info.default
        return default_val

    # Clamp to bounds
    if ge is not None:
        numeric_val = max(cast_fn(ge), numeric_val)
    if le is not None:
        numeric_val = min(cast_fn(le), numeric_val)

    return numeric_val


class ServerSettings(BaseSettings):
    """Server configuration with validation and clamping.

    All configuration values are loaded from environment variables with sensible
    defaults. Out-of-range values are automatically clamped to min/max bounds
    to preserve backward compatibility with the previous implementation.

    Environment Variables:
        GITHUB_TOKEN: GitHub Personal Access Token (required)
        GH_HOST: GitHub hostname (default: "github.com")
        GITHUB_API_URL: REST API base URL override (optional)
        GITHUB_GRAPHQL_URL: GraphQL API URL override (optional)
        HTTP_PER_PAGE: Items per page for pagination (default: 100, range: 1-100)
        PR_FETCH_MAX_PAGES: Maximum pages to fetch (default: 50, range: 1-200)
        PR_FETCH_MAX_COMMENTS: Maximum comments to fetch
            (default: 2000, range: 100-100000)
        HTTP_MAX_RETRIES: Maximum HTTP retries (default: 3, range: 0-10)
        HTTP_TIMEOUT: Total HTTP timeout in seconds
            (default: 30.0, range: 1.0-300.0)
        HTTP_CONNECT_TIMEOUT: HTTP connection timeout in seconds
            (default: 10.0, range: 1.0-60.0)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
        frozen=True,
    )

    # GitHub Configuration
    github_token: SecretStr = Field(
        ...,
        description="GitHub Personal Access Token for API authentication (required)",
    )
    gh_host: str = Field(
        default="github.com",
        description="GitHub hostname (use custom domain for GitHub Enterprise)",
    )
    github_api_url: str | None = Field(
        default=None,
        description="Override for GitHub REST API base URL (for enterprise instances)",
    )
    github_graphql_url: str | None = Field(
        default=None,
        description="Override for GitHub GraphQL API URL (for enterprise instances)",
    )

    # Pagination Configuration
    http_per_page: int = Field(
        default=100,
        ge=1,
        le=100,
        description="Number of items per page for API requests",
    )
    pr_fetch_max_pages: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Maximum number of pages to fetch from API",
    )
    pr_fetch_max_comments: int = Field(
        default=2000,
        ge=100,
        le=100000,
        description="Maximum number of comments to fetch per PR",
    )

    # HTTP Configuration
    http_max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum number of HTTP request retries",
    )
    http_timeout: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Total HTTP timeout in seconds",
    )
    http_connect_timeout: float = Field(
        default=10.0,
        ge=1.0,
        le=60.0,
        description="HTTP connection timeout in seconds",
    )

    @field_validator("github_token", mode="before")
    @classmethod
    def validate_github_token(cls, v: Any) -> str:
        """Validate and sanitize GitHub token.

        Args:
            v: The GitHub token value

        Returns:
            The validated token (stripped of whitespace)

        Raises:
            ValueError: If token is whitespace-only
        """
        if v is None:
            msg = (
                "GITHUB_TOKEN is required. "
                "Please provide a valid GitHub Personal Access Token."
            )
            raise ValueError(msg)

        raw_value: str
        if isinstance(v, SecretStr):
            raw_value = v.get_secret_value()
        elif isinstance(v, str):
            raw_value = v
        else:
            msg = (
                "GITHUB_TOKEN must be a string. "
                "Please provide a valid GitHub Personal Access Token."
            )
            raise ValueError(msg)

        # Strip whitespace
        token = raw_value.strip()

        # Reject whitespace-only tokens (empty is caught by required field)
        if not token:
            msg = (
                "GITHUB_TOKEN cannot be whitespace-only. "
                "Please provide a valid GitHub Personal Access Token."
            )
            raise ValueError(msg)

        return token

    @field_validator("github_api_url", "github_graphql_url", mode="before")
    @classmethod
    def validate_url_format(cls, v: Any) -> str | None:
        """Validate URL structure if provided (HTTPS only).

        Uses Pydantic's Url validator for robust URL parsing and validation,
        ensuring consistent behavior with Pydantic's URL handling.

        Args:
            v: The URL value to validate

        Returns:
            The validated HTTPS URL or None if not provided (empty/None)

        Raises:
            ValueError: If URL is provided but invalid (non-string, non-HTTPS,
                       malformed structure, contains spaces, or missing hostname)
        """
        # Allow None or empty string (optional field)
        if v is None or v == "":
            return None

        # Validate type
        if not isinstance(v, str):
            msg = (
                f"URL must be a string, got {type(v).__name__}. "
                "Please provide a valid HTTPS URL."
            )
            raise ValueError(msg)

        # Check for spaces BEFORE stripping (common mistake)
        # This catches cases like "https://   " which would otherwise
        # be stripped to "https://" and give a confusing error
        if " " in v:
            msg = (
                f"URL contains spaces: {v!r}. "
                "URLs cannot contain spaces. Please provide a valid HTTPS URL."
            )
            raise ValueError(msg)

        # Strip whitespace for convenience (only if no spaces inside)
        v = v.strip()

        # Use Pydantic's URL validator for robust parsing
        try:
            parsed = Url(v)
        except Exception as e:
            # Provide user-friendly error messages for common issues
            error_str = str(e).lower()
            if "empty host" in error_str or (
                "missing" in error_str and "host" in error_str
            ):
                msg = (
                    f"URL is missing hostname: {v!r}. "
                    "Please provide a complete HTTPS URL with a hostname."
                )
            elif "scheme" in error_str or "://" not in v:
                msg = (
                    f"URL is missing scheme: {v!r}. "
                    "Please provide a full HTTPS URL (e.g., https://api.github.com)."
                )
            else:
                msg = f"Failed to parse URL {v!r}: {e}"
            raise ValueError(msg) from e

        # Validate HTTPS scheme (Pydantic accepts various schemes)
        if parsed.scheme != "https":
            if parsed.scheme == "http":
                msg = (
                    f"HTTP URLs are not allowed for security reasons: {v!r}. "
                    "Please use HTTPS instead."
                )
            elif parsed.scheme:
                msg = (
                    f"Invalid URL scheme '{parsed.scheme}': {v!r}. "
                    "Only HTTPS URLs are allowed."
                )
            else:
                msg = (
                    f"URL is missing scheme: {v!r}. "
                    "Please provide a full HTTPS URL (e.g., https://api.github.com)."
                )
            raise ValueError(msg)

        # Validate hostname exists (Pydantic's Url.host is None if missing)
        if not parsed.host:
            msg = (
                f"URL is missing hostname: {v!r}. "
                "Please provide a complete HTTPS URL with a hostname."
            )
            raise ValueError(msg)

        # Return the original input (validated, stripped)
        # Note: We return the original input rather than str(parsed) to avoid
        # URL normalization changes (e.g., trailing slashes, port defaults)
        return cast(str, v)

    @field_validator(
        "http_per_page",
        "pr_fetch_max_pages",
        "pr_fetch_max_comments",
        "http_max_retries",
        mode="before",
    )
    @classmethod
    def clamp_int_values(cls, v: Any, info: ValidationInfo) -> int:
        """Clamp integer values to their field constraints.

        This validator preserves the clamping behavior from the old _int_conf
        implementation, where out-of-range values are clamped instead of
        raising validation errors.

        Args:
            v: The value to validate and clamp
            info: Validation info containing field name and context

        Returns:
            Clamped integer value

        Raises:
            RuntimeError: If field_name is missing from ValidationInfo
        """
        # Get field info to access constraints
        field_name = info.field_name
        if field_name is None:
            msg = "Missing field_name in ValidationInfo"
            raise RuntimeError(msg)
        field_info = cls.model_fields[field_name]

        # Use generic clamping helper
        return _clamp_numeric_value(v, field_info, int)

    @field_validator("http_timeout", "http_connect_timeout", mode="before")
    @classmethod
    def clamp_float_values(cls, v: Any, info: ValidationInfo) -> float:
        """Clamp float values to their field constraints.

        This validator preserves the clamping behavior from the old _float_conf
        implementation, where out-of-range values are clamped instead of
        raising validation errors.

        NaN and infinite values (±inf) are treated as invalid and will be
        replaced with the field default.

        Args:
            v: The value to validate and clamp
            info: Validation info containing field name and context

        Returns:
            Clamped float value (finite, within ge/le bounds)

        Raises:
            RuntimeError: If field_name is missing from ValidationInfo
        """
        # Get field info to access constraints
        field_name = info.field_name
        if field_name is None:
            msg = "Missing field_name in ValidationInfo"
            raise RuntimeError(msg)
        field_info = cls.model_fields[field_name]

        # Use generic clamping helper with finite check for floats
        return _clamp_numeric_value(v, field_info, float, math.isfinite)

    @model_validator(mode="after")
    def validate_timeout_consistency(self) -> "ServerSettings":
        """Ensure connect timeout does not exceed total timeout.

        Automatically clamps http_connect_timeout to http_timeout if it's larger,
        maintaining backward compatibility while preventing misconfiguration.

        Returns:
            Self with adjusted timeout values if needed
        """
        if self.http_connect_timeout > self.http_timeout:
            # Clamp connect timeout to not exceed total timeout
            # Use object.__setattr__ since model is frozen
            old_connect_timeout = self.http_connect_timeout
            object.__setattr__(self, "http_connect_timeout", self.http_timeout)

            # Log for observability
            logger.warning(
                "http_connect_timeout (%s) exceeded http_timeout (%s); clamped to %s",
                old_connect_timeout,
                self.http_timeout,
                self.http_timeout,
            )

        return self

    def with_overrides(
        self,
        *,
        per_page: int | None = None,
        max_pages: int | None = None,
        max_comments: int | None = None,
        max_retries: int | None = None,
    ) -> "ServerSettings":
        """Create a new settings instance with override values.

        This method provides backward compatibility with the override mechanism
        from the old _int_conf implementation, where function parameters could
        override environment variables.

        Args:
            per_page: Override for http_per_page
            max_pages: Override for pr_fetch_max_pages
            max_comments: Override for pr_fetch_max_comments
            max_retries: Override for http_max_retries

        Returns:
            New ServerSettings instance with overridden values
        """
        overrides = {}
        if per_page is not None:
            overrides["http_per_page"] = per_page
        if max_pages is not None:
            overrides["pr_fetch_max_pages"] = max_pages
        if max_comments is not None:
            overrides["pr_fetch_max_comments"] = max_comments
        if max_retries is not None:
            overrides["http_max_retries"] = max_retries

        # Create new instance with overrides
        # Use model_validate to ensure validators run on override values
        data = self.model_dump()
        data.update(overrides)
        return self.__class__.model_validate(data)


@lru_cache
def get_settings() -> ServerSettings:
    """Get or create the global settings instance (thread-safe via lru_cache).

    Returns:
        ServerSettings instance loaded from environment
    """
    return ServerSettings()


def _get_ge_constraint(field_info: FieldInfo) -> int | float | None:
    """Extract the >= constraint value from field metadata.

    Pydantic v2 stores Field(ge=...) constraints as annotated-types metadata.
    This helper extracts the constraint value for use in custom clamping logic.

    Args:
        field_info: Pydantic field metadata

    Returns:
        The >= constraint value if present, None otherwise
    """
    for meta in field_info.metadata:
        if isinstance(meta, Ge):
            return cast(float | int | None, meta.ge)
    return None


def _get_le_constraint(field_info: FieldInfo) -> int | float | None:
    """Extract the <= constraint value from field metadata.

    Pydantic v2 stores Field(le=...) constraints as annotated-types metadata.
    This helper extracts the constraint value for use in custom clamping logic.

    Args:
        field_info: Pydantic field metadata

    Returns:
        The <= constraint value if present, None otherwise
    """
    for meta in field_info.metadata:
        if isinstance(meta, Le):
            return cast(float | int | None, meta.le)
    return None
