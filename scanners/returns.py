"""Motore ricerca voli di ritorno Ryanair."""

from datetime import datetime, date, timedelta

from config.settings import settings
from scanners.base import Offerta, ReturnOption


API_URL = "https://services-api.ryanair.com/farfnd/v4/oneWayFares"


RETURN_DAYS_MIN = 1
RETURN_DAYS_MAX = 14

MAX_RETURN_OPTIONS = 5



def estrai_ora(data_ora: str):

    if not data_ora:
        return None

    try:
        return datetime.fromisoformat(
            data_ora
        ).strftime("%H:%M")

    except Exception:
        return None



def durata_volo(
    partenza: str,
    arrivo: str
):

    if not partenza or not arrivo:
        return None

    try:
        p = datetime.fromisoformat(partenza)
        a = datetime.fromisoformat(arrivo)

        return int(
            (a - p).total_seconds()
            / 60
        )

    except Exception:
        return None



def giorni_soggiorno(
    andata: str,
    ritorno: str
):

    try:
        a = datetime.strptime(
            andata,
            "%Y-%m-%d"
        )

        r = datetime.strptime(
            ritorno,
            "%Y-%m-%d"
        )

        return (
            r - a
        ).days

    except Exception:
        return None



def cerca_ritorni(
    offerta: Offerta,
    connector
):

    """
    Cerca voli nella direzione opposta.

    Esempio:
    VRN -> BRI

    cerca:
    BRI -> VRN

    da +1 a +14 giorni
    """

    if not offerta.aeroporto_arrivo:
        return []


    risultati = []


    data_andata = datetime.strptime(
        offerta.data_partenza,
        "%Y-%m-%d"
    ).date()



    data_da = (
        data_andata
        +
        timedelta(
            days=RETURN_DAYS_MIN
        )
    )


    data_a = (
        data_andata
        +
        timedelta(
            days=RETURN_DAYS_MAX
        )
    )



    risposta = connector.get_json(
        API_URL,
        params={

            "departureAirportIataCode":
                offerta.aeroporto_arrivo,


            "outboundDepartureDateFrom":
                data_da.isoformat(),


            "outboundDepartureDateTo":
                data_a.isoformat(),


            "currency":
                settings.valuta,


            "limit":
                200,


            "offset":
                0,


            "market":
                "it-it",
        }
    )


    if not risposta:
        return []



    for voce in risposta.get(
        "fares",
        []
    ):


        volo = (
            voce.get(
                "outbound"
            )
            or {}
        )


        arrivo = (
            volo.get(
                "arrivalAirport"
            )
            or {}
        )


        aeroporto_finale = (
            arrivo.get(
                "iataCode"
            )
        )


        # teniamo solo il ritorno corretto
        if aeroporto_finale != (
            offerta.aeroporto_partenza
        ):
            continue



        prezzo = (
            volo.get(
                "price"
            )
            or {}
        ).get(
            "value"
        )


        data_ritorno_iso = (
            volo.get(
                "departureDate"
            )
            or ""
        )


        arrivo_iso = (
            volo.get(
                "arrivalDate"
            )
            or ""
        )


        if not (
            prezzo
            and data_ritorno_iso
        ):
            continue



        data_ritorno = (
            data_ritorno_iso[:10]
        )


        risultati.append(

            ReturnOption(

                data_ritorno=
                    data_ritorno,


                prezzo=
                    float(prezzo),


                ora_partenza=
                    estrai_ora(
                        data_ritorno_iso
                    ),


                ora_arrivo=
                    estrai_ora(
                        arrivo_iso
                    ),


                durata=
                    durata_volo(
                        data_ritorno_iso,
                        arrivo_iso
                    ),


                notti=
                    giorni_soggiorno(
                        offerta.data_partenza,
                        data_ritorno
                    )
            )
        )



    risultati.sort(
        key=lambda r:
        (
            r.prezzo,
            r.notti or 999
        )
    )


    return risultati[
        :MAX_RETURN_OPTIONS
    ]



def aggiungi_ritorni(
    offerte: list[Offerta],
    connector
):

    """
    Aggiunge le opzioni di ritorno
    alle offerte.
    """

    # limitiamo per non bombardare Ryanair
    analizzate = offerte[:500]


    for offerta in analizzate:

        try:

            offerta.ritorni = cerca_ritorni(
                offerta,
                connector
            )

        except Exception as e:

            print(
                "Errore ricerca ritorni:",
                e
            )

            offerta.ritorni = []


    return offerte
