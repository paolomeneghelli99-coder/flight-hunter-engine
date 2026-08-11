"""Scanner Volotea tramite browser Playwright.

Lo scanner utilizza il booking engine pubblico Volotea e
intercetta la risposta reale della ricerca voli.

Strategia:

1. Apre il booking engine Volotea.
2. Chiude il banner cookie, se presente.
3. Seleziona un aeroporto di origine configurato in settings.origini.
4. Legge dal selettore Volotea le destinazioni effettivamente disponibili.
5. Scarta le destinazioni non valide o uguali all'origine.
6. Cerca i voli solo sulle tratte realmente disponibili.
7. Intercetta la risposta reale della ricerca voli.
8. Estrae prezzo, orari, durata e numero volo.
9. Converte i risultati nel modello Offerta di Flight Hunter.

Non vengono utilizzati endpoint storici delle stazioni.

La scansione delle tratte viene ricavata direttamente dal frontend
Volotea, evitando di provare indiscriminatamente combinazioni
origine/destinazione inesistenti.
"""

from __future__ import annotations

import re
import traceback
from datetime import date, datetime, timedelta
from typing import Any

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    sync_playwright,
)

from config.settings import settings
from scanners.base import BaseScanner, Offerta


BOOKING_URL = "https://book.volotea.com/search"

SEARCH_PATHS = (
    "/api/spa/voe/v1/flights/search",
    "/flights/search",
)

IATA_RE = re.compile(r"\b([A-Z]{3})\b")


# ============================================================
# UTILITÀ
# ============================================================

def estrai_ora(
    value: str | None,
) -> str | None:
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

        durata = int(
            (a - p).total_seconds() / 60
        )

        if durata < 0:
            return None

        return durata

    except Exception:

        return None


def estrai_prezzo(
    volo: dict[str, Any],
) -> float | None:
    """Estrae il prezzo minimo per un adulto."""

    prezzi: list[float] = []

    fares = volo.get("fares") or []

    if not isinstance(fares, list):
        return None

    for fare in fares:

        if not isinstance(fare, dict):
            continue

        passenger_fares = (
            fare.get("passengerFares") or []
        )

        if not isinstance(
            passenger_fares,
            list,
        ):
            continue

        for passenger in passenger_fares:

            if not isinstance(
                passenger,
                dict,
            ):
                continue

            if (
                passenger.get("passengerType")
                != "ADT"
            ):
                continue

            fare_amount = (
                passenger.get("fareAmount")
                or {}
            )

            if not isinstance(
                fare_amount,
                dict,
            ):
                continue

            valore = (
                fare_amount.get("eurAmount")
                or fare_amount.get("amount")
            )

            if valore is None:
                continue

            try:

                prezzo = float(valore)

            except (
                TypeError,
                ValueError,
            ):

                continue

            if prezzo > 0:
                prezzi.append(prezzo)

    if not prezzi:
        return None

    return min(prezzi)


