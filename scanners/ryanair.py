"""Scanner Ryanair basato sull'endpoint pubblico Fare Finder."""

from datetime import date, timedelta

from config.settings import settings
from connectors.base import BaseConnector
from scanners.base import BaseScanner, Offerta


API_URL = "https://services-api.ryanair.com/farfnd/v4/oneWayFares"

BOOKING_URL = "https://www.ryanair.com/it/it/trip/flights/select"



def estrai_ora(timestamp):

    if not timestamp:
        return None

    return timestamp[11:16]



def calcola_durata(partenza, arrivo):

    if not partenza or not arrivo:
        return None

    try:
        from datetime import datetime

        p = datetime.fromisoformat(
            partenza.replace("Z", "+00:00")
        )

        a = datetime.fromisoformat(
            arrivo.replace("Z", "+00:00")
        )

        minuti = int(
            (a - p).total_seconds() / 60
        )

        return minuti if minuti > 0 else None

    except Exception:
        return None



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

        a = oggi + timedelta(
            days=settings.giorni_anticipo_max
        )


        offerte = []


        for origine in self.origini:


            dati = self.connector.get_json(
                API_URL,
                params={
                    "departureAirportIataCode": origine,
                    "outboundDepartureDateFrom": da.isoformat(),
                    "outboundDepartureDateTo": a.isoformat(),
                    "currency": settings.valuta,
                    "limit":200,
                    "offset":0,
                    "market":"it-it",
                }
            )


            if not dati:
                continue



            for voce in dati.get("fares", []):

                out = voce.get("outbound") or {}

                prezzo = (
                    out.get("price") or {}
                ).get("value")


                partenza = (
                    out.get("departureDate")
                    or ""
                )


                arrivo = (
                    out.get("arrivalDate")
                    or ""
                )


                data_partenza = partenza[:10]


                aeroporto_arrivo = (
                    out.get("arrivalAirport")
                    or {}
                )


                citta = (
                    aeroporto_arrivo.get("city") or {}
                ).get("name") or aeroporto_arrivo.get("name")



                if not (
                    prezzo
                    and data_partenza
                    and citta
                ):
                    continue



                offerte.append(
                    Offerta(

                        aeroporto_partenza=origine,

                        destinazione=citta,

                        compagnia=self.compagnia,

                        prezzo=float(prezzo),

                        valuta=settings.valuta,


                        data_partenza=data_partenza,


                        ora_partenza=estrai_ora(partenza),

                        ora_arrivo=estrai_ora(arrivo),


                        durata_andata=calcola_durata(
                            partenza,
                            arrivo
                        ),


                        link_prenotazione=(
                            f"{BOOKING_URL}"
                            f"?adults=1"
                            f"&dateOut={data_partenza}"
                            f"&originIata={origine}"
                            f"&destinationIata="
                            f"{aeroporto_arrivo.get('iataCode','')}"
                        ),


                        fonte_dato=settings.fonte_dato,
                    )
                )


        return offerte
