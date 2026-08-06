"""Interfaccia comune a tutti gli scanner compagnia."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import date

logger = logging.getLogger(__name__)

ALLOWED_FONTE_DATO = {"reale", "api", "import", "diretta", "scanner"}


@dataclass(slots=True)
class Offer:
    """Offerta nel formato atteso da POST /api/public/offers/import."""

    aeroporto_partenza: str
    destinazione: str
    compagnia: str
    prezzo: float
    data_partenza: str
    valuta: str = "EUR"
    data_ritorno: str | None = None
    link_prenotazione: str | None = None
    fonte_dato: str = "diretta"
    opportunity_score: int | None = None

    def __post_init__(self) -> None:
        self.aeroporto_partenza = self.aeroporto_partenza.strip().upper()[:8]
        self.destinazione = self.destinazione.strip()[:80]
        self.compagnia = self.compagnia.strip()[:60]
        self.valuta = self.valuta.strip().upper()[:3]
        self.prezzo = round(float(self.prezzo), 2)

        if not 3 <= len(self.aeroporto_partenza) <= 8:
            raise ValueError(f"IATA non valido: {self.aeroporto_partenza}")
        if not 0 < self.prezzo <= 10000:
            raise ValueError(f"Prezzo fuori range: {self.prezzo}")
        if self.fonte_dato not in ALLOWED_FONTE_DATO:
            raise ValueError(f"fonte_dato non valido: {self.fonte_dato}")
        date.fromisoformat(self.data_partenza)
        if self.data_ritorno:
            date.fromisoformat(self.data_ritorno)
        if self.link_prenotazione and len(self.link_prenotazione) > 1000:
            self.link_prenotazione = None

    def to_payload(self) -> dict:
        return asdict(self)


class BaseScanner(ABC):
    """Base per ogni compagnia. Sottoclasse -> implementa scan()."""

    #: slug del connettore lato Flight Hunter
    #: kiwi_tequila | amadeus | ryanair | wizzair | easyjet | volotea
    connector_slug: str = ""
    #: nome compagnia mostrato nelle offerte
    airline: str = ""
    #: fonte_dato usata dalle offerte prodotte
    fonte_dato: str = "diretta"

    def __init__(self, airports: list[str], days_ahead: int = 90) -> None:
        self.airports = [a.strip().upper() for a in airports]
        self.days_ahead = days_ahead

    @abstractmethod
    def scan(self) -> list[Offer]:
        """Restituisce le offerte trovate. Nessun dato simulato."""

    def safe_scan(self) -> list[Offer]:
        """Esegue scan() isolando gli errori: un connettore rotto non blocca gli altri."""
        try:
            offers = self.scan()
        except Exception as error:  # noqa: BLE001
            logger.error("[%s] scan fallito: %s", self.airline or self.connector_slug, error)
            return []
        logger.info("[%s] offerte trovate: %d", self.airline, len(offers))
        return offers
