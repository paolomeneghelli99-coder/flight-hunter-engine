"""Registro dei connettori HTTP disponibili."""

from connectors.base import BaseConnector

CONNECTORS = {
    "ryanair": lambda: BaseConnector(nome="ryanair"),
}

__all__ = ["BaseConnector", "CONNECTORS"]
