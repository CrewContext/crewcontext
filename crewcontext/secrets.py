"""Secrets management for CrewContext.

Provides secure handling of sensitive configuration values.

Usage:
    from crewcontext.secrets import SecretsManager, SecretProvider
    
    # Use environment variables (default)
    secrets = SecretsManager()
    db_password = secrets.get("DB_PASSWORD")
    
    # Use file-based secrets
    secrets = SecretsManager(provider="file", path="/run/secrets")
    api_key = secrets.get("API_KEY")
    
    # Use hashicorp vault (requires hvac package)
    secrets = SecretsManager(provider="vault", url="http://vault:8200")
    db_password = secrets.get("database/password")
"""
from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class SecretNotFoundError(Exception):
    """Raised when a secret is not found."""
    pass


class SecretProvider(ABC):
    """Abstract base class for secret providers."""

    @abstractmethod
    def get(self, name: str) -> Optional[str]:
        """Get a secret by name."""
        pass

    @abstractmethod
    def list(self) -> List[str]:
        """List available secret names."""
        pass


class EnvSecretProvider(SecretProvider):
    """Get secrets from environment variables."""

    def __init__(self, prefix: str = ""):
        """Initialize with optional prefix for secret names.

        Args:
            prefix: Prefix to add to secret names (e.g., "CREWCONTEXT_").
        """
        self.prefix = prefix

    def get(self, name: str) -> Optional[str]:
        """Get secret from environment variable."""
        full_name = f"{self.prefix}{name}" if self.prefix else name
        return os.getenv(full_name)

    def list(self) -> List[str]:
        """List all environment variables (filtered by prefix)."""
        if self.prefix:
            return [
                k[len(self.prefix):]
                for k in os.environ.keys()
                if k.startswith(self.prefix)
            ]
        return list(os.environ.keys())


class FileSecretProvider(SecretProvider):
    """Get secrets from files in a directory.

    Each secret is stored in a separate file.
    Common in Kubernetes and Docker Swarm.
    """

    def __init__(self, path: str):
        """Initialize with path to secrets directory.

        Args:
            path: Path to directory containing secret files.
        """
        self.path = Path(path)
        if not self.path.exists():
            log.warning("Secrets directory does not exist: %s", path)

    def get(self, name: str) -> Optional[str]:
        """Get secret from file."""
        secret_file = self.path / name
        if not secret_file.exists():
            return None
        try:
            return secret_file.read_text().strip()
        except Exception as e:
            log.error("Failed to read secret %s: %s", name, e)
            return None

    def list(self) -> List[str]:
        """List all secret files in directory."""
        if not self.path.exists():
            return []
        return [f.name for f in self.path.iterdir() if f.is_file()]


class JsonSecretProvider(SecretProvider):
    """Get secrets from a JSON file."""

    def __init__(self, path: str, key_path: Optional[str] = None):
        """Initialize with path to JSON file.

        Args:
            path: Path to JSON file containing secrets.
            key_path: Optional nested key path (e.g., "secrets.database").
        """
        self.path = Path(path)
        self.key_path = key_path
        self._cache: Optional[Dict[str, Any]] = None
        self._load_time: Optional[datetime] = None

    def _load(self) -> Dict[str, Any]:
        """Load and cache JSON file."""
        if self._cache is not None:
            return self._cache

        try:
            content = self.path.read_text()
            data = json.loads(content)

            # Navigate to nested key path if specified
            if self.key_path:
                for key in self.key_path.split("."):
                    data = data[key]

            self._cache = data
            self._load_time = datetime.now(timezone.utc)
            return data
        except Exception as e:
            log.error("Failed to load secrets from %s: %s", self.path, e)
            return {}

    def get(self, name: str) -> Optional[str]:
        """Get secret from JSON file."""
        data = self._load()
        value = data.get(name)
        return str(value) if value is not None else None

    def list(self) -> List[str]:
        """List all secret keys in JSON file."""
        data = self._load()
        return list(data.keys())


