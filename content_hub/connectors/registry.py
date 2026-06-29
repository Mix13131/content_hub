from __future__ import annotations

from content_hub.connectors.base import Connector
from content_hub.connectors.website import WebsiteConnector


class ConnectorNotFound(LookupError):
    """Raised when a connector name is not registered."""


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        self._connectors[connector.name] = connector

    def get(self, name: str) -> Connector:
        connector = self._connectors.get(name)
        if connector is None:
            raise ConnectorNotFound(f"Connector is not registered: {name}")
        return connector


def default_connector_registry() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register(WebsiteConnector())
    return registry

