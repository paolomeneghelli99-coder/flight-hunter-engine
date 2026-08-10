"""Scanner Volotea tramite browser Playwright.

Strategia:

1. Apre il nuovo booking engine Volotea.
2. Utilizza il form reale del frontend.
3. Imposta origine, destinazione e data.
4. Intercetta le richieste/risposte reali verso flights/search.
5. Estrae voli, prezzi, orari e durata.
6. Converte i risultati nel modello Offerta di Flight Hunter.

NOTA:
L'endpoint storico stations.json non viene più utilizzato perché
attualmente restituisce HTTP 404.
"""

from __future__ import annotations

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

    partenza = (
        designator.get("departure")
    )

    arrivo = (
        designator.get("arrival")
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
    # DATE
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
            "button:has-text('Only essential')",
            "button:has-text('Solo essenziali')",
            "button:has-text('Accetta solo i necessari')",
        ]

        for selettore in selettori:

            try:

                locator = page.locator(
                    selettore
                )

                if locator.count() == 0:
                    continue

                for i in range(
                    locator.count()
                ):

                    elemento = locator.nth(i)

                    if elemento.is_visible():

                        print(
                            "[volotea] cookie banner trovato:",
                            selettore,
                        )

                        elemento.click(
                            timeout=5000
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
    # APERTURA SELETTORE
    # ========================================================

    def apri_selettore_aeroporti(
        self,
        page: Page,
    ) -> bool:
        """Apre il nuovo componente aeroporti."""

        print("")
        print(
            "APERTURA SELETTORE AEROPORTI"
        )
        print("=" * 60)

        # Primo tentativo: click sugli input vecchi/nuovi.
        for selettore in (
            "#origin",
            "#destination",
            "input[name='origin']",
            "input[placeholder='Select airport']",
        ):

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
                    timeout=5000,
                )

                print(
                    "[volotea] selettore aeroporti aperto:",
                    selettore,
                )

                page.wait_for_timeout(
                    500
                )

                return True

            except Exception:
                continue

        print(
            "[volotea] impossibile aprire il selettore aeroporti."
        )

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
        """Seleziona un aeroporto nel nuovo componente."""

        codice = codice.upper()

        print("")
        print(
            f"[volotea] selezione {campo}: {codice}"
        )

        # Individua input.
        selettori = [
            f"#{campo}",
            f"input[name='{campo}']",
        ]

        input_locator = None

        for selettore in selettori:

            try:

                loc = page.locator(
                    selettore
                ).first

                if loc.count() > 0:
                    input_locator = loc
                    break

            except Exception:
                continue

        if input_locator is None:

            print(
                f"[volotea] campo {campo} non trovato."
            )

            return False

        try:

            input_locator.fill(
                codice
            )

            page.wait_for_timeout(
                800
            )

        except Exception as exc:

            print(
                f"[volotea] errore compilazione {campo}:",
                exc,
            )

            return False

        # Cerchiamo l'opzione che contiene esattamente
        # il codice aeroporto.
        candidati = [
            page.get_by_text(
                re.compile(
                    rf"^\s*{re.escape(codice)}\s*$",
                    re.I,
                )
            ),
            page.locator(
                f"text={codice}"
            ),
        ]

        for candidati_locator in candidati:

            try:

                count = candidati_locator.count()

                for i in range(count):

                    elemento = (
                        candidati_locator.nth(i)
                    )

                    if not elemento.is_visible():
                        continue

                    try:

                        testo = (
                            elemento.inner_text()
                            .strip()
                        )

                    except Exception:

                        testo = ""

                    if (
                        codice
                        not in testo.upper()
                    ):
                        continue

                    print(
                        "[volotea] opzione trovata:",
                        repr(testo),
                    )

                    elemento.click(
                        timeout=5000
                    )

                    page.wait_for_timeout(
                        500
                    )

                    print(
                        f"[volotea] {campo} selezionato: {codice}"
                    )

                    return True

            except Exception:
                continue

        # Fallback: cerchiamo elementi contenenti il codice
        # e almeno un nome città.
        try:

            elementi = page.locator(
                "text=" + codice
            )

            for i in range(
                elementi.count()
            ):

                elemento = (
                    elementi.nth(i)
                )

                if not elemento.is_visible():
                    continue

                testo = (
                    elemento.inner_text()
                    .strip()
                )

                if codice in testo.upper():

                    print(
                        "[volotea] fallback opzione:",
                        repr(testo),
                    )

                    elemento.click(
                        timeout=5000
                    )

                    page.wait_for_timeout(
                        500
                    )

                    return True

        except Exception:
            pass

        print(
            f"[volotea] aeroporto {codice} non selezionato."
        )

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

        # Apriamo il campo departure.
        try:

            departure = page.locator(
                "#departure"
            ).first

            if departure.count() == 0:

                departure = page.locator(
                    "input[name='departure']"
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
                500
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

        # Prima cerchiamo un bottone/data con aria-label.
        selettori = [
            f"button[aria-label*='{giorno}']",
            f"[role='button'][aria-label*='{giorno}']",
            f"button:has-text('{giorno}')",
        ]

        for selettore in selettori:

            try:

                elementi = page.locator(
                    selettore
                )

                for i in range(
                    elementi.count()
                ):

                    elemento = (
                        elementi.nth(i)
                    )

                    if not elemento.is_visible():
                        continue

                    testo = ""

                    try:
                        testo = (
                            elemento.inner_text()
                            .strip()
                        )
                    except Exception:
                        pass

                    print(
                        "[volotea] giorno candidato:",
                        repr(testo),
                    )

                    elemento.click(
                        timeout=5000
                    )

                    print(
                        "[volotea] giorno selezionato:",
                        giorno,
                    )

                    return True

            except Exception:
                continue

        # Fallback molto più permissivo.
        try:

            elementi = page.locator(
                "text=" + giorno
            )

            for i in range(
                elementi.count()
            ):

                elemento = (
                    elementi.nth(i)
                )

                if not elemento.is_visible():
                    continue

                try:

                    testo = (
                        elemento.inner_text()
                        .strip()
                    )

                except Exception:

                    testo = ""

                if testo == giorno:

                    elemento.click(
                        timeout=5000
                    )

                    print(
                        "[volotea] giorno selezionato:",
                        giorno,
                    )

                    return True

        except Exception:
            pass

        print(
            "[volotea] giorno non trovato:",
            giorno,
        )

        return False

    # ========================================================
    # RICERCA
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

        # 1. Role button
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

                testo = (
                    button.inner_text()
                    .strip()
                )

                if pattern.search(testo):

                    print(
                        "[volotea] pulsante trovato tramite role=button:",
                        repr(testo),
                    )

                    return button

        except Exception:
            pass

        # 2. Elementi con testo.
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
                    "[volotea] pulsante trovato tramite testo:",
                    repr(
                        elemento.inner_text()
                    ),
                )

                return elemento

        except Exception:
            pass

        # 3. input submit.
        try:

            submits = page.locator(
                "input[type='submit'], "
                "button[type='submit']"
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
    # INTERCETTAZIONE SEARCH API
    # ========================================================

    def esegui_ricerca(
        self,
        page: Page,
        origine: str,
        destinazione: str,
        data_partenza: date,
    ) -> list[dict[str, Any]]:
        """Esegue una ricerca reale tramite il frontend."""

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

                    post_data = (
                        request.post_data
                    )

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

        try:

            page.wait_for_timeout(
                5000
            )

        except Exception:
            pass

        self.chiudi_cookie(
            page
        )

        self.stampa_input(
            page,
            "FORM INIZIALE",
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
        # PULSANTE SEARCH
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

            # Diagnostica DOM utile per il prossimo fix.
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
                        30,
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

        # ----------------------------------------------------
        # ATTESA API
        # ----------------------------------------------------

        print(
            "[volotea] attesa risposta Search API..."
        )

        try:

            page.wait_for_timeout(
                15000
            )

        except Exception:
            pass

        # Aspettiamo ancora se la rete sta lavorando.
        if not risposta_json:

            try:

                page.wait_for_timeout(
                    10000
                )

            except Exception:
                pass

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

            return []

        risultati: list[dict[str, Any]] = []

        for risposta in risposta_json:

            risultati.extend(
                trova_voli(
                    risposta
                )
            )

        # Deduplica voli.
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
        #
        # NON utilizziamo più stations.json.
        #
        # In questa fase testiamo esplicitamente VRN -> CTA.
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

                import traceback

                traceback.print_exc()

            finally:

                try:
                    context.close()
                except Exception:
                    pass

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
