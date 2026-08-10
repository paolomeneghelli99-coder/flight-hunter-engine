"""Scanner Volotea tramite browser Playwright.

Strategia:
1. Scarica stations.json per ottenere dinamicamente le rotte.
2. Apre il booking engine Volotea con Chromium.
3. Intercetta le richieste POST verso /flights/search.
4. Utilizza la risposta reale generata dal sito.
5. Estrae voli, prezzi, orari e durata.
6. Converte tutto nel modello Offerta di Flight Hunter.

Il browser viene utilizzato perché la chiamata diretta con requests
all'endpoint /flights/search restituisce HTTP 403.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any

from playwright.sync_api import (
    Browser,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from config.settings import settings
from scanners.base import BaseScanner, Offerta


STATIONS_URL = (
    "https://json.volotea.com/dist/stations/stations.json"
)

BOOKING_URL = (
    "https://www.volotea.com/"
)

SEARCH_PATH = (
    "/api/spa/voe/v1/flights/search"
)

VOL0TEA_BOOKING_URL = (
    "https://www.volotea.com/"
)


def estrai_ora(value: str | None) -> str | None:
    """Estrae HH:MM da una data ISO Volotea."""

    if not value:
        return None

    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).strftime("%H:%M")
    except Exception:
        match = re.search(
            r"T(\d{2}:\d{2})",
            value,
        )

        if match:
            return match.group(1)

    return None


def calcola_durata(
    partenza: str | None,
    arrivo: str | None,
) -> int | None:
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


def estrai_prezzo(volo: dict[str, Any]) -> float | None:
    """Estrae il prezzo minimo ADT dal blocco fares."""

    prezzi: list[float] = []

    for fare in volo.get("fares", []) or []:

        for passenger in (
            fare.get("passengerFares", []) or []
        ):

            if passenger.get("passengerType") != "ADT":
                continue

            fare_amount = (
                passenger.get("fareAmount")
                or {}
            )

            valore = (
                fare_amount.get("eurAmount")
                or fare_amount.get("amount")
            )

            if valore is None:
                continue

            try:
                prezzo = float(valore)

            except (TypeError, ValueError):
                continue

            if prezzo > 0:
                prezzi.append(prezzo)

    if not prezzi:
        return None

    return min(prezzi)


def trova_voli(obj: Any) -> list[dict[str, Any]]:
    """Cerca ricorsivamente gli oggetti volo nella risposta JSON."""

    risultati: list[dict[str, Any]] = []

    def visita(value: Any) -> None:

        if isinstance(value, dict):

            if (
                isinstance(value.get("fares"), list)
                and isinstance(value.get("designator"), dict)
            ):
                risultati.append(value)

            for child in value.values():
                visita(child)

        elif isinstance(value, list):

            for child in value:
                visita(child)

    visita(obj)

    return risultati


def estrai_dati_volo(
    volo: dict[str, Any],
) -> dict[str, Any] | None:
    """Estrae i dati principali di un volo Volotea."""

    designator = (
        volo.get("designator")
        or {}
    )

    origine = (
        designator.get("origin")
        or ""
    ).upper()

    destinazione = (
        designator.get("destination")
        or ""
    ).upper()

    partenza = (
        designator.get("departure")
    )

    arrivo = (
        designator.get("arrival")
    )

    if not origine or not destinazione or not partenza:
        return None

    data_partenza = str(partenza)[:10]

    prezzo = estrai_prezzo(volo)

    if prezzo is None:
        return None

    numero_volo = None

    segments = (
        volo.get("segments")
        or []
    )

    if segments:

        identifier = (
            segments[0].get("identifier")
            or {}
        )

        numero_volo = (
            identifier.get("identifier")
        )

    durata = calcola_durata(
        partenza,
        arrivo,
    )

    return {
        "origine": origine,
        "destinazione": destinazione,
        "data_partenza": data_partenza,
        "partenza": partenza,
        "arrivo": arrivo,
        "prezzo": prezzo,
        "durata": durata,
        "numero_volo": numero_volo,
    }


class VoloteaScanner(BaseScanner):

    nome = "volotea"
    compagnia = "Volotea"

    def __init__(self):
        super().__init__(
            connector=None
        )

    # --------------------------------------------------
    # STATIONS
    # --------------------------------------------------

    def carica_stazioni(self, page: Page) -> dict[str, Any]:
        """Scarica stations.json tramite il browser."""

        print("")
        print("========================================")
        print("VOLOTEA - DOWNLOAD STATIONS")
        print("========================================")

        response = page.request.get(
            STATIONS_URL,
            timeout=60000,
        )

        print(
            "HTTP stations:",
            response.status,
        )

        response.raise_for_status()

        data = response.json()

        if not isinstance(data, dict):
            raise RuntimeError(
                "stations.json non contiene un dizionario."
            )

        print(
            "Stazioni Volotea:",
            len(data),
        )

        return data

    # --------------------------------------------------
    # ROTTE DINAMICHE
    # --------------------------------------------------

    def trova_rotte(
        self,
        stations: dict[str, Any],
    ) -> list[tuple[str, str]]:
        """Costruisce dinamicamente l'elenco origine/destinazione."""

        rotte: list[tuple[str, str]] = []

        for origine in self.origini:

            station = stations.get(
                origine
            )

            if not isinstance(station, dict):
                print(
                    f"[volotea] origine non trovata: {origine}"
                )
                continue

            markets = (
                station.get("Markets")
                or {}
            )

            for destinazione, market in markets.items():

                if not isinstance(market, dict):
                    continue

                if not market.get("Enabled"):
                    continue

                if market.get("FlightType") != "Direct":
                    continue

                destinazione = (
                    str(destinazione)
                    .upper()
                    .strip()
                )

                if not destinazione:
                    continue

                rotte.append(
                    (
                        origine.upper(),
                        destinazione,
                    )
                )

        rotte = sorted(
            set(rotte)
        )

        print("")
        print(
            f"[volotea] rotte dinamiche trovate: {len(rotte)}"
        )

        return rotte

    # --------------------------------------------------
    # DATE
    # --------------------------------------------------

    def date_rotta(
        self,
        stations: dict[str, Any],
        origine: str,
        destinazione: str,
    ) -> tuple[date, date] | None:
        """Determina l'intervallo operativo della rotta."""

        station = stations.get(
            origine
        )

        if not isinstance(station, dict):
            return None

        markets = (
            station.get("Markets")
            or {}
        )

        market = markets.get(
            destinazione
        )

        if not isinstance(market, dict):
            return None

        if not market.get("Enabled"):
            return None

        oggi = date.today()

        data_min = oggi + timedelta(days=1)

        min_flight = market.get(
            "MinFlightDate"
        )

        max_flight = market.get(
            "MaxFlightDate"
        )

        if min_flight:

            try:
                data_min = max(
                    data_min,
                    date.fromisoformat(
                        min_flight
                    ),
                )

            except ValueError:
                pass

        data_max = (
            oggi
            + timedelta(
                days=settings.giorni_anticipo_max
            )
        )

        if max_flight:

            try:
                data_max = min(
                    data_max,
                    date.fromisoformat(
                        max_flight
                    ),
                )

            except ValueError:
                pass

        if data_min > data_max:
            return None

        return (
            data_min,
            data_max,
        )

    # --------------------------------------------------
    # RICERCA BROWSER
    # --------------------------------------------------

    def costruisci_url_ricerca(
        self,
        origine: str,
        destinazione: str,
        data_partenza: date,
    ) -> str:
        """Costruisce una URL compatibile con il booking engine."""

        return (
            f"{BOOKING_URL}"
            f"?origin={origine}"
            f"&destination={destinazione}"
            f"&date={data_partenza.isoformat()}"
        )

    def esegui_ricerca(
        self,
        page: Page,
        origine: str,
        destinazione: str,
        data_partenza: date,
    ) -> list[dict[str, Any]]:
        """Apre Volotea e intercetta la risposta flights/search."""

        risposta_json: list[Any] = []

        def intercetta_response(response) -> None:

            try:

                if (
                    SEARCH_PATH not in response.url
                ):
                    return

                if response.request.method != "POST":
                    return

                print("")
                print(
                    "[volotea] intercettata:",
                    response.request.method,
                    response.url,
                )

                print(
                    "[volotea] HTTP:",
                    response.status,
                )

                if response.status != 200:
                    return

                try:
                    payload = response.json()

                except Exception:
                    return

                risposta_json.append(
                    payload
                )

                print(
                    "[volotea] risposta Search API ricevuta."
                )

            except Exception as exc:
                print(
                    "[volotea] errore intercettazione:",
                    exc,
                )

        page.on(
            "response",
            intercetta_response,
        )

        url = self.costruisci_url_ricerca(
            origine,
            destinazione,
            data_partenza,
        )

        print("")
        print("========================================")
        print("VOLOTEA - RICERCA")
        print("========================================")

        print(
            "Origine:",
            origine,
        )

        print(
            "Destinazione:",
            destinazione,
        )

        print(
            "Data:",
            data_partenza.isoformat(),
        )

        print(
            "URL:",
            url,
        )

        try:

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000,
            )

        except Exception as exc:

            print(
                "[volotea] errore apertura pagina:",
                exc,
            )

        # La ricerca viene effettuata dal frontend.
        # Attendiamo la POST reale verso /flights/search.

        try:

            page.wait_for_timeout(
                12000
            )

        except Exception:
            pass

        if not risposta_json:

            print(
                "[volotea] nessuna risposta /flights/search intercettata."
            )

            return []

        risultati: list[dict[str, Any]] = []

        for risposta in risposta_json:

            risultati.extend(
                trova_voli(
                    risposta
                )
            )

        print(
            "[volotea] voli estratti:",
            len(risultati),
        )

        return risultati

    # --------------------------------------------------
    # SCAN
    # --------------------------------------------------

    def scan(self) -> list[Offerta]:

        print("")
        print("========================================")
        print("FLIGHT HUNTER - SCANNER VOLOTEA")
        print("========================================")

        offerte: list[Offerta] = []

        with sync_playwright() as p:

            browser: Browser = p.chromium.launch(
                headless=True,
            )

            context = browser.new_context(
                locale="it-IT",
                timezone_id="Europe/Rome",
                viewport={
                    "width": 1440,
                    "height": 1000,
                },
                user_agent=(
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/140.0.0.0 Safari/537.36"
                ),
            )

            page = context.new_page()

            try:

                stations = self.carica_stazioni(
                    page
                )

                rotte = self.trova_rotte(
                    stations
                )

                print("")
                print(
                    "Prime rotte:"
                )

                for origine, destinazione in rotte[:20]:

                    print(
                        f" - {origine} -> {destinazione}"
                    )

                # --------------------------------------------------
                # TEST INIZIALE:
                # utilizziamo VRN -> CTA se disponibile.
                # Questo serve a verificare Playwright e
                # l'intercettazione della Search API.
                # --------------------------------------------------

                rotta_test = None

                for rotta in rotte:

                    if rotta == (
                        "VRN",
                        "CTA",
                    ):

                        rotta_test = rotta
                        break

                if rotta_test is None:

                    print(
                        "[volotea] VRN -> CTA non disponibile."
                    )

                else:

                    date_test = self.date_rotta(
                        stations,
                        "VRN",
                        "CTA",
                    )

                    if date_test:

                        data_test = date_test[0]

                        print("")
                        print(
                            "========================================"
                        )
                        print(
                            "TEST VOLOTEA PLAYWRIGHT"
                        )
                        print(
                            "========================================"
                        )

                        voli = self.esegui_ricerca(
                            page,
                            "VRN",
                            "CTA",
                            data_test,
                        )

                        for volo in voli:

                            dati = estrai_dati_volo(
                                volo
                            )

                            if not dati:
                                continue

                            print("")
                            print(
                                "VOLO TROVATO"
                            )

                            print(
                                " ",
                                dati,
                            )

                            prezzo = dati[
                                "prezzo"
                            ]

                            if prezzo > settings.prezzo_massimo:
                                continue

                            offerte.append(
                                Offerta(
                                    aeroporto_partenza=
                                        dati["origine"],

                                    aeroporto_arrivo=
                                        dati["destinazione"],

                                    destinazione=
                                        dati["destinazione"],

                                    compagnia=
                                        self.compagnia,

                                    preco=prezzo,
                                )
                            )

                    else:

                        print(
                            "[volotea] nessuna data valida per VRN -> CTA."
                        )

            finally:

                context.close()
                browser.close()

        print("")
        print("========================================")
        print("VOLOTEA COMPLETATO")
        print("========================================")

        print(
            "Offerte prodotte:",
            len(offerte),
        )

        return offerte
