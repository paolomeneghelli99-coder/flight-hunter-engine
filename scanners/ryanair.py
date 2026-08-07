"""Scanner Ryanair basato sull'endpoint pubblico Fare Finder."""

from datetime import date, timedelta, datetime

from config.settings import settings
from connectors.base import BaseConnector
from scanners.base import BaseScanner, Offerta


API_URL = "https://services-api.ryanair.com/farfnd/v4/oneWayFares"

BOOKING_URL = (
    "https://www.ryanair.com/it/it/trip/flights/select"
)


def estrai_ora(data_ora: str):
    """
    Estrae HH:MM da una data ISO Ryanair.
    Esempio:
    2026-09-18T23:45:00 -> 23:45
    """
    if not data_ora:
        return None

    try:
        return datetime.fromisoformat(
            data_ora
        ).strftime("%H:%M")
    except Exception:
        return None



def calcola_durata(
    partenza: str,
    arrivo: str
):
    """
    Calcola durata volo in minuti.
    """

    if not partenza or not arrivo:
        return None

    try:
        p = datetime.fromisoformat(partenza)
        a = datetime.fromisoformat(arrivo)

        minuti = int(
            (a - p).total_seconds() / 60
        )

        return minuti

    except Exception:
        return None



class RyanairScanner(BaseScanner):

    nome = "ryanair"
    compagnia = "Ryanair"


    def __init__(self):

        super().__init__(
            connector=BaseConnector(
                nome="ryanair"
            )
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

                    "outboundDepartureDateFrom":
                        da.isoformat(),

                    "outboundDepartureDateTo":
                        a.isoformat(),

                    "currency":
                        settings.valuta,

                    "limit": 200,

                    "offset": 0,

                    "market": "it-it",
                }
            )


            if not dati:
                continue



            for voce in dati.get(
                "fares",
                []
            ):

                out = voce.get(
                    "outbound"
                ) or {}



                prezzo = (
                    out.get("price")
                    or {}
                ).get(
                    "value"
                )


                partenza_iso = (
                    out.get(
                        "departureDate"
                    )
                    or ""
                )


                arrivo_iso = (
                    out.get(
                        "arrivalDate"
                    )
                    or ""
                )


                data_partenza = (
                    partenza_iso[:10]
                    if partenza_iso
                    else ""
                )


                aeroporto_arrivo = (
                    out.get(
                        "arrivalAirport"
                    )
                    or {}
                ).get(
                    "iataCode"
                )


                arrivo = (
                    out.get(
                        "arrivalAirport"
                    )
                    or {}
                )


                destinazione = (

                    (arrivo.get("city") or {})
                    .get("name")

                    or arrivo.get("name")

                )


                if not (
                    prezzo
                    and data_partenza
                    and destinazione
                    and aeroporto_arrivo
                ):
                    continue



                durata = calcola_durata(
                    partenza_iso,
                    arrivo_iso
                )



                offerte.append(

                    Offerta(

                        aeroporto_partenza=origine,

                        aeroporto_arrivo=
                            aeroporto_arrivo,

                        destinazione=
                            destinazione,

                        compagnia=
                            self.compagnia,

                        prezzo=
                            float(prezzo),

                        valuta=(

                            out.get("price")
                            or {}

                        ).get(

                            "currencyCode",
                            settings.valuta
                        ),


                        data_partenza=
                            data_partenza,


                        ora_partenza=
                            estrai_ora(
                                partenza_iso
                            ),


                        ora_arrivo=
                            estrai_ora(
                                arrivo_iso
                            ),


                        durata_andata=
                            durata,


                        link_prenotazione=(

                            f"{BOOKING_URL}"
                            f"?adults=1"
                            f"&dateOut={data_partenza}"
                            f"&originIata={origine}"
                            f"&destinationIata={aeroporto_arrivo}"

                        ),


                        fonte_dato=
                            settings.fonte_dato,
                    )

                )


        return offerte
