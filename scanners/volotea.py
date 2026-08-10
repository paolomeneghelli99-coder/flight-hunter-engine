"""Scanner Volotea basato sulle API utilizzate dal booking engine."""

from datetime import date, datetime, timedelta

from config.settings import settings
from connectors.base import BaseConnector
from scanners.base import BaseScanner, Offerta


STATIONS_URL = (
    "https://json.volotea.com/dist/stations/stations.json"
)

SEARCH_URL = (
    "https://api.volotea.com/api/spa/voe/v1/flights/search"
)

BOOKING_URL = (
    "https://www.volotea.com/it/"
)


def estrai_ora(data_ora: str):
    """Estrae HH:MM da una data ISO."""
    if not data_ora:
        return None

    try:
        return datetime.fromisoformat(
            data_ora.replace("Z", "+00:00")
        ).strftime("%H:%M")
    except Exception:
        return None


def calcola_durata(data_ora: str):
    """Converte una durata HH:MM:SS in minuti."""
    if not data_ora:
        return None

    try:
        parti = data_ora.split(":")

        ore = int(parti[0])
        minuti = int(parti[1])

        return ore * 60 + minuti

    except Exception:
        return None


def primo_valore_fare(fares):
    """
    Restituisce il prezzo EUR più basso trovato
    nelle tariffe disponibili.
    """

    prezzi = []

    for fare in fares or []:

        for passenger in fare.get(
            "passengerFares",
            []
        ):

            if passenger.get(
                "passengerType"
            ) != "ADT":

                continue

            fare_amount = (
                passenger.get(
                    "fareAmount"
                )
                or {}
            )

            prezzo = (
                fare_amount.get(
                    "eurAmount"
                )
                or fare_amount.get(
                    "amount"
                )
            )

            if prezzo is None:
                continue

            try:
                prezzo = float(prezzo)

                if prezzo > 0:
                    prezzi.append(prezzo)

            except (TypeError, ValueError):
                continue

    if not prezzi:
        return None

    return min(prezzi)


