"""Scanner Volotea basato sulle API pubbliche utilizzate dal sito."""

from datetime import date, timedelta, datetime

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


def calcola_durata(
    partenza: str,
    arrivo: str
):
    """Calcola la durata del volo in minuti."""
    if not partenza or not arrivo:
        return None

    try:
        p = datetime.fromisoformat(
            partenza.replace("Z", "+00:00")
        )

        a = datetime.fromisoformat(
            arrivo.replace("Z", "+00:00")
        )

        return int(
            (a - p).total_seconds() / 60
        )

    except Exception:
        return None


def primo_valore(*valori):
    """Restituisce il primo valore non vuoto."""
    for valore in valori:
        if valore is not None and valore != "":
            return valore

    return None


class VoloteaScanner(BaseScanner):

    nome = "volotea"
    compagnia = "Volotea"

    def __init__(self):

        super().__init__(
            connector=BaseConnector(
                nome="volotea"
            )
        )


    def _carica_stazioni(self):

        print(
            "Download configurazione dinamica "
            "stazioni Volotea..."
        )

        dati = self.connector.get_json(
            STATIONS_URL
        )

        if not isinstance(dati, dict):

            print(
                "ERRORE: stations.json non contiene "
                "un dizionario."
            )

            return {}

        print(
            f"Stazioni Volotea ricevute: {len(dati)}"
        )

        return dati


    def _trova_market(
        self,
        stazione,
        destinazione
    ):

        markets = (
            stazione.get("Markets")
            or {}
        )

        market = markets.get(
            destinazione
        )

        if not isinstance(market, dict):
            return None

        if not market.get("Enabled", False):
            return None

        if (
            market.get("FlightType")
            and market.get("FlightType")
            != "Direct"
        ):
            return None

        return market


    def _nome_destinazione(
        self,
        dati_stazione,
        codice
    ):

        market = (
            dati_stazione
            .get("Markets", {})
            .get(codice)
            or {}
        )

        # stations.json può contenere
        # informazioni localizzate sulla destinazione
        # in altre strutture. Se non disponibili,
        # utilizziamo il codice IATA come fallback.

        return (
            market.get("Name")
            or market.get("City")
            or codice
        )


    def _costruisci_criteria(
        self,
        origine,
        destinazione,
        data_partenza,
        market
    ):

        min_date = market.get(
            "MinFlightDate"
        )

        max_date = market.get(
            "MaxFlightDate"
        )

        if min_date:
            try:
                minimo = date.fromisoformat(
                    min_date
                )

                if data_partenza < minimo:
                    return None

            except ValueError:
                pass

        if max_date:
            try:
                massimo = date.fromisoformat(
                    max_date
                )

                if data_partenza > massimo:
                    return None

            except ValueError:
                pass

        # Finestra volutamente molto piccola:
        # il Search API restituisce i voli relativi
        # alla data selezionata.
        #
        # beginDate/endDate vengono mantenuti
        # ravvicinati per evitare richieste enormi.

        return {
            "beginDate": data_partenza.isoformat(),
            "endDate": data_partenza.isoformat(),
            "selectedDate": data_partenza.isoformat(),
            "origin": origine,
            "destination": destinazione,
        }


    def _cerca_voli(
        self,
        origine,
        destinazione,
        data_partenza,
        market
    ):

        criteria = self._costruisci_criteria(
            origine,
            destinazione,
            data_partenza,
            market
        )

        if not criteria:
            return {}

        payload = {
            "abTastyExperiments": [],

            "codes": {
                "currency": settings.valuta,
                "promotionCode": "",
                "bookingType": 2,
                "residentType": "NONE",
            },

            "criteria": [
                criteria
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

        return self.connector.post_json(
            SEARCH_URL,
            json=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://www.volotea.com",
                "Referer": "https://www.volotea.com/",
            }
        ) or {}


    def _estrai_offerte(
        self,
        dati,
        origine,
        destinazione,
        data_partenza
    ):

        offerte = []

        if not isinstance(dati, dict):
            return offerte

        # Il formato può contenere strutture annidate.
        # Cerchiamo ricorsivamente gli oggetti che
        # rappresentano una tariffa.

        def visita(obj):

            if isinstance(obj, dict):

                # Individuazione di un oggetto tariffa
                # tramite passengerFares.
                if isinstance(
                    obj.get("passengerFares"),
                    list
                ):

                    self._aggiungi_tariffa(
                        offerte,
                        obj,
                        origine,
                        destinazione,
                        data_partenza
                    )

                for valore in obj.values():
                    visita(valore)

            elif isinstance(obj, list):

                for valore in obj:
                    visita(valore)

        visita(dati)

        return offerte


    def _aggiungi_tariffa(
        self,
        offerte,
        tariffa,
        origine,
        destinazione,
        data_partenza
    ):

        passenger_fares = (
            tariffa.get("passengerFares")
            or []
        )

        for passenger_fare in passenger_fares:

            if (
                passenger_fare.get(
                    "passengerType"
                )
                != "ADT"
            ):
                continue

            fare_amount = (
                passenger_fare.get(
                    "fareAmount"
                )
                or {}
            )

            prezzo = primo_valore(
                fare_amount.get("eurAmount"),
                fare_amount.get("amount")
            )

            if prezzo is None:
                continue

            try:
                prezzo = float(prezzo)

            except (TypeError, ValueError):
                continue

            if prezzo <= 0:
                continue

            # Cerchiamo le informazioni del volo
            # risalendo dalla struttura della tariffa.

            designator = (
                tariffa.get("designator")
                or {}
            )

            leg_info = (
                tariffa.get("legInfo")
                or {}
            )

            # In alcuni risultati il designator/legInfo
            # si trova in strutture superiori.
            # Per questo conserviamo comunque
            # origine/destinazione/date della ricerca.

            aeroporto_arrivo = (
                designator.get("destination")
                or destinazione
            )

            aeroporto_partenza = (
                designator.get("origin")
                or origine
            )

            departure = (
                designator.get("departure")
                or leg_info.get("departureTime")
            )

            arrival = (
                designator.get("arrival")
                or leg_info.get("arrivalTime")
            )

            data_effettiva = (
                departure[:10]
                if departure
                else data_partenza.isoformat()
            )

            durata = calcola_durata(
                departure,
                arrival
            )

            destinazione_nome = (
                aeroporto_arrivo
            )

            link = (
                f"{BOOKING_URL}"
                f"?origin={aeroporto_partenza}"
                f"&destination={aeroporto_arrivo}"
                f"&date={data_effettiva}"
            )

            offerte.append(
                Offerta(
                    aeroporto_partenza=
                        aeroporto_partenza,

                    aeroporto_arrivo=
                        aeroporto_arrivo,

                    destinazione=
                        destinazione_nome,

                    compagnia=
                        self.compagnia,

                    prezzo=
                        prezzo,

                    valuta=
                        settings.valuta,

                    data_partenza=
                        data_effettiva,

                    ora_partenza=
                        estrai_ora(
                            departure
                        ),

                    ora_arrivo=
                        estrai_ora(
                            arrival
                        ),

                    durata_andata=
                        durata,

                    link_prenotazione=
                        link,

                    fonte_dato=
                        settings.fonte_dato,
                )
            )


    def scan(self) -> list:

        oggi = date.today()

        data_inizio = (
            oggi + timedelta(days=1)
        )

        data_fine = (
            oggi
            + timedelta(
                days=settings.giorni_anticipo_max
            )
        )

        offerte = []

        stations = (
            self._carica_stazioni()
        )

        if not stations:
            return offerte


        for origine in self.origini:

            print("")
            print(
                f"[volotea] origine: {origine}"
            )

            stazione = stations.get(
                origine
            )

            if not isinstance(
                stazione,
                dict
            ):

                print(
                    f"[volotea] {origine}: "
                    "stazione non trovata"
                )

                continue

            if not stazione.get(
                "Enabled",
                False
            ):

                print(
                    f"[volotea] {origine}: "
                    "stazione disabilitata"
                )

                continue


            markets = (
                stazione.get("Markets")
                or {}
            )

            destinazioni = []

            for codice, market in markets.items():

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

                if (
                    market.get("FlightType")
                    and market.get("FlightType")
                    != "Direct"
                ):
                    continue

                destinazioni.append(
                    (
                        codice,
                        market
                    )
                )


            print(
                f"[volotea] {origine}: "
                f"{len(destinazioni)} rotte attive"
            )


            for destinazione, market in destinazioni:

                min_date = market.get(
                    "MinFlightDate"
                )

                max_date = market.get(
                    "MaxFlightDate"
                )


                da = data_inizio
                a = data_fine


                if min_date:

                    try:
                        da = max(
                            da,
                            date.fromisoformat(
                                min_date
                            )
                        )

                    except ValueError:
                        pass


                if max_date:

                    try:
                        a = min(
                            a,
                            date.fromisoformat(
                                max_date
                            )
                        )

                    except ValueError:
                        pass


                if da > a:
                    continue


                # IMPORTANTE:
                # non interroghiamo inutilmente tutte le date
                # se il market non è operativo.
                #
                # Per ora analizziamo ogni data valida.
                # Il limite FH_GIORNI_MAX controlla la finestra.

                corrente = da

                while corrente <= a:

                    print(
                        f"[volotea] "
                        f"{origine}->{destinazione} "
                        f"{corrente.isoformat()}"
                    )

                    try:

                        dati = self._cerca_voli(
                            origine,
                            destinazione,
                            corrente,
                            market
                        )

                        nuove = (
                            self._estrai_offerte(
                                dati,
                                origine,
                                destinazione,
                                corrente
                            )
                        )

                        offerte.extend(
                            nuove
                        )

                    except Exception as exc:

                        print(
                            f"[volotea] ERRORE "
                            f"{origine}->{destinazione} "
                            f"{corrente}: {exc}"
                        )

                    corrente += timedelta(
                        days=1
                    )


        print("")
        print(
            f"[volotea] offerte trovate: "
            f"{len(offerte)}"
        )

        return offerte
