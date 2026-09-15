"""Provider registry: turn configuration into a live :class:`CloudConnection`.

Backends are registered by dotted path, not by import, so that selecting Azure
never loads boto3 and selecting AWS never loads the Azure SDK. The import
happens once, at the moment a connection is actually built.

Which provider gets built is a configuration question, answered by
:func:`inferq.config.get_cloud_config`; this module only reads the answer.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from importlib import import_module
from typing import Any

from inferq.remote.base import CloudConnection

logger = logging.getLogger(__name__)

#: Provider name -> ``"module:attribute"`` naming its ``CloudConnection``.
_REGISTRY: dict[str, str] = {
    "azure": "inferq.remote.providers.azure:AzureConnection",
    "aws": "inferq.remote.providers.aws:AwsConnection",
}

#: Extra to install for each provider, quoted back at an operator who is
#: missing one.
_EXTRAS: dict[str, str] = {
    "azure": "azure",
    "aws": "aws",
}


def register_provider(name: str, target: str, *, extra: str | None = None) -> None:
    """Register a backend under ``name``, given as ``"module:attribute"``.

    Exists so that a deployment can add a backend without editing this file.
    """
    _REGISTRY[name] = target
    if extra:
        _EXTRAS[name] = extra


def available_providers() -> tuple[str, ...]:
    """Provider names that can be selected, registration order preserved."""
    return tuple(_REGISTRY)


def connection_class(provider: str) -> type[CloudConnection]:
    """Import and return the connection class for ``provider``.

    Raises:
        ValueError: when no backend is registered under that name.
        ImportError: when the backend's SDK is not installed, naming the extra
            that provides it.
    """
    try:
        target = _REGISTRY[provider]
    except KeyError:
        raise ValueError(
            f"Unknown cloud provider {provider!r}. Available: {', '.join(available_providers())}."
        ) from None

    module_name, _, attribute = target.partition(":")
    try:
        module = import_module(module_name)
    except ImportError as exc:
        extra = _EXTRAS.get(provider, provider)
        raise ImportError(
            f"Cloud provider {provider!r} is not installed. "
            f"Install it with: uv sync --extra {extra}"
        ) from exc
    return getattr(module, attribute)


def resolve_provider(config: Mapping[str, Any] | None = None) -> str:
    """Return the configured provider name, validated against the registry."""
    if config is None:
        from inferq.config import get_cloud_config

        config = get_cloud_config()
    provider = str(config.get("provider") or "")
    if provider not in _REGISTRY:
        raise ValueError(
            f"Unknown cloud provider {provider!r}. "
            f"Set INFERQ_CLOUD_PROVIDER to one of: {', '.join(available_providers())}."
        )
    return provider


def get_connection(
    provider: str | None = None, *, config: Mapping[str, Any] | None = None
) -> CloudConnection:
    """Build a connection to the configured cloud.

    Args:
        provider: Override the configured provider.
        config: A cloud config view, as returned by
            :func:`inferq.config.get_cloud_config`. Read from the environment
            when omitted.

    Returns:
        A connected :class:`~inferq.remote.base.CloudConnection`. Clients are
        constructed eagerly, so credential problems surface here.
    """
    if config is None:
        from inferq.config import get_cloud_config

        config = get_cloud_config()
    name = provider or resolve_provider(config)
    logger.debug("Building %s cloud connection", name)
    return connection_class(name).from_env(config.get(name))


__all__ = [
    "available_providers",
    "connection_class",
    "get_connection",
    "register_provider",
    "resolve_provider",
]
