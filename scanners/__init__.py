"""Registro degli scanner disponibili."""

from scanners.base import BaseScanner, Offer
from scanners.ryanair import RyanairScanner

# Aggiungere qui i futuri connettori:
# Wizz Air, easyJet, Volotea, Vueling, Transavia, Eurowings, Pegasus, Norwegian...
SCANNERS: dict[str, type[BaseScanner]] = {
    RyanairScanner.connector_slug: RyanairScanner,
}


def get_scanner(slug: str) -> type[BaseScanner]:
    try:
        return SCANNERS[slug]
    except KeyError as error:
        disponibili = ", ".join(sorted(SCANNERS)) or "nessuno"
        raise ValueError(f"Scanner sconosciuto '{slug}'. Disponibili: {disponibili}") from error


def available_scanners() -> list[str]:
    return sorted(SCANNERS)


__all__ = ["BaseScanner", "Offer", "SCANNERS", "get_scanner", "available_scanners"]
