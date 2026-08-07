"""Scanner Ryanair basato sull'endpoint pubblico Fare Finder."""

from datetime import date, timedelta

from config.settings import settings
from connectors.base import BaseConnector
from scanners.base import BaseScanner, Offerta

API_URL = "https://services-api.ryanair.com/farfnd/v4/oneWayFares"
BOOKING_URL = "https://www.ryanair.com/it/it/trip/flights/select"


class RyanairScanner(BaseScanner):
    nome = "ryanair"
    compagnia = "Ryanair"

    def __init__(self):
        super().__init__(connector=BaseConnector(nome="ryanair"))

    def scan(self) -> list:
        oggi = date.today()
        da = oggi + timedelta(days=1)
        a = oggi + timedelta(days=settings.giorni_anticipo_max)

        offerte = []

        stampato_debug = False

        for origine in self.origini:
            dati = self.connector.get_json(API_URL, params={
                "departureAirportIataCode": origine,
                "outboundDepartureDateFrom": da.isoformat(),
                "outboundDepartureDateTo": a.isoformat(),
                "currency": settings.valuta,
                "limit": 200,
                "offset": 0,
                "market": "it-it",
            })

            if not dati:
                continue

            # DEBUG TEMPORANEO:
            # stampa una risposta completa Ryanair per capire
            # quali campi possiamo usare per i ritorni
            if not stampato_debug and dati.get("fares"):
                print("===== DEBUG RISPOSTA RYANAIR =====")
                print(dati["fares"][0])
                print("===== FINE DEBUG =====")
                stampato_debug = True

            for voce in dati.get("fares", []):
                out = voce.get("outbound") or {}

                prezzo = (out.get("price") or {}).get("value")
                partenza = (out.get("departureDate") or "")[:10]

                arrivo = out.get("arrivalAirport") or {}

                citta = (
                    (arrivo.get("city") or {}).get("name")
                    or arrivo.get("name")
                )

                if not (prezzo and partenza and citta):
                    continue

                offerte.append(
                    Offerta(
                        aeroporto_partenza=origine,
                        destinazione=citta,
                        compagnia=self.compagnia,
                        prezzo=float(prezzo),
                        valuta=(
                            out.get("price") or {}
                        ).get(
                            "currencyCode",
                            settings.valuta
                        ),
                        data_partenza=partenza,
                        data_ritorno=None,
                        link_prenotazione=(
                            f"{BOOKING_URL}?adults=1&dateOut={partenza}"
                            f"&originIata={origine}"
                            f"&destinationIata={arrivo.get('iataCode', '')}"
                        ),
                        fonte_dato=settings.fonte_dato,
                    )
                )

        return offerte
