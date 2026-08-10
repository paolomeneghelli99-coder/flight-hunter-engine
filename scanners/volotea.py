"""Scanner Volotea tramite browser Playwright.

Strategia:

1. Apre il booking engine Volotea.
2. Chiude il banner cookie.
3. Apre esplicitamente il nuovo selettore aeroporti
   cliccando il vecchio campo visibile del frontend.
4. Compila il nuovo input #origin.
5. Seleziona l'aeroporto dall'elenco.
6. Compila il nuovo input #destination.
7. Seleziona la destinazione dall'elenco.
8. Imposta la data.
9. Intercetta la richiesta/risposta reale della Search API.
10. Estrae voli, prezzi, orari e durata.
11. Converte i risultati nel modello Offerta.

NOTA:
L'endpoint storico stations.json non viene utilizzato.
"""

from __future__ import annotations

import re
import traceback
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


BOOKING_URL = "https://book.volotea.com/search"

SEARCH_PATHS = (
    "/api/spa/voe/v1/flights/search",
    "/flights/search",
)


# ============================================================
# UTILITÀ
# ============================================================

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


def estrai_prezzo(
    volo: dict[str, Any],
) -> float | None:
    """Estrae il prezzo minimo ADT."""

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


def trova_voli(
    obj: Any,
) -> list[dict[str, Any]]:
    """Cerca ricorsivamente gli oggetti volo."""

    risultati: list[dict[str, Any]] = []

    def visita(value: Any) -> None:

        if isinstance(value, dict):

            if (
                isinstance(
                    value.get("fares"),
                    list,
                )
                and isinstance(
                    value.get("designator"),
                    dict,
                )
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

    partenza = designator.get(
        "departure"
    )

    arrivo = designator.get(
        "arrival"
    )

    if (
        not origine
        or not destinazione
        or not partenza
    ):
        return None

    data_partenza = str(
        partenza
    )[:10]

    prezzo = estrai_prezzo(
        volo
    )

    if prezzo is None:
        return None

    numero_volo = None

    segments = (
        volo.get("segments")
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


# ============================================================
# SCANNER
# ============================================================

class VoloteaScanner(BaseScanner):

    nome = "volotea"
    compagnia = "Volotea"

    def __init__(self):
        super().__init__(
            connector=None
        )

    # ========================================================
    # DATA TEST
    # ========================================================

    def data_test(self) -> date:
        """Prima data utile per il test."""

        oggi = date.today()

        return (
            oggi
            + timedelta(days=1)
        )

    # ========================================================
    # COOKIE
    # ========================================================

    def chiudi_cookie(
        self,
        page: Page,
    ) -> None:
        """Chiude eventuali banner cookie."""

        selettori = [
            "button:has-text('Aceptar sólo las esenciales')",
            "button:has-text('Accept only essential')",
            "button:has-text('Accept only necessary')",
            "button:has-text('Only essential')",
            "button:has-text('Solo essenziali')",
            "button:has-text('Accetta solo i necessari')",
        ]

        for selettore in selettori:

            try:

                locator = page.locator(
                    selettore
                )

                count = locator.count()

                if count == 0:
                    continue

                for i in range(count):

                    elemento = locator.nth(i)

                    if not elemento.is_visible():
                        continue

                    print(
                        "[volotea] cookie banner trovato:",
                        selettore,
                    )

                    elemento.click(
                        force=True,
                        timeout=5000,
                    )

                    page.wait_for_timeout(
                        1000
                    )

                    print(
                        "[volotea] cookie chiusi."
                    )

                    return

            except Exception:
                continue

    # ========================================================
    # DEBUG FORM
    # ========================================================

    def stampa_input(
        self,
        page: Page,
        titolo: str,
    ) -> None:
        """Stampa gli input visibili del form."""

        print("")
        print(titolo)
        print("-" * 60)

        try:

            inputs = page.locator(
                "input:visible"
            )

            totale = inputs.count()

            print(
                "Input visibili:",
                totale,
            )

            for i in range(totale):

                elemento = inputs.nth(i)

                try:

                    print(
                        {
                            "tag": "INPUT",
                            "type": elemento.get_attribute(
                                "type"
                            ),
                            "id": elemento.get_attribute(
                                "id"
                            ),
                            "name": elemento.get_attribute(
                                "name"
                            ),
                            "placeholder": elemento.get_attribute(
                                "placeholder"
                            ),
                            "value": elemento.input_value(),
                            "readonly": elemento.get_attribute(
                                "readonly"
                            )
                            is not None,
                            "disabled": elemento.is_disabled(),
                            "className": elemento.get_attribute(
                                "class"
                            ),
                        }
                    )

                except Exception:
                    pass

        except Exception as exc:

            print(
                "[volotea] errore debug input:",
                exc,
            )

    # ========================================================
    # APERTURA NUOVO SELETTORE AEROPORTI
    # ========================================================

    def apri_selettore_aeroporti(
        self,
        page: Page,
    ) -> bool:
        """Apre il nuovo componente aeroporti Volotea.

        Il nuovo frontend mantiene nel DOM i campi
        #origin e #destination, ma questi sono nascosti
        finché non viene aperto il componente tramite
        il vecchio campo #input-text_sf-origin.

        Questo è il passaggio fondamentale emerso dal test.
        """

        print("")
        print(
            "APERTURA SELETTORE AEROPORTI"
        )
        print("=" * 60)

        # ----------------------------------------------------
        # PRIMO TENTATIVO:
        # vecchio campo origine del frontend
        # ----------------------------------------------------

        selettori_trigger = [
            "#input-text_sf-origin:visible",
            "input[id='input-text_sf-origin']:visible",
        ]

        for selettore in selettori_trigger:

            try:

                elemento = page.locator(
                    selettore
                ).first

                if elemento.count() == 0:
                    continue

                if not elemento.is_visible():
                    continue

                print(
                    "Vecchio campo origine trovato."
                )

                print(
                    "Apertura componente aeroporti tramite click forzato."
                )

                elemento.click(
                    force=True,
                    timeout=10000,
                )

                page.wait_for_timeout(
                    1000
                )

                # ------------------------------------------------
                # Verifica reale del nuovo componente
                # ------------------------------------------------

                origin = page.locator(
                    "#origin:visible"
                ).first

                destination = page.locator(
                    "#destination:visible"
                ).first

                origin.wait_for(
                    state="visible",
                    timeout=10000,
                )

                destination.wait_for(
                    state="visible",
                    timeout=10000,
                )

                print(
                    "Nuovo componente aeroporto:"
                    " #origin/#destination PRESENTE"
                )

                return True

            except Exception as exc:

                print(
                    "[volotea] trigger selettore fallito:",
                    repr(exc),
                )

        # ----------------------------------------------------
        # FALLBACK:
        # cerca qualsiasi input Select airport visibile
        # ----------------------------------------------------

        fallback_selectors = [
            "input[placeholder='Select airport']:visible",
            "input[placeholder*='Select airport' i]:visible",
        ]

        for selettore in fallback_selectors:

            try:

                elemento = page.locator(
                    selettore
                ).first

                if elemento.count() == 0:
                    continue

                if not elemento.is_visible():
                    continue

                elemento.click(
                    force=True,
                    timeout=10000,
                )

                page.wait_for_timeout(
                    1000
                )

                origin = page.locator(
                    "#origin:visible"
                ).first

                destination = page.locator(
                    "#destination:visible"
                ).first

                if (
                    origin.count() > 0
                    and destination.count() > 0
                    and origin.is_visible()
                    and destination.is_visible()
                ):

                    print(
                        "Nuovo componente aeroporto aperto tramite fallback."
                    )

                    return True

            except Exception:
                continue

        print(
            "[volotea] impossibile aprire il selettore aeroporti."
        )

        try:
            page.screenshot(
                path="/tmp/volotea-airport-selector-failed.png",
                full_page=True,
            )
        except Exception:
            pass

        return False

    # ========================================================
    # SELEZIONE AEROPORTO
    # ========================================================

    def seleziona_aeroporto(
        self,
        page: Page,
        campo: str,
        codice: str,
    ) -> bool:
        """Seleziona un aeroporto dal nuovo componente."""

        codice = codice.upper()

        print("")
        print(
            f"[volotea] selezione {campo}: {codice}"
        )

        # ----------------------------------------------------
        # Assicuriamoci che il componente sia aperto.
        # ----------------------------------------------------

        if not (
            page.locator(
                f"#{campo}:visible"
            ).count()
        ):

            print(
                f"[volotea] #{campo} non visibile."
            )

            if not self.apri_selettore_aeroporti(
                page
            ):

                return False

        # ----------------------------------------------------
        # Recupera SOLO l'input visibile.
        # ----------------------------------------------------

        input_locator = page.locator(
            f"#{campo}:visible"
        ).first

        try:

            input_locator.wait_for(
                state="visible",
                timeout=10000,
            )

        except Exception as exc:

            print(
                f"[volotea] #{campo} non è diventato visibile:",
                repr(exc),
            )

            return False

        # ----------------------------------------------------
        # Compilazione.
        # ----------------------------------------------------

        try:

            input_locator.click(
                force=True,
                timeout=5000,
            )

            input_locator.fill(
                "",
                timeout=5000,
            )

            input_locator.fill(
                codice,
                timeout=10000,
            )

            page.wait_for_timeout(
                1200
            )

        except Exception as exc:

            print(
                f"[volotea] errore compilazione {campo}:",
                exc,
            )

            return False

        # ----------------------------------------------------
        # DEBUG: mostra le opzioni visibili.
        # ----------------------------------------------------

        try:

            print(
                f"[volotea] ricerca opzione {codice}..."
            )

            elementi = page.locator(
                "button:visible, "
                "[role='button']:visible, "
                "li:visible, "
                "[role='option']:visible"
            )

            for i in range(
                min(
                    elementi.count(),
                    150,
                )
            ):

                elemento = elementi.nth(i)

                try:

                    testo = (
                        elemento.inner_text()
                        .strip()
                    )

                except Exception:

                    continue

                if not testo:
                    continue

                if codice not in testo.upper():
                    continue

                # Evita di cliccare accidentalmente
                # il campo stesso.
                if testo.upper() == codice:
                    candidato = elemento
                else:
                    candidato = elemento

                print(
                    "[volotea] opzione trovata:",
                    repr(testo),
                )

                try:

                    candidato.click(
                        force=True,
                        timeout=5000,
                    )

                    page.wait_for_timeout(
                        800
                    )

                    print(
                        f"[volotea] {campo} selezionato: {codice}"
                    )

                    return True

                except Exception:
                    continue

        except Exception as exc:

            print(
                "[volotea] errore ricerca opzione:",
                exc,
            )

        # ----------------------------------------------------
        # FALLBACK IATA
        # ----------------------------------------------------

        try:

            iata = page.locator(
                "p.c-iata-tag__text:visible"
            ).filter(
                has_text=codice
            ).first

            if (
                iata.count() > 0
                and iata.is_visible()
            ):

                print(
                    "[volotea] selezione tramite IATA:"
                    f" {codice}"
                )

                iata.click(
                    force=True,
                    timeout=5000,
                )

                page.wait_for_timeout(
                    800
                )

                return True

        except Exception:
            pass

        # ----------------------------------------------------
        # FALLBACK TESTO
        # ----------------------------------------------------

        try:

            elementi = page.get_by_text(
                re.compile(
                    rf"\b{re.escape(codice)}\b",
                    re.I,
                )
            )

            for i in range(
                elementi.count()
            ):

                elemento = elementi.nth(i)

                if not elemento.is_visible():
                    continue

                testo = (
                    elemento.inner_text()
                    .strip()
                )

                if codice not in testo.upper():
                    continue

                print(
                    "[volotea] fallback testo:",
                    repr(testo),
                )

                elemento.click(
                    force=True,
                    timeout=5000,
                )

                page.wait_for_timeout(
                    800
                )

                return True

        except Exception:
            pass

        print(
            f"[volotea] aeroporto {codice} non selezionato."
        )

        try:
            page.screenshot(
                path=(
                    f"/tmp/"
                    f"volotea-{campo}-selection-failed.png"
                ),
                full_page=True,
            )
        except Exception:
            pass

        return False

    # ========================================================
    # DATA
    # ========================================================

    def seleziona_data(
        self,
        page: Page,
        data_partenza: date,
    ) -> bool:
        """Seleziona la data di partenza."""

        print("")
        print(
            "SELEZIONE DATA"
        )
        print("=" * 60)

        print(
            "Data richiesta:",
            data_partenza.isoformat(),
        )

        # ----------------------------------------------------
        # Recupera campo departure visibile.
        # ----------------------------------------------------

        try:

            departure = page.locator(
                "#departure:visible"
            ).first

            if departure.count() == 0:

                departure = page.locator(
                    "input[name='departure']:visible"
                ).first

            if departure.count() == 0:

                print(
                    "[volotea] campo departure non trovato."
                )

                return False

            departure.click(
                force=True,
                timeout=5000,
            )

            page.wait_for_timeout(
                800
            )

        except Exception as exc:

            print(
                "[volotea] errore apertura calendario:",
                exc,
            )

            return False

        giorno = str(
            data_partenza.day
        )

        # ----------------------------------------------------
        # Prima prova: aria-label.
        # ----------------------------------------------------

        selettori = [
            f"button[aria-label*='{giorno}']:visible",
            f"[role='button'][aria-label*='{giorno}']:visible",
            f"button:has-text('{giorno}'):visible",
        ]

        for selettore in selettori:

            try:

                elementi = page.locator(
                    selettore
                )

                for i in range(
                    elementi.count()
                ):

                    elemento = elementi.nth(i)

                    if not elemento.is_visible():
                        continue

                    try:

                        testo = (
                            elemento.inner_text()
                            .strip()
                        )

                    except Exception:

                        testo = ""

                    print(
                        "[volotea] giorno candidato:",
                        repr(testo),
                    )

                    elemento.click(
                        force=True,
                        timeout=5000,
                    )

                    page.wait_for_timeout(
                        500
                    )

                    print(
                        "[volotea] giorno selezionato:",
                        giorno,
                    )

                    return True

            except Exception:
                continue

        # ----------------------------------------------------
        # Fallback: elemento con testo esatto.
        # ----------------------------------------------------

        try:

            elementi = page.locator(
                "button:visible, "
                "[role='button']:visible, "
                "[class*='day']:visible"
            )

            for i in range(
                elementi.count()
            ):

                elemento = elementi.nth(i)

                if not elemento.is_visible():
                    continue

                try:

                    testo = (
                        elemento.inner_text()
                        .strip()
                    )

                except Exception:

                    continue

                if testo != giorno:
                    continue

                try:

                    elemento.click(
                        force=True,
                        timeout=5000,
                    )

                    page.wait_for_timeout(
                        500
                    )

                    print(
                        "[volotea] giorno selezionato:",
                        giorno,
                    )

                    return True

                except Exception:
                    continue

        except Exception:
            pass

        print(
            "[volotea] giorno non trovato:",
            giorno,
        )

        try:
            page.screenshot(
                path="/tmp/volotea-date-selection-failed.png",
                full_page=True,
            )
        except Exception:
            pass

        return False

    # ========================================================
    # PULSANTE RICERCA
    # ========================================================

    def trova_pulsante_ricerca(
        self,
        page: Page,
    ):
        """Trova il pulsante Search flights in modo resiliente."""

        pattern = re.compile(
            r"search\s*flights|"
            r"buscar\s*vuelos|"
            r"rechercher|"
            r"cerca\s*voli|"
            r"cerca\s*volo",
            re.I,
        )

        # ----------------------------------------------------
        # ROLE BUTTON
        # ----------------------------------------------------

        try:

            buttons = page.get_by_role(
                "button"
            )

            for i in range(
                buttons.count()
            ):

                button = buttons.nth(i)

                if not button.is_visible():
                    continue

                try:

                    testo = (
                        button.inner_text()
                        .strip()
                    )

                except Exception:

                    continue

                if pattern.search(testo):

                    print(
                        "[volotea] pulsante trovato:",
                        repr(testo),
                    )

                    return button

        except Exception:
            pass

        # ----------------------------------------------------
        # TESTO
        # ----------------------------------------------------

        try:

            elementi = page.get_by_text(
                pattern
            )

            for i in range(
                elementi.count()
            ):

                elemento = elementi.nth(i)

                if not elemento.is_visible():
                    continue

                print(
                    "[volotea] elemento ricerca trovato:",
                    repr(
                        elemento.inner_text()
                    ),
                )

                return elemento

        except Exception:
            pass

        # ----------------------------------------------------
        # SUBMIT
        # ----------------------------------------------------

        try:

            submits = page.locator(
                "input[type='submit']:visible, "
                "button[type='submit']:visible"
            )

            for i in range(
                submits.count()
            ):

                elemento = submits.nth(i)

                if elemento.is_visible():

                    print(
                        "[volotea] submit trovato."
                    )

                    return elemento

        except Exception:
            pass

        return None

    # ========================================================
    # RICERCA API
    # ========================================================

    def esegui_ricerca(
        self,
        page: Page,
        origine: str,
        destinazione: str,
        data_partenza: date,
    ) -> list[dict[str, Any]]:
        """Esegue una ricerca reale tramite frontend."""

        risposta_json: list[Any] = []
        richieste_search: list[Any] = []

        def intercetta_request(
            request,
        ) -> None:

            try:

                if request.method != "POST":
                    return

                if not any(
                    path in request.url
                    for path in SEARCH_PATHS
                ):
                    return

                print("")
                print(
                    "[volotea] REQUEST SEARCH:"
                )

                print(
                    "  METHOD:",
                    request.method,
                )

                print(
                    "  URL:",
                    request.url,
                )

                try:

                    post_data = request.post_data

                    if post_data:

                        print(
                            "  POST DATA:",
                            post_data[:2000],
                        )

                except Exception:
                    pass

                richieste_search.append(
                    request
                )

            except Exception:
                pass

        def intercetta_response(
            response,
        ) -> None:

            try:

                if not any(
                    path in response.url
                    for path in SEARCH_PATHS
                ):
                    return

                if response.request.method != "POST":
                    return

                print("")
                print(
                    "[volotea] RESPONSE SEARCH:"
                )

                print(
                    "  HTTP:",
                    response.status,
                )

                print(
                    "  URL:",
                    response.url,
                )

                if response.status != 200:

                    print(
                        "[volotea] risposta non 200."
                    )

                    return

                try:

                    payload = response.json()

                except Exception as exc:

                    print(
                        "[volotea] risposta non JSON:",
                        exc,
                    )

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
            "request",
            intercetta_request,
        )

        page.on(
            "response",
            intercetta_response,
        )

        print("")
        print("=" * 60)
        print(
            "VOLOTEA - RICERCA"
        )
        print("=" * 60)

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
            "Apertura:",
            BOOKING_URL,
        )

        # ----------------------------------------------------
        # APERTURA
        # ----------------------------------------------------

        try:

            page.goto(
                BOOKING_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

        except Exception as exc:

            print(
                "[volotea] errore apertura:",
                exc,
            )

            return []

        page.wait_for_timeout(
            10000
        )

        print(
            "[volotea] URL finale:",
            page.url,
        )

        print(
            "[volotea] Titolo:",
            page.title(),
        )

        self.chiudi_cookie(
            page
        )

        self.stampa_input(
            page,
            "FORM INIZIALE",
        )

        # ----------------------------------------------------
        # APERTURA SELETTORE
        # ----------------------------------------------------

        if not self.apri_selettore_aeroporti(
            page
        ):

            print(
                "[volotea] impossibile aprire selettore aeroporti."
            )

            return []

        self.stampa_input(
            page,
            "NUOVO FORM AEROPORTI",
        )

        # ----------------------------------------------------
        # ORIGINE
        # ----------------------------------------------------

        if not self.seleziona_aeroporto(
            page,
            "origin",
            origine,
        ):

            print(
                "[volotea] impossibile selezionare origine."
            )

            return []

        # ----------------------------------------------------
        # DESTINAZIONE
        # ----------------------------------------------------

        if not self.seleziona_aeroporto(
            page,
            "destination",
            destinazione,
        ):

            print(
                "[volotea] impossibile selezionare destinazione."
            )

            return []

        # ----------------------------------------------------
        # DATA
        # ----------------------------------------------------

        if not self.seleziona_data(
            page,
            data_partenza,
        ):

            print(
                "[volotea] impossibile selezionare data."
            )

            return []

        # ----------------------------------------------------
        # FORM FINALE
        # ----------------------------------------------------

        self.stampa_input(
            page,
            "FORM FINALE",
        )

        # ----------------------------------------------------
        # SEARCH
        # ----------------------------------------------------

        print("")
        print(
            "RICERCA VOLO"
        )
        print("=" * 60)

        pulsante = (
            self.trova_pulsante_ricerca(
                page
            )
        )

        if pulsante is None:

            print(
                "ERRORE: pulsante Search flights non trovato."
            )

            try:

                print("")
                print(
                    "BUTTON VISIBILI:"
                )

                buttons = page.locator(
                    "button:visible"
                )

                for i in range(
                    min(
                        buttons.count(),
                        50,
                    )
                ):

                    button = buttons.nth(i)

                    try:

                        print(
                            " -",
                            repr(
                                button.inner_text()
                            ),
                        )

                    except Exception:
                        pass

            except Exception:
                pass

            try:

                page.screenshot(
                    path="/tmp/volotea-search-button-failed.png",
                    full_page=True,
                )

            except Exception:
                pass

            return []

        # ----------------------------------------------------
        # CLICK
        # ----------------------------------------------------

        print(
            "[volotea] click Search flights..."
        )

        try:

            pulsante.click(
                timeout=10000
            )

        except Exception as exc:

            print(
                "[volotea] click normale fallito:",
                exc,
            )

            try:

                pulsante.click(
                    force=True,
                    timeout=10000,
                )

            except Exception as exc2:

                print(
                    "[volotea] click forzato fallito:",
                    exc2,
                )

                return []

        print(
            "[volotea] ricerca avviata."
        )

        # ----------------------------------------------------
        # ATTESA API
        # ----------------------------------------------------

        print(
            "[volotea] attesa risposta Search API..."
        )

        page.wait_for_timeout(
            15000
        )

        if not risposta_json:

            page.wait_for_timeout(
                10000
            )

        # ----------------------------------------------------
        # RISULTATI
        # ----------------------------------------------------

        if not risposta_json:

            print("")
            print(
                "[volotea] NESSUNA RISPOSTA SEARCH API."
            )

            print(
                "[volotea] richieste Search intercettate:",
                len(richieste_search),
            )

            try:

                page.screenshot(
                    path="/tmp/volotea-no-search-response.png",
                    full_page=True,
                )

            except Exception:
                pass

            return []

        risultati: list[dict[str, Any]] = []

        for risposta in risposta_json:

            risultati.extend(
                trova_voli(
                    risposta
                )
            )

        # ----------------------------------------------------
        # DEDUPLICA
        # ----------------------------------------------------

        viste = set()
        unici = []

        for volo in risultati:

            dati = estrai_dati_volo(
                volo
            )

            if not dati:
                continue

            chiave = (
                dati["origine"],
                dati["destinazione"],
                dati["data_partenza"],
                dati["partenza"],
                dati["arrivo"],
                dati["prezzo"],
            )

            if chiave in viste:
                continue

            viste.add(
                chiave
            )

            unici.append(
                volo
            )

        print("")
        print(
            "[volotea] voli estratti:",
            len(unici),
        )

        return unici

    # ========================================================
    # SCAN
    # ========================================================

    def scan(
        self,
    ) -> list[Offerta]:
        """Esegue il test Volotea."""

        print("")
        print("=" * 60)
        print(
            "FLIGHT HUNTER - SCANNER VOLOTEA"
        )
        print("=" * 60)

        offerte: list[Offerta] = []

        # ----------------------------------------------------
        # TEST INIZIALE
        # ----------------------------------------------------

        origine = "VRN"
        destinazione = "CTA"

        data_test = self.data_test()

        print("")
        print(
            "TEST CONFIGURATO:"
        )

        print(
            "  Origine:",
            origine,
        )

        print(
            "  Destinazione:",
            destinazione,
        )

        print(
            "  Data:",
            data_test.isoformat(),
        )

        with sync_playwright() as p:

            browser: Browser | None = None
            context = None

            try:

                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
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
                        "(X11; Linux x86_64) "
                        "AppleWebKit/537.36 "
                        "(KHTML, like Gecko) "
                        "Chrome/140.0.0.0 Safari/537.36"
                    ),
                )

                page = context.new_page()

                voli = self.esegui_ricerca(
                    page,
                    origine,
                    destinazione,
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
                        "  Origine:",
                        dati["origine"],
                    )

                    print(
                        "  Destinazione:",
                        dati["destinazione"],
                    )

                    print(
                        "  Data:",
                        dati["data_partenza"],
                    )

                    print(
                        "  Partenza:",
                        estrai_ora(
                            dati["partenza"]
                        ),
                    )

                    print(
                        "  Arrivo:",
                        estrai_ora(
                            dati["arrivo"]
                        ),
                    )

                    print(
                        "  Durata:",
                        dati["durata"],
                        "minuti",
                    )

                    print(
                        "  Numero volo:",
                        dati["numero_volo"],
                    )

                    print(
                        "  Prezzo:",
                        dati["prezzo"],
                    )

                    prezzo = dati[
                        "prezzo"
                    ]

                    if (
                        prezzo
                        > settings.prezzo_massimo
                    ):

                        print(
                            "[volotea] prezzo oltre il limite:",
                            prezzo,
                        )

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

                            prezzo=
                                prezzo,

                            data_partenza=
                                dati["data_partenza"],

                            ora_partenza=
                                estrai_ora(
                                    dati["partenza"]
                                ),

                            ora_arrivo=
                                estrai_ora(
                                    dati["arrivo"]
                                ),

                            durata_andata=
                                dati["durata"],

                            fonte_dato=
                                "scanner",
                        )
                    )

            except Exception as exc:

                print("")
                print(
                    "[volotea] ERRORE SCANNER:"
                )

                print(
                    repr(exc)
                )

                traceback.print_exc()

            finally:

                if context is not None:

                    try:
                        context.close()
                    except Exception:
                        pass

                if browser is not None:

                    try:
                        browser.close()
                    except Exception:
                        pass

        print("")
        print("=" * 60)
        print(
            "VOLOTEA COMPLETATO"
        )
        print("=" * 60)

        print(
            "Offerte prodotte:",
            len(offerte),
        )

        return offerte