def trova_voli(
    obj: Any,
) -> list[dict[str, Any]]:
    """Cerca ricorsivamente gli oggetti volo nella risposta API."""

    risultati: list[dict[str, Any]] = []

    def visita(
        value: Any,
    ) -> None:

        if isinstance(
            value,
            dict,
        ):

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

        elif isinstance(
            value,
            list,
        ):

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

    if not isinstance(
        designator,
        dict,
    ):
        return None

    origine = str(
        designator.get("origin")
        or ""
    ).upper()

    destinazione = str(
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

    if (
        isinstance(
            segments,
            list,
        )
        and segments
    ):

        primo_segmento = segments[0]

        if isinstance(
            primo_segmento,
            dict,
        ):

            identifier = (
                primo_segmento.get(
                    "identifier"
                )
                or {}
            )

            if isinstance(
                identifier,
                dict,
            ):

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
    # DATA MINIMA
    # ========================================================

    def giorni_minimi(self) -> int:
        """Restituisce il numero minimo di giorni da oggi.

        Vengono controllate diverse denominazioni possibili per
        mantenere compatibilità con eventuali impostazioni già
        presenti nel progetto.

        Se nessuna è presente viene utilizzato +1 giorno.
        """

        nomi = (
            "giorni_minimi",
            "giorni_minimi_partenza",
            "min_giorni",
            "giorni_minimi_volo",
            "min_days",
        )

        for nome in nomi:

            try:

                valore = getattr(
                    settings,
                    nome,
                    None,
                )

                if valore is None:
                    continue

                valore = int(valore)

                if valore >= 0:
                    return valore

            except (
                TypeError,
                ValueError,
            ):
                continue

        return 1

    def data_test(self) -> date:
        """Prima data utile utilizzabile dallo scanner."""

        return (
            date.today()
            + timedelta(
                days=self.giorni_minimi()
            )
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
            "button:has-text('Accept all')",
            "button:has-text('Accetta tutto')",
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
                        "[volotea] cookie banner chiuso."
                    )

                    return

            except Exception:
                continue

    # ========================================================
    # APERTURA SELETTORE
    # ========================================================

    def apri_selettore_aeroporti(
        self,
        page: Page,
    ) -> bool:
        """Apre il selettore aeroporti del frontend Volotea."""

        trigger_selettori = [
            "#input-text_sf-origin:visible",
            "input[id='input-text_sf-origin']:visible",
            "input[placeholder='Select airport']:visible",
            "input[placeholder*='Select airport' i]:visible",
        ]

        for selettore in trigger_selettori:

            try:

                elementi = page.locator(
                    selettore
                )

                count = elementi.count()

                if count == 0:
                    continue

                for i in range(count):

                    elemento = elementi.nth(i)

                    if not elemento.is_visible():
                        continue

                    print(
                        "[volotea] trigger aeroporto trovato:",
                        selettore,
                    )

                    elemento.click(
                        force=True,
                        timeout=10000,
                    )

                    page.wait_for_timeout(
                        1200
                    )

                    if (
                        page.locator(
                            "#origin:visible"
                        ).count() > 0
                        or
                        page.locator(
                            "#destination:visible"
                        ).count() > 0
                    ):
                        return True

            except Exception as exc:

                print(
                    "[volotea] errore apertura selettore:",
                    repr(exc),
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
        """Seleziona un aeroporto tramite codice IATA."""

        codice = codice.upper()

        print(
            f"[volotea] selezione {campo}: {codice}"
        )

        input_locator = page.locator(
            f"#{campo}:visible"
        ).first

        if input_locator.count() == 0:

            if not self.apri_selettore_aeroporti(
                page
            ):
                return False

            input_locator = page.locator(
                f"#{campo}:visible"
            ).first

        if input_locator.count() == 0:
            return False

        try:

            input_locator.wait_for(
                state="visible",
                timeout=10000,
            )

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
                1500
            )

        except Exception as exc:

            print(
                f"[volotea] errore compilazione {campo}:",
                repr(exc),
            )

            return False

        candidati = [
            page.locator(
                "[role='option']:visible"
            ),
            page.locator(
                "li:visible"
            ),
            page.locator(
                "button:visible"
            ),
        ]

        for locator in candidati:

            try:

                count = locator.count()

                for i in range(count):

                    elemento = locator.nth(i)

                    if not elemento.is_visible():
                        continue

                    try:

                        testo = (
                            elemento.inner_text()
                            .strip()
                        )

                    except Exception:

                        continue

                    if not testo:
                        continue

                    righe = [
                        r.strip()
                        for r in testo.splitlines()
                        if r.strip()
                    ]

                    match_esatto = any(
                        r.upper() == codice
                        for r in righe
                    )

                    contiene_codice = (
                        codice in testo.upper()
                    )

                    if not (
                        match_esatto
                        or (
                            contiene_codice
                            and len(testo) < 200
                        )
                    ):
                        continue

                    print(
                        "[volotea] aeroporto candidato:",
                        repr(testo),
                    )

                    try:

                        elemento.click(
                            force=True,
                            timeout=5000,
                        )

                    except Exception:

                        try:

                            elemento.locator(
                                "xpath=.."
                            ).click(
                                force=True,
                                timeout=5000,
                            )

                        except Exception:

                            continue

                    page.wait_for_timeout(
                        1000
                    )

                    return True

            except Exception:
                continue

        selettori_iata = [
            "p.c-iata-tag__text:visible",
            "[class*='iata']:visible",
            "[class*='IATA']:visible",
        ]

        for selettore in selettori_iata:

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

                    testo = (
                        elemento.inner_text()
                        .strip()
                    )

                    if testo.upper() != codice:
                        continue

                    elemento.click(
                        force=True,
                        timeout=5000,
                    )

                    page.wait_for_timeout(
                        1000
                    )

                    return True

            except Exception:
                continue

        print(
            f"[volotea] aeroporto {codice} non selezionato."
        )

        return False

    # ========================================================
    # ESTRAZIONE DESTINAZIONI
    # ========================================================

    def estrai_iata_da_testo(
        self,
        testo: str,
    ) -> list[str]:
        """Estrae codici IATA da un testo visibile."""

        risultati: list[str] = []

        if not testo:
            return risultati

        for match in IATA_RE.findall(
            testo.upper()
        ):

            if match not in risultati:
                risultati.append(match)

        return risultati

    def raccogli_destinazioni_visibili(
        self,
        page: Page,
        origine: str,
    ) -> list[str]:
        """Raccoglie le destinazioni mostrate dal selettore Volotea."""

        origine = origine.upper()

        destinazioni: list[str] = []

        selettori = [
            "[role='option']:visible",
            "li:visible",
            "button:visible",
        ]

        for selettore in selettori:

            try:

                elementi = page.locator(
                    selettore
                )

                count = elementi.count()

                for i in range(count):

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

                    if not testo:
                        continue

                    if len(testo) > 300:
                        continue

                    righe = [
                        r.strip()
                        for r in testo.splitlines()
                        if r.strip()
                    ]

                    candidati: list[str] = []

                    # Prima proviamo una riga che sia
                    # esattamente un codice IATA.

                    for riga in righe:

                        if re.fullmatch(
                            r"[A-Z]{3}",
                            riga.upper(),
                        ):
                            candidati.append(
                                riga.upper()
                            )

                    # Poi analizziamo il testo completo.
                    if not candidati:

                        candidati.extend(
                            self.estrai_iata_da_testo(
                                testo
                            )
                        )

                    for codice in candidati:

                        if codice == origine:
                            continue

                        if codice not in destinazioni:
                            destinazioni.append(
                                codice
                            )

            except Exception:
                continue

        return destinazioni

    def apri_selettore_destinazione(
        self,
        page: Page,
    ) -> bool:
        """Apre il campo destinazione."""

        selettori = [
            "#destination:visible",
            "input[id='destination']:visible",
            "input[placeholder*='destination' i]:visible",
            "input[placeholder*='airport' i]:visible",
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

                    elemento.click(
                        force=True,
                        timeout=5000,
                    )

                    page.wait_for_timeout(
                        1000
                    )

                    return True

            except Exception:
                continue

        return False

    def scopri_destinazioni(
        self,
        page: Page,
        origine: str,
    ) -> list[str]:
        """Scopre le destinazioni realmente disponibili per l'origine."""

        print(
            f"[volotea] ricerca destinazioni disponibili da {origine}"
        )

        destinazioni: list[str] = []

        # ----------------------------------------------------
        # Dopo la selezione dell'origine il frontend può già
        # mostrare le destinazioni.
        # ----------------------------------------------------

        destinazioni.extend(
            self.raccogli_destinazioni_visibili(
                page,
                origine,
            )
        )

        # ----------------------------------------------------
        # Proviamo anche ad aprire esplicitamente il campo
        # destinazione.
        # ----------------------------------------------------

        if self.apri_selettore_destinazione(
            page
        ):

            page.wait_for_timeout(
                1000
            )

            nuove = (
                self.raccogli_destinazioni_visibili(
                    page,
                    origine,
                )
            )

            for codice in nuove:

                if codice not in destinazioni:
                    destinazioni.append(
                        codice
                    )

        # ----------------------------------------------------
        # Elimina valori palesemente non utili.
        # ----------------------------------------------------

        filtrate: list[str] = []

        for codice in destinazioni:

            codice = codice.upper()

            if not re.fullmatch(
                r"[A-Z]{3}",
                codice,
            ):
                continue

            if codice == origine.upper():
                continue

            if codice not in filtrate:
                filtrate.append(
                    codice
                )

        print(
            f"[volotea] destinazioni disponibili da "
            f"{origine}: {len(filtrate)}"
        )

        if filtrate:

            print(
                "[volotea] tratte disponibili:",
                ", ".join(filtrate),
            )

        else:

            print(
                f"[volotea] nessuna destinazione rilevata "
                f"per {origine}"
            )

        return filtrate

    # ========================================================
    # DATA
    # ========================================================

    def seleziona_data(
        self,
        page: Page,
        data_partenza: date,
    ) -> bool:
        """Seleziona la data richiesta."""

        selettori = [
            "#departure:visible",
            "input[name='departure']:visible",
            "input[placeholder*='departure' i]:visible",
            "input[placeholder*='date' i]:visible",
        ]

        departure = None

        for selettore in selettori:

            try:

                loc = page.locator(
                    selettore
                ).first

                if (
                    loc.count() > 0
                    and loc.is_visible()
                ):

                    departure = loc
                    break

            except Exception:
                continue

        if departure is None:
            return False

        try:

            departure.click(
                force=True,
                timeout=5000,
            )

            page.wait_for_timeout(
                1000
            )

        except Exception:

            return False

        giorno = str(
            data_partenza.day
        )

        # ----------------------------------------------------
        # aria-label
        # ----------------------------------------------------

        selettori_data = [
            (
                "button[aria-label*='"
                + giorno
                + "']:visible"
            ),
            (
                "[role='button'][aria-label*='"
                + giorno
                + "']:visible"
            ),
            (
                "[role='gridcell'][aria-label*='"
                + giorno
                + "']:visible"
            ),
        ]

        for selettore in selettori_data:

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

                    elemento.click(
                        force=True,
                        timeout=5000,
                    )

                    page.wait_for_timeout(
                        800
                    )

                    return True

            except Exception:
                continue

        # ----------------------------------------------------
        # Fallback giorno esatto
        # ----------------------------------------------------

        try:

            elementi = page.locator(
                "button:visible, "
                "[role='button']:visible, "
                "[role='gridcell']:visible"
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
                        800
                    )

                    return True

                except Exception:
                    continue

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
        """Trova il pulsante di ricerca."""

        pattern = re.compile(
            r"search\s*flights|"
            r"buscar\s*vuelos|"
            r"rechercher|"
            r"cerca\s*voli|"
            r"cerca\s*volo",
            re.I,
        )

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

                if pattern.search(
                    testo
                ):
                    return button

        except Exception:
            pass

        try:

            elementi = page.get_by_text(
                pattern
            )

            for i in range(
                elementi.count()
            ):

                elemento = elementi.nth(i)

                if elemento.is_visible():
                    return elemento

        except Exception:
            pass

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
                    return elemento

        except Exception:
            pass

        return None

    # ========================================================
    # RICERCA SINGOLA TRATTA
    # ========================================================

    def esegui_ricerca(
        self,
        page: Page,
        origine: str,
        destinazione: str,
        data_partenza: date,
    ) -> list[dict[str, Any]]:
        """Esegue una ricerca Volotea reale."""

        risposta_json: list[Any] = []

        def intercetta_response(
            response,
        ) -> None:

            try:

                if not any(
                    path in response.url
                    for path in SEARCH_PATHS
                ):
                    return

                if (
                    response.request.method
                    != "POST"
                ):
                    return

                print(
                    "[volotea] SEARCH RESPONSE:",
                    response.status,
                    response.url,
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

            except Exception:
                pass

        page.on(
            "response",
            intercetta_response,
        )

        try:

            page.goto(
                BOOKING_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

        except Exception as exc:

            print(
                "[volotea] errore apertura:",
                repr(exc),
            )

            return []

        page.wait_for_timeout(
            10000
        )

        self.chiudi_cookie(
            page
        )

        if not self.apri_selettore_aeroporti(
            page
        ):
            return []

        if not self.seleziona_aeroporto(
            page,
            "origin",
            origine,
        ):
            return []

        if not self.seleziona_aeroporto(
            page,
            "destination",
            destinazione,
        ):
            return []

        if not self.seleziona_data(
            page,
            data_partenza,
        ):
            return []

        pulsante = (
            self.trova_pulsante_ricerca(
                page
            )
        )

        if pulsante is None:

            print(
                "[volotea] pulsante ricerca non trovato."
            )

            return []

        try:

            pulsante.click(
                timeout=10000
            )

        except Exception:

            try:

                pulsante.click(
                    force=True,
                    timeout=10000,
                )

            except Exception as exc:

                print(
                    "[volotea] click ricerca fallito:",
                    repr(exc),
                )

                return []

        page.wait_for_timeout(
            15000
        )

        if not risposta_json:

            page.wait_for_timeout(
                15000
            )

        risultati: list[
            dict[str, Any]
        ] = []

        for risposta in risposta_json:

            risultati.extend(
                trova_voli(
                    risposta
                )
            )

        return risultati

    # ========================================================
    # CREAZIONE PAGINA DI RICERCA
    # ========================================================

    def prepara_pagina(
        self,
        context: BrowserContext,
    ) -> Page | None:
        """Crea e prepara una nuova pagina Volotea."""

        page = context.new_page()

        try:

            page.goto(
                BOOKING_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            page.wait_for_timeout(
                10000
            )

            self.chiudi_cookie(
                page
            )

            if not self.apri_selettore_aeroporti(
                page
            ):

                page.close()

                return None

            return page

        except Exception as exc:

            print(
                "[volotea] errore preparazione pagina:",
                repr(exc),
            )

            try:
                page.close()
            except Exception:
                pass

            return None

    # ========================================================
    # SCAN
    # ========================================================

    def scan(
        self,
    ) -> list[Offerta]:
        """Esegue la scansione completa Volotea."""

        print("")
        print("=" * 60)
        print(
            "FLIGHT HUNTER - SCANNER VOLOTEA"
        )
        print("=" * 60)

        offerte: list[Offerta] = []

        data_test = self.data_test()

        print(
            "[volotea] data minima utilizzata:",
            data_test.isoformat(),
        )

        print(
            "[volotea] giorni minimi:",
            self.giorni_minimi(),
        )

        browser: Browser | None = None
        context: BrowserContext | None = None

        # ----------------------------------------------------
        # DEDUPLICA TRATTE
        # ----------------------------------------------------

        tratte_viste: set[
            tuple[str, str]
        ] = set()

        try:

            with sync_playwright() as p:

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

                # ------------------------------------------------
                # PER OGNI ORIGINE
                # ------------------------------------------------

                for origine in self.origini:

                    origine = str(
                        origine
                    ).upper().strip()

                    if not re.fullmatch(
                        r"[A-Z]{3}",
                        origine,
                    ):
                        print(
                            "[volotea] origine ignorata:",
                            origine,
                        )
                        continue

                    print("")
                    print(
                        "=" * 60
                    )

                    print(
                        f"[volotea] analisi origine: {origine}"
                    )

                    print(
                        "=" * 60
                    )

                    # --------------------------------------------
                    # PAGINA USATA PER SCOPRIRE LE TRATTE
                    # --------------------------------------------

                    pagina_discovery = (
                        self.prepara_pagina(
                            context
                        )
                    )

                    if pagina_discovery is None:
                        continue

                    try:

                        if not self.seleziona_aeroporto(
                            pagina_discovery,
                            "origin",
                            origine,
                        ):

                            print(
                                f"[volotea] impossibile selezionare "
                                f"origine {origine}"
                            )

                            continue

                        destinazioni = (
                            self.scopri_destinazioni(
                                pagina_discovery,
                                origine,
                            )
                        )

                    except Exception as exc:

                        print(
                            f"[volotea] errore scoperta "
                            f"tratte da {origine}:",
                            repr(exc),
                        )

                        destinazioni = []

                    finally:

                        try:
                            pagina_discovery.close()
                        except Exception:
                            pass

                    # --------------------------------------------
                    # Se il frontend non restituisce destinazioni
                    # NON inventiamo tratte.
                    # --------------------------------------------

                    if not destinazioni:

                        print(
                            f"[volotea] nessuna tratta verificabile "
                            f"da {origine}: origine saltata."
                        )

                        continue

                    # --------------------------------------------
                    # RICERCA DELLE TRATTE
                    # --------------------------------------------

                    for destinazione in destinazioni:

                        destinazione = (
                            destinazione.upper().strip()
                        )

                        if destinazione == origine:
                            continue

                        if not re.fullmatch(
                            r"[A-Z]{3}",
                            destinazione,
                        ):
                            continue

                        chiave_tratta = (
                            origine,
                            destinazione,
                        )

                        if chiave_tratta in tratte_viste:
                            continue

                        tratte_viste.add(
                            chiave_tratta
                        )

                        print("")
                        print(
                            f"[volotea] ricerca "
                            f"{origine} -> {destinazione}"
                        )

                        page = context.new_page()

                        try:

                            voli = self.esegui_ricerca(
                                page,
                                origine,
                                destinazione,
                                data_test,
                            )

                            print(
                                f"[volotea] voli ricevuti "
                                f"{origine}->{destinazione}:",
                                len(voli),
                            )

                            viste_voli: set[
                                tuple[Any, ...]
                            ] = set()

                            for volo in voli:

                                dati = (
                                    estrai_dati_volo(
                                        volo
                                    )
                                )

                                if not dati:
                                    continue

                                if (
                                    dati["origine"]
                                    != origine
                                ):
                                    continue

                                if (
                                    dati["destinazione"]
                                    != destinazione
                                ):
                                    continue

                                if (
                                    dati["prezzo"]
                                    > self.prezzo_massimo
                                ):
                                    continue

                                chiave_volo = (
                                    dati["origine"],
                                    dati["destinazione"],
                                    dati["data_partenza"],
                                    dati["partenza"],
                                    dati["arrivo"],
                                    dati["prezzo"],
                                )

                                if (
                                    chiave_volo
                                    in viste_voli
                                ):
                                    continue

                                viste_voli.add(
                                    chiave_volo
                                )

                                print("")
                                print(
                                    "[volotea] VOLO TROVATO"
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
                                            dati["prezzo"],

                                        valuta=
                                            settings.valuta,

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

                            print(
                                f"[volotea] errore "
                                f"{origine}->{destinazione}:",
                                repr(exc),
                            )

                            traceback.print_exc()

                        finally:

                            try:
                                page.close()
                            except Exception:
                                pass

        except Exception as exc:

            print(
                "[volotea] ERRORE SCANNER:",
                repr(exc),
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

        # ----------------------------------------------------
        # DEDUPLICA GLOBALE
        # ----------------------------------------------------

        viste_finali: set[
            tuple[Any, ...]
        ] = set()

        offerte_uniche: list[
            Offerta
        ] = []

        for offerta in offerte:

            chiave = (
                offerta.aeroporto_partenza,
                offerta.aeroporto_arrivo,
                offerta.data_partenza,
                offerta.ora_partenza,
                offerta.ora_arrivo,
                offerta.prezzo,
            )

            if chiave in viste_finali:
                continue

            viste_finali.add(
                chiave
            )

            offerte_uniche.append(
                offerta
            )

        offerte_uniche.sort(
            key=lambda o: o.prezzo
        )

        print("")
        print("=" * 60)
        print(
            "VOLOTEA COMPLETATO"
        )
        print("=" * 60)

        print(
            "Tratte verificate:",
            len(tratte_viste),
        )

        print(
            "Offerte prodotte:",
            len(offerte_uniche),
        )

        return offerte_uniche
