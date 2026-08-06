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
        super().__init__(
            connector=BaseConnector(nome="ryanair")
        )

    def scan(self) -> list:
        oggi = date.today()

        da = oggi + timedelta(days=1)
        a = oggi + timedelta(days=settings.giorni_anticipo_max)

        offerte = []

        for origine in self.origini:

            params = {
                "departureAirportIataCode": origine,
                "outboundDepartureDateFrom": da.isoformat(),
                "outboundDepartureDateTo": a.isoformat(),
                "currency": settings.valuta,
                "limit": 200,
                "offset": 0,
                "market": "it-it",
            }

            # Richiede anche il ritorno se impostato
            if settings.tipo_viaggio == "andata_ritorno":
                params["isReturn"] = "true"

            dati = self.connector.get_json(
                API_URL,
                params=params
            )

            if not dati:
                continue


            for voce in dati.get("fares", []):

                outbound = voce.get("outbound") or {}

                prezzo_andata = (
                    outbound.get("price") or {}
                ).get("value")

                partenza = (
                    outbound.get("departureDate") or ""
                )[:10]

                arrivo = (
                    outbound.get("arrivalAirport") or {}
                )

                destinazione = (
                    (arrivo.get("city") or {}).get("name")
                    or arrivo.get("name")
                )

                if not (
                    prezzo_andata
                    and partenza
                    and destinazione
                ):
                    continue


                data_ritorno = None
                prezzo_totale = prezzo_andata


                # Gestione A/R
                if settings.tipo_viaggio == "andata_ritorno":

                    ritorno = voce.get("return") or {}

                    data_ritorno = (
                        ritorno.get("departureDate") or ""
                    )[:10]

                    prezzo_ritorno = (
                        ritorno.get("price") or {}
                    ).get("value")


                    if not data_ritorno or not prezzo_ritorno:
                        continue


                    prezzo_totale = (
                        float(prezzo_andata)
                        + float(prezzo_ritorno)
                    )


                link = (
                    f"{BOOKING_URL}"
                    f"?adults=1"
                    f"&dateOut={partenza}"
                    f"&originIata={origine}"
                    f"&destinationIata={arrivo.get('iataCode', '')}"
                )

                if data_ritorno:
                    link += (
                        f"&dateIn={data_ritorno}"
                    )


                offerte.append(
                    Offerta(
                        aeroporto_partenza=origine,
                        destinazione=destinazione,
                        compagnia=self.compagnia,
                        prezzo=float(prezzo_totale),
                        valuta=(
                            outbound.get("price") or {}
                        ).get(
                            "currencyCode",
                            settings.valuta
                        ),
                        data_partenza=partenza,
                        data_ritorno=data_ritorno,
                        link_prenotazione=link,
                        fonte_dato=settings.fonte_dato,
                    )
                )


        return offerte
