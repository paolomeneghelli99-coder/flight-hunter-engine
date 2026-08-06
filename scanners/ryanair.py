"""Scanner Ryanair basato sull'endpoint pubblico Fare Finder."""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import requests

from scanners.base import BaseScanner, Offer

logger = logging.getLogger(__name__)

FARE_FINDER_URL = "https://services-api.ryanair.com/farfnd/v4/oneWayFares"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FlightHunterEngine/1.0)",
    "Accept": "application/json",
}


class RyanairScanner(BaseScanner):
    connector_slug = "ryanair"
    airline = "Ryanair"
    fonte_dato = "diretta"

    def __init__(
        self,
        airports: list[str],
        days_ahead: int = 90,
        max_price: float = 100.0,
        currency: str = "EUR",
        market: str = "it-it",
        timeout: int = 30,
        pause: float = 1.0,
    ) -> None:
        super().__init__(airports, days_ahead)
        self.max_price = max_price
        self.currency = currency
        self.market = market
        self.timeout = timeout
        self.pause = pause
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _fetch(self, origin: str) -> list[dict]:
        params = {
            "departureAirportIataCode": origin,
            "outboundDepartureDateFrom": date.today().isoformat(),
            "outboundDepartureDateTo": (date.today() + timedelta(days=self.days_ahead)).isoformat(),
            "currency": self.currency,
            "market": self.market,
            "priceValueTo": self.max_price,
            "limit": 200,
            "offset": 0,
        }
        response = self.session.get(FARE_FINDER_URL, params=params, timeout=self.timeout)
        if not response.ok:
            logger.warning(
                "[Ryanair] %s -> HTTP %s: %s", origin, response.status_code, response.text[:200]
            )
            return []
        return response.json().get("fares", []) or []

    @staticmethod
    def _booking_link(origin: str, destination: str, departure: str) -> str:
        return (
            "https://www.ryanair.com/it/it/trip/flights/select"
            f"?adults=1&teens=0&children=0&infants=0&dateOut={departure}"
            f"&originIata={origin}&destinationIata={destination}"
            "&isConnectedFlight=false&isReturn=false"
        )

    def _to_offer(self, fare: dict) -> Offer | None:
        outbound = fare.get("outbound") or {}
        price = outbound.get("price") or {}
        origin = (outbound.get("departureAirport") or {}).get("iataCode")
        arrival = outbound.get("arrivalAirport") or {}
        destination_iata = arrival.get("iataCode")
        destination_name = (arrival.get("city") or {}).get("name") or arrival.get("name")
        departure_at = outbound.get("departureDate")
        amount = price.get("value")

        if not (origin and destination_iata and destination_name and departure_at and amount):
            return None

        departure_day = str(departure_at)[:10]
        try:
            return Offer(
                aeroporto_partenza=origin,
                destinazione=destination_name,
                compagnia=self.airline,
                prezzo=float(amount),
                valuta=price.get("currencyCode") or self.currency,
                data_partenza=departure_day,
                data_ritorno=None,
                link_prenotazione=self._booking_link(origin, destination_iata, departure_day),
                fonte_dato=self.fonte_dato,
                opportunity_score=None,
            )
        except ValueError as error:
            logger.debug("[Ryanair] offerta scartata: %s", error)
            return None

    def scan(self) -> list[Offer]:
        offers: list[Offer] = []
        seen: set[tuple] = set()

        for origin in self.airports:
            for fare in self._fetch(origin):
                offer = self._to_offer(fare)
                if offer is None:
                    continue
                key = (
                    offer.aeroporto_partenza,
                    offer.destinazione,
                    offer.data_partenza,
                    offer.prezzo,
                )
                if key in seen:
                    continue
                seen.add(key)
                offers.append(offer)
            time.sleep(self.pause)

        offers.sort(key=lambda o: o.prezzo)
        return offers