class VoloteaScanner(BaseScanner):

    nome = "volotea"
    compagnia = "Volotea"

    def __init__(self):

        super().__init__(
            connector=BaseConnector(
                nome="volotea",
                timeout=settings.timeout,
            )
        )

    def carica_stations(self):
        """
        Scarica ogni volta la configurazione aggiornata
        delle stazioni Volotea.

        In questo modo le rotte non sono hardcoded:
        se Volotea aggiunge o rimuove una rotta,
        Flight Hunter la vede automaticamente.
        """

        dati = self.connector.get_json(
            STATIONS_URL
        )

        if not isinstance(dati, dict):

            print(
                "[volotea] stations.json "
                "non valido"
            )

            return {}

        print(
            f"[volotea] stazioni caricate: "
            f"{len(dati)}"
        )

        return dati

    def estrai_rotte(self, stations):
        """
        Costruisce dinamicamente le rotte dalle
        informazioni Markets di stations.json.
        """

        rotte = []

        for origine in self.origini:

            stazione = stations.get(
                origine
            )

            if not isinstance(
                stazione,
                dict
            ):

                print(
                    f"[volotea] origine "
                    f"{origine} non trovata"
                )

                continue

            markets = stazione.get(
                "Markets"
            ) or {}

            for destinazione, market in markets.items():

                if not isinstance(
                    market,
                    dict
                ):
                    continue

                if not market.get(
                    "Enabled",
                    False
                ):
                    continue

                if market.get(
                    "FlightType"
                ) not in (
                    None,
                    "Direct"
                ):
                    continue

                min_date = market.get(
                    "MinFlightDate"
                )

                max_date = market.get(
                    "MaxFlightDate"
                )

                rotte.append(
                    {
                        "origine": origine,
                        "destinazione": destinazione,
                        "min_date": min_date,
                        "max_date": max_date,
                    }
                )

        return rotte

    def costruisci_criteria(
        self,
        origine,
        destinazione,
        data_partenza,
    ):
        """
        Costruisce il criterio compatibile con
        il payload reale dell'API Volotea.
        """

        data_str = data_partenza.isoformat()

        return {
            "beginDate": data_str,
            "endDate": data_str,
            "selectedDate": data_str,
            "origin": origine,
            "destination": destinazione,
        }

    def cerca_voli(
        self,
        origine,
        destinazione,
        data_partenza,
    ):
        """
        Esegue una ricerca reale sul Search API Volotea.
        """

        criterio = self.costruisci_criteria(
            origine,
            destinazione,
            data_partenza,
        )

        payload = {
            "codes": {
                "currency": settings.valuta,
                "promotionCode": "",
                "bookingType": 2,
                "residentType": "NONE",
            },

            "criteria": [
                criterio
            ],

            "fareTypesToRequest": [
                "R",
                "S",
                "SP",
            ],

            "passengers": [
                {
                    "type": "ADT",
                    "count": 1,
                }
            ],
        }

        try:

            response = (
                self.connector.session.post(
                    SEARCH_URL,
                    json=payload,
                    timeout=settings.timeout,
                )
            )

            if (
                response.status_code == 429
                or response.status_code >= 500
            ):

                print(
                    f"[volotea] HTTP "
                    f"{response.status_code} "
                    f"{origine}-{destinazione} "
                    f"{data_partenza}"
                )

                return None

            response.raise_for_status()

            return response.json()

        except Exception as exc:

            print(
                f"[volotea] ricerca fallita "
                f"{origine}-{destinazione} "
                f"{data_partenza}: {exc}"
            )

            return None

    def estrai_offerte(
        self,
        dati,
        origine,
        destinazione,
        data_partenza,
    ):

        offerte = []

        if not isinstance(
            dati,
            dict
        ):
            return offerte

        """
        La risposta può contenere strutture annidate.
        Cerchiamo ricorsivamente gli oggetti che
        rappresentano un volo.
        """

        def visita(obj):

            if isinstance(obj, dict):

                if (
                    "fares" in obj
                    and "designator" in obj
                ):

                    aggiungi_volo(obj)

                for value in obj.values():
                    visita(value)

            elif isinstance(obj, list):

                for value in obj:
                    visita(value)

        def aggiungi_volo(volo):

            designator = (
                volo.get(
                    "designator"
                )
                or {}
            )

            origine_volo = (
                designator.get(
                    "origin"
                )
                or origine
            )

            destinazione_volo = (
                designator.get(
                    "destination"
                )
                or destinazione
            )

            partenza_iso = (
                designator.get(
                    "departure"
                )
            )

            arrivo_iso = (
                designator.get(
                    "arrival"
                )
            )

            if not partenza_iso:
                return

            prezzo = primo_valore_fare(
                volo.get(
                    "fares"
                )
            )

            if prezzo is None:
                return

            data_str = (
                partenza_iso[:10]
            )

            durata = calcola_durata(
                volo.get(
                    "flightDuration"
                )
            )

            numero_volo = None

            segments = (
                volo.get(
                    "segments"
                )
                or []
            )

            if segments:

                identifier = (
                    segments[0].get(
                        "identifier"
                    )
                    or {}
                )

                numero_volo = (
                    identifier.get(
                        "identifier"
                    )
                )

            if (
                prezzo <= settings.prezzo_massimo
            ):

                offerte.append(

                    Offerta(

                        aeroporto_partenza=(
                            origine_volo
                        ),

                        aeroporto_arrivo=(
                            destinazione_volo
                        ),

                        destinazione=(
                            destinazione_volo
                        ),

                        compagnia=self.compagnia,

                        prezzo=prezzo,

                        valuta=settings.valuta,

                        data_partenza=data_str,

                        ora_partenza=(
                            estrai_ora(
                                partenza_iso
                            )
                        ),

                        ora_arrivo=(
                            estrai_ora(
                                arrivo_iso
                            )
                        ),

                        durata_andata=durata,

                        link_prenotazione=(
                            BOOKING_URL
                        ),

                        fonte_dato=(
                            settings.fonte_dato
                        ),
                    )
                )

                print(
                    "[volotea] OFFERTA: "
                    f"{origine_volo} -> "
                    f"{destinazione_volo} | "
                    f"{data_str} | "
                    f"{prezzo:.2f} EUR"
                    + (
                        f" | volo {numero_volo}"
                        if numero_volo
                        else ""
                    )
                )

        visita(dati)

        return offerte

    def scan(self):

        oggi = date.today()

        data_massima = (
            oggi
            + timedelta(
                days=settings.giorni_anticipo_max
            )
        )

        print(
            "[volotea] caricamento "
            "rotte dinamiche..."
        )

        stations = (
            self.carica_stations()
        )

        if not stations:
            return []

        rotte = self.estrai_rotte(
            stations
        )

        print(
            f"[volotea] rotte trovate: "
            f"{len(rotte)}"
        )

        offerte = []

        for rotta in rotte:

            origine = rotta[
                "origine"
            ]

            destinazione = rotta[
                "destinazione"
            ]

            min_date = rotta.get(
                "min_date"
            )

            max_date = rotta.get(
                "max_date"
            )

            try:

                inizio = max(
                    oggi + timedelta(days=1),
                    date.fromisoformat(
                        min_date
                    )
                    if min_date
                    else oggi
                    + timedelta(days=1)
                )

                fine = min(
                    data_massima,
                    date.fromisoformat(
                        max_date
                    )
                    if max_date
                    else data_massima
                )

            except ValueError:

                continue

            if inizio > fine:
                continue

            giorno = inizio

            while giorno <= fine:

                dati = self.cerca_voli(
                    origine,
                    destinazione,
                    giorno,
                )

                if dati:

                    offerte.extend(
                        self.estrai_offerte(
                            dati,
                            origine,
                            destinazione,
                            giorno,
                        )
                    )

                giorno += timedelta(
                    days=1
                )

        print(
            f"[volotea] offerte trovate: "
            f"{len(offerte)}"
        )

        return offerte