class SecretsManager:
    """Main interface for secrets management.

    Supports multiple providers with fallback chain.

    Usage:
        # Simple usage with environment variables
        secrets = SecretsManager()
        password = secrets.get("DB_PASSWORD")

        # With multiple providers (fallback chain)
        secrets = SecretsManager(
            providers=[
                FileSecretProvider("/run/secrets"),
                EnvSecretProvider(prefix="CREWCONTEXT_"),
            ]
        )
        api_key = secrets.get("API_KEY")  # Tries file first, then env

        # With required secrets (raises error if missing)
        secrets.require("DB_PASSWORD", "API_KEY")
    """

    def __init__(
        self,
        provider: str = "env",
        **provider_kwargs: Any,
    ):
        """Initialize secrets manager.

        Args:
            provider: Provider type ("env", "file", "json", "vault").
            **provider_kwargs: Arguments passed to provider constructor.
        """
        self._providers: List[SecretProvider] = []
        self._access_log: List[Dict[str, Any]] = []
        self._required: set[str] = set()

        # Create primary provider
        self._add_provider(provider, **provider_kwargs)

    def _add_provider(self, provider: str, **kwargs: Any) -> None:
        """Add a secret provider."""
        if provider == "env":
            self._providers.append(EnvSecretProvider(kwargs.get("prefix", "")))
        elif provider == "file":
            self._providers.append(FileSecretProvider(kwargs.get("path", "/run/secrets")))
        elif provider == "json":
            self._providers.append(JsonSecretProvider(
                kwargs.get("path", "secrets.json"),
                kwargs.get("key_path"),
            ))
        elif provider == "vault":
            self._try_vault_provider(kwargs)
        else:
            log.warning("Unknown secret provider: %s", provider)

    def _try_vault_provider(self, kwargs: Dict[str, Any]) -> None:
        """Try to create Vault provider (requires hvac package)."""
        try:
            import hvac
            from hvac import Client

            client = Client(
                url=kwargs.get("url", "http://localhost:8200"),
                token=kwargs.get("token"),
            )

            class VaultProvider(SecretProvider):
                def __init__(self, client: Client, mount_point: str):
                    self.client = client
                    self.mount_point = mount_point

                def get(self, name: str) -> Optional[str]:
                    try:
                        secret = self.client.secrets.kv.v2.read_secret_version(
                            path=name,
                            mount_point=self.mount_point,
                        )
                        return secret["data"]["data"].get("value")
                    except Exception:
                        return None

                def list(self) -> List[str]:
                    return []

            self._providers.append(VaultProvider(client, kwargs.get("mount_point", "secret")))
            log.info("Connected to HashiCorp Vault")
        except ImportError:
            log.warning("hvac package not installed. Vault provider unavailable.")
        except Exception as e:
            log.warning("Failed to connect to Vault: %s", e)

    def add_provider(self, provider: SecretProvider) -> None:
        """Add a custom secret provider."""
        self._providers.append(provider)

    def get(self, name: str, default: Optional[str] = None) -> Optional[str]:
        """Get a secret value.

        Args:
            name: Secret name.
            default: Default value if secret not found.

        Returns:
            Secret value or default.
        """
        # Try each provider in order
        for provider in self._providers:
            value = provider.get(name)
            if value is not None:
                self._log_access(name, True)
                return value

        self._log_access(name, False)

        # Check if required
        if name in self._required:
            raise SecretNotFoundError(f"Required secret not found: {name}")

        return default

    def get_int(self, name: str, default: int = 0) -> int:
        """Get a secret as integer."""
        value = self.get(name)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            log.warning("Secret %s is not a valid integer", name)
            return default

    def get_bool(self, name: str, default: bool = False) -> bool:
        """Get a secret as boolean."""
        value = self.get(name)
        if value is None:
            return default
        return value.lower() in ("true", "1", "yes", "on")

    def require(self, *names: str) -> None:
        """Mark secrets as required.

        Raises SecretNotFoundError if any required secret is missing.
        """
        for name in names:
            if self.get(name) is None:
                raise SecretNotFoundError(f"Required secret not found: {name}")
            self._required.add(name)

    def list(self) -> List[str]:
        """List all available secret names."""
        names: set[str] = set()
        for provider in self._providers:
            names.update(provider.list())
        return sorted(names)

    def _log_access(self, name: str, found: bool) -> None:
        """Log secret access for audit."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "secret_name": name,
            "found": found,
        }
        self._access_log.append(entry)

        # Keep only last 100 entries
        if len(self._access_log) > 100:
            self._access_log = self._access_log[-100:]

    def get_access_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent secret access log entries."""
        return self._access_log[-limit:]


# -- Global instance for convenience ----------------------------------------

_default_secrets: Optional[SecretsManager] = None


def get_secrets() -> SecretsManager:
    """Get the default secrets manager instance."""
    global _default_secrets
    if _default_secrets is None:
        _default_secrets = SecretsManager()
    return _default_secrets


def secret(name: str, default: Optional[str] = None) -> Optional[str]:
    """Get a secret using the default secrets manager."""
    return get_secrets().get(name, default)


def require_secret(*names: str) -> None:
    """Require secrets using the default secrets manager."""
    get_secrets().require(*names)
