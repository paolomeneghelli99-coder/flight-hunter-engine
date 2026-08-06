"""Registro degli scanner attivi."""

from scanners.base import BaseScanner, Offerta
from scanners.ryanair import RyanairScanner

SCANNERS = {
    "ryanair": RyanairScanner,
}

__all__ = ["BaseScanner", "Offerta", "SCANNERS"]
