"""Scanner Volotea tramite API interna del booking engine."""

from datetime import datetime, timedelta
from typing import Any, Optional

import requests

from config.settings import settings
from scanners.base import BaseScanner, Offerta


SEARCH_URL = "https://api.volotea.com/api/spa/voe/v1/flights/search"

FARE_TYPES = ["R", "S", "SP"]


class VoloteaScanner(BaseScanner):

    nome = "volotea"
    compagnia = "Volotea"

    def __init__(self, connector=None):
        super().__init__(connector)

        self.session = requests.Session()

        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "Origin": "https://www.volotea.com",
                "Referer": "https://www.volotea.com/",
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/140.0.0.0 Safari/537.36"
                ),
            }
        )

    # ---------------------------------------------------------
    # UTILITÀ
    # ---------------------------------------------------------

    @staticmethod
    def _date_iso(data: datetime) -> str:
        return data.strftime("%Y-%m-%d")

    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None

        try:
            return datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _nested(data: Any, *keys: str) -> Any:
        current = data

        for key in keys:
            if not isinstance(current, dict):
                return None

            current = current.get(key)

        return current

    # ---------------------------------------------------------
    # PREZZO
    # ---------------------------------------------------------

    @staticmethod
    def _price_from_fare(fare: dict) -> Optional[float]:
        """
        Determina il prezzo della tariffa per un passeggero ADT.

        Volotea separa la tariffa base dalle service charges.
        Se disponibile, utilizziamo il totale effettivamente
        associato alla tariffa; altrimenti ricostruiamo il totale.
        """

        passenger_fares = fare.get("passengerFares") or []

        adult_fare = None

        for passenger_fare in passenger_fares:
            if passenger_fare.get("passengerType") == "ADT":
                adult_fare = passenger_fare
                break

        if adult_fare is None and passenger_fares:
            adult_fare = passenger_fares[0]

        if not adult_fare:
            return None

        # Se Volotea fornisce direttamente un totale, preferirlo.
        for key in (
            "totalFare",
            "totalAmount",
            "totalPrice",
        ):
            value = adult_fare.get(key)

            if isinstance(value, dict):
                value = value.get("eurAmount")

            if value is not None:
                try:
                    return round(float(value), 2)
                except (TypeError, ValueError):
                    pass

        fare_amount = adult_fare.get("fareAmount") or {}

        try:
            totale = float(
                fare_amount.get(
                    "eurAmount",
                    fare_amount.get("amount")
                )
            )
        except (TypeError, ValueError):
            return None

        # Aggiungiamo le service charges della tariffa.
        service_charges = adult_fare.get("serviceCharges") or []

        for charge in service_charges:
            amount = charge.get("amount") or {}

            try:
                totale += float(
                    amount.get(
                        "eurAmount",
                        amount.get("amount", 0)
                    )
                )
            except (TypeError, ValueError):
                continue

        return round(totale, 2)

    # ---------------------------------------------------------
    # ESTRAZIONE DEI VOLI
    # ---------------------------------------------------------

    def _extract_flights(
        self,
        data: Any,
    ) -> list[dict]:

        risultati = []

        def visita(obj: Any) -> None:

            if isinstance(obj, dict):

                designator = obj.get("designator")
                leg_info = obj.get("legInfo")

                if (
                    isinstance(designator, dict)
                    and isinstance(leg_info, dict)
                ):
                    origin = designator.get("origin")
                    destination = designator.get("destination")
                    departure = designator.get("departure")
                    arrival = designator.get("arrival")

                    if (
                        origin
                        and destination
                        and departure
                        and arrival
                    ):
                        risultati.append(obj)

                for value in obj.values():
                    visita(value)

            elif isinstance(obj, list):

                for value in obj:
                    visita(value)

        visita(data)

        return risultati

    # ---------------------------------------------------------
    # RICERCA
    # ---------------------------------------------------------

    def _search(
        self,
        origin: str,
        destination: str,
        departure_date: str,
    ) -> list[dict]:

        start = datetime.strptime(
            departure_date,
            "%Y-%m-%d"
        )

        # Finestra piccola per non generare richieste inutili.
        begin_date = start.strftime("%Y-%m-%d")

        end_date = (
            start + timedelta(days=1)
        ).strftime("%Y-%m-%d")

        payload = {
            "abTastyExperiments": [],
            "codes": {
                "currency": settings.valuta.upper(),
                "promotionCode": "",
                "bookingType": 2,
                "residentType": "NONE",
            },
            "criteria": [
                {
                    "beginDate": begin_date,
                    "endDate": end_date,
                    "selectedDate": departure_date,
                    "origin": origin,
                    "destination": destination,
                }
            ],
            "fareTypesToRequest": FARE_TYPES,
            "passengers": [
                {
                    "type": "ADT",
                    "count": 1,
                }
            ],
        }

        risposta = self.session.post(
            SEARCH_URL,
            json=payload,
            timeout=settings.timeout,
        )

        risposta.raise_for_status()

        data = risposta.json()

        return self._extract_flights(data)

    # ---------------------------------------------------------
    # SCAN
    # ---------------------------------------------------------

    def scan(self) -> list[Offerta]:

        offerte = []

        oggi = datetime.now().date()

        data_finale = oggi + timedelta(
            days=settings.giorni_anticipo_max
        )

        print("")
        print("========================================")
        print("SCANNER VOLOTEA")
        print("========================================")

        print(
            f"Origini: {', '.join(self.origini)}"
        )

        print(
            f"Prezzo massimo: €{settings.prezzo_massimo:.2f}"
        )

        # Per il primo test utilizziamo le rotte che Volotea
        # restituisce autonomamente durante la ricerca.
        #
        # La ricerca iniziale viene effettuata utilizzando
        # l'aeroporto di partenza e una destinazione generica
        # non è supportata dall'API.
        #
        # Pertanto le destinazioni verranno aggiunte nel metodo
        # _get_destinations quando avremo completato il test
        # dell'endpoint.

        print("")
        print(
            "Scanner Volotea pronto per il test API."
        )

        return offerte

    def close(self) -> None:
        self.session.close()
