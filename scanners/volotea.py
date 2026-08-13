"""Scanner Volotea tramite browser Playwright.

Lo scanner utilizza il booking engine pubblico Volotea e
intercetta la risposta reale della ricerca voli.

Gli aeroporti di partenza NON sono hardcodati:
vengono letti da self.origini, cioè dagli aeroporti selezionati
e passati a Flight Hunter.

Per ogni aeroporto di partenza configurato viene interrogato
il selettore aeroporti Volotea e vengono utilizzate solamente
le destinazioni realmente disponibili.

Le destinazioni indicate da Volotea come "Connection" vengono
escluse perché non rappresentano un collegamento diretto.

La struttura delle offerte prodotte è compatibile con scanners.base.

============================================================
NOTE VERSIONE (fix diagnosi "0 voli trovati")
============================================================
Rispetto alla versione precedente:

1. trova_pulsante_ricerca() ora privilegia i veri pulsanti
   type="submit" ed esclude esplicitamente elementi dentro
   <header>/<nav>, per evitare di cliccare un CTA sbagliato
   nella pagina invece del vero pulsante del widget di ricerca.

2. Nuovo metodo seleziona_solo_andata(): tentativo best-effort
   di impostare la ricerca in modalità "solo andata", nel caso
   il motore richieda una data di ritorno per poter sottomettere
   la ricerca. Se non trova alcun controllo simile non fa nulla.

3. seleziona_data(): il ramo di fallback (match sul solo numero
   del giorno) ora tenta di disambiguare il mese corretto tramite
   le intestazioni mese/anno visibili nel calendario. Se non riesce
   a confermare il mese, fallisce esplicitamente invece di rischiare
   un click sulla data sbagliata. Dopo ogni selezione riuscita viene
   riletto e loggato il valore effettivo del campo data.

4. esegui_ricerca(): logging diagnostico aggiuntivo su URL
   prima/dopo il click sul pulsante di ricerca e su presenza/assenza
   di una risposta di rete intercettata sui path di ricerca.
============================================================
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

DEFAULT_DAYS_MIN = 1
DEFAULT_DAYS_MAX = 14

MAX_DESTINATIONS_PER_ORIGIN = 100
MAX_FLIGHTS_PER_SEARCH = 1000

PAGE_LOAD_WAIT_MS = 8000
AIRPORT_WAIT_MS = 1500
DATE_WAIT_MS = 1000
SEARCH_WAIT_MS = 15000

NOMI_MESE = {
    1: ("january", "gennaio"),
    2: ("february", "febbraio"),
    3: ("march", "marzo"),
    4: ("april", "aprile"),
    5: ("may", "maggio"),
    6: ("june", "giugno"),
    7: ("july", "luglio"),
    8: ("august", "agosto"),
    9: ("september", "settembre"),
    10: ("october", "ottobre"),
    11: ("november", "novembre"),
    12: ("december", "dicembre"),
}

PATTERN_INTESTAZIONE_MESE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|"
    r"October|November|December|"
    r"Gennaio|Febbraio|Marzo|Aprile|Maggio|Giugno|Luglio|Agosto|"
    r"Settembre|Ottobre|Novembre|Dicembre)\s+\d{4}$",
    re.I,
)


# ============================================================
# FUNZIONI DI SUPPORTO
# ============================================================

def texto_normalizzato(testo: str) -> str:
    """Normalizza il testo per la ricerca del codice IATA."""

    return re.sub(
        r"\s+",
        " ",
        testo.upper(),
    )


def estrai_primo_iata(testo: str) -> str | None:
    """Estrae il primo codice IATA plausibile dal testo."""

    if not testo:
        return None

    righe = [
        r.strip().upper()
        for r in testo.splitlines()
        if r.strip()
    ]

    for riga in righe:
        if re.fullmatch(r"[A-Z]{3}", riga):
            return riga

    match = re.search(
        r"\b([A-Z]{3})\b",
        texto_normalizzato(testo),
    )

    if match:
        return match.group(1).upper()

    return None


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

        durata = int(
            (a - p).total_seconds() / 60
        )

        if durata <= 0:
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

            passenger_type = (
                passenger.get("passengerType")
                or passenger.get("type")
            )

            if passenger_type not in (
                "ADT",
                "adult",
                "Adult",
                None,
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
                or fare_amount.get("value")
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

    viste_id: set[int] = set()

    def visita(value: Any) -> None:

        if isinstance(value, dict):

            object_id = id(value)

            if object_id in viste_id:
                return

            viste_id.add(object_id)

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
                    or identifier.get(
                        "code"
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


def codigo_gia_presente(
    valori: list[str],
    codice: str,
) -> bool:
    """Controlla se un codice IATA è già presente."""

    return codice in valori


def valor_normalizzato(
    valore: str,
) -> str:
    """Normalizza un valore testuale per i confronti."""

    return re.sub(
        r"\s+",
        " ",
        valore.upper(),
    )


def destinazione_ha_connection(
    testo: str,
) -> bool:
    """Verifica se Volotea indica la destinazione come connessione."""

    if not testo:
        return False

    normalizzato = valor_normalizzato(
        testo
    )

    # Volotea nel selettore mostra esplicitamente
    # "Connection" per le destinazioni non dirette.
    return bool(
        re.search(
            r"\bCONNECTION\b",
            normalizzato,
        )
    )


def mese_atteso_testi(data_partenza: date) -> list[str]:
    """Restituisce le possibili intestazioni mese/anno attese (EN + IT)."""

    nomi = NOMI_MESE.get(data_partenza.month, ())

    return [
        f"{nome} {data_partenza.year}".lower()
        for nome in nomi
    ]


# ============================================================
# SCANNER VOLOTEA
# ============================================================

class VoloteaScanner(BaseScanner):

    nome = "volotea"
    compagnia = "Volotea"

    def __init__(self):
        super().__init__(
            connector=None
        )

    # ========================================================
    # CONFIGURAZIONE DATE
    # ========================================================

    def giorni_minimi(self) -> int:
        """Restituisce il minimo soggiorno configurato."""

        possibili_nomi = (
            "giorni_minimi",
            "giorni_minimi_soggiorno",
            "min_giorni",
            "min_days",
            "soggiorno_minimo",
        )

        for nome in possibili_nomi:

            valore = getattr(
                settings,
                nome,
                None,
            )

            if valore is None:
                continue

            try:
                valore = int(valore)

                if valore >= 0:
                    return valore

            except (
                TypeError,
                ValueError,
            ):
                continue

        return DEFAULT_DAYS_MIN

    def giorni_massimi(self) -> int:
        """Restituisce il massimo soggiorno configurato."""

        possibili_nomi = (
            "giorni_massimi",
            "giorni_massimi_soggiorno",
            "max_giorni",
            "max_days",
            "soggiorno_massimo",
        )

        minimo = self.giorni_minimi()

        for nome in possibili_nomi:

            valore = getattr(
                settings,
                nome,
                None,
            )

            if valore is None:
                continue

            try:
                valore = int(valore)

                if valore >= minimo:
                    return valore

            except (
                TypeError,
                ValueError,
            ):
                continue

        return max(
            DEFAULT_DAYS_MAX,
            minimo,
        )

    def data_inizio(self) -> date:
        """Prima data utile per la ricerca."""

        possibili_nomi = (
            "giorni_anticipo_minimi",
            "anticipo_minimo",
            "min_days_ahead",
            "giorni_minimi_anticipo",
        )

        for nome in possibili_nomi:

            valore = getattr(
                settings,
                nome,
                None,
            )

            if valore is None:
                continue

            try:

                valore = int(valore)

                if valore >= 0:
                    return (
                        date.today()
                        + timedelta(
                            days=valore
                        )
                    )

            except (
                TypeError,
                ValueError,
            ):
                continue

        return (
            date.today()
            + timedelta(
                days=1
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
            "button:has-text('Aceptar solo las esenciales')",
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
    # MODALITA' SOLO ANDATA (best-effort)
    # ========================================================

    def seleziona_solo_andata(
        self,
        page: Page,
    ) -> None:
        """Tenta di impostare la ricerca in modalità solo andata.

        Se Volotea è di default in modalità andata/ritorno, la mancanza
        di una data di ritorno potrebbe impedire il submit della ricerca
        (pulsante disabilitato, validazione bloccante, ecc.).

        Questo tentativo è puramente difensivo: se non trova alcun
        controllo compatibile non fa nulla e il flusso prosegue
        normalmente come prima.
        """

        selettori = [
            "text=/^\\s*One\\s*way\\s*$/i",
            "text=/^\\s*Solo\\s*andata\\s*$/i",
            "text=/^\\s*S[oó]lo\\s*ida\\s*$/i",
            "[data-testid*='oneway' i]:visible",
            "[data-testid*='one-way' i]:visible",
            "input[value='oneway' i]",
            "input[value='one_way' i]",
            "label:has-text('One way'):visible",
            "label:has-text('Solo andata'):visible",
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

                    elemento.click(
                        force=True,
                        timeout=3000,
                    )

                    page.wait_for_timeout(
                        500
                    )

                    print(
                        "[volotea] modalità 'solo andata' impostata "
                        "tramite selettore:",
                        selettore,
                    )

                    return

            except Exception:
                continue

        print(
            "[volotea] nessun controllo 'solo andata' trovato "
            "(potrebbe non essere necessario o non presente)."
        )

    # ========================================================
    # SELETTORE AEROPORTI
    # ========================================================

    def apri_selettore_aeroporti(
        self,
        page: Page,
    ) -> bool:
        """Apre il selettore aeroporti Volotea."""

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
                        1000
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

    def ottieni_testo_elemento(
        self,
        elemento,
    ) -> str:
        """Restituisce il testo visibile di un elemento."""

        try:
            return (
                elemento.inner_text()
                .strip()
            )
        except Exception:
            return ""

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
                AIRPORT_WAIT_MS
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

                    testo = self.ottieni_testo_elemento(
                        elemento
                    )

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

                    contiene_codice = bool(
                        re.search(
                            rf"\b{re.escape(codice)}\b",
                            testo.upper(),
                        )
                    )

                    if not (
                        match_esatto
                        or (
                            contiene_codice
                            and len(testo) < 250
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
                        800
                    )

                    return True

            except Exception:
                continue

        print(
            f"[volotea] aeroporto {codice} non selezionato."
        )

        return False

    # ========================================================
    # SCOPERTA ROTTE
    # ========================================================

    def scopri_destinazioni(
        self,
        page: Page,
        origine: str,
    ) -> list[str]:
        """Scopre solamente le destinazioni dirette realmente disponibili."""

        print(
            f"[volotea] ricerca destinazioni attive da {origine}"
        )

        if not self.apri_selettore_aeroporti(
            page
        ):
            print(
                f"[volotea] impossibile aprire selettore per {origine}"
            )
            return []

        if not self.seleziona_aeroporto(
            page,
            "origin",
            origine,
        ):
            print(
                f"[volotea] {origine}: aeroporto non disponibile su Volotea."
            )
            return []

        page.wait_for_timeout(
            1000
        )

        destination = page.locator(
            "#destination:visible"
        ).first

        if destination.count() == 0:

            print(
                "[volotea] campo destination non trovato."
            )

            return []

        try:

            destination.click(
                force=True,
                timeout=5000,
            )

            destination.fill(
                "",
                timeout=5000,
            )

            page.wait_for_timeout(
                AIRPORT_WAIT_MS
            )

        except Exception as exc:

            print(
                "[volotea] errore apertura destinazioni:",
                repr(exc),
            )

            return []

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

                    testo = self.ottieni_testo_elemento(
                        elemento
                    )

                    if not testo:
                        continue

                    codice = estrai_primo_iata(
                        testo
                    )

                    if not codice:
                        continue

                    if codice == origine:
                        continue

                    # ==================================================
                    # IMPORTANTE:
                    # Volotea mostra anche destinazioni raggiungibili
                    # con una connessione.
                    #
                    # Esempio:
                    # BOD ... From €149 ... Connection
                    #
                    # Queste NON sono rotte dirette e quindi non devono
                    # essere sottoposte allo scanner.
                    # ==================================================

                    if destinazione_ha_connection(
                        testo
                    ):
                        print(
                            "[volotea] destinazione esclusa "
                            "(Connection):",
                            repr(testo),
                        )
                        continue

                    if codigo_gia_presente(
                        destinazioni,
                        codice,
                    ):
                        continue

                    print(
                        "[volotea] destinazione attiva:",
                        repr(testo),
                    )

                    destinazioni.append(
                        codice
                    )

                    if (
                        len(destinazioni)
                        >= MAX_DESTINATIONS_PER_ORIGIN
                    ):
                        break

                if (
                    len(destinazioni)
                    >= MAX_DESTINATIONS_PER_ORIGIN
                ):
                    break

            except Exception:
                continue

        print(
            f"[volotea] {origine}: "
            f"{len(destinazioni)} destinazioni attive trovate"
        )

        return destinazioni

    # ========================================================
    # DATE
    # ========================================================

    def trova_campo_data(
        self,
        page: Page,
    ):
        """Trova il campo data di partenza visibile."""

        selettori = [
            "#departure:visible",
            "input[name='departure']:visible",
            "input[placeholder*='departure' i]:visible",
            "input[placeholder*='date' i]:visible",
        ]

        for selettore in selettori:

            try:

                loc = page.locator(
                    selettore
                ).first

                if (
                    loc.count() > 0
                    and loc.is_visible()
                ):
                    return loc

            except Exception:
                continue

        return None

    def leggi_valore_campo_data(
        self,
        page: Page,
    ) -> str:
        """Legge il valore/testo attualmente mostrato nel campo data.

        Usato solo a scopo diagnostico dopo una selezione, per
        confermare nel log cosa è realmente impostato nel form.
        """

        campo = self.trova_campo_data(
            page
        )

        if campo is None:
            return ""

        valore = ""

        try:
            valore = campo.input_value(
                timeout=2000
            )
        except Exception:
            pass

        if not valore:

            try:
                valore = (
                    campo.get_attribute(
                        "value"
                    )
                    or ""
                )
            except Exception:
                pass

        if not valore:

            try:
                valore = self.ottieni_testo_elemento(
                    campo
                )
            except Exception:
                pass

        return valore

    def _intestazioni_mese_visibili(
        self,
        page: Page,
    ) -> list[dict]:
        """Individua le intestazioni mese/anno visibili nel calendario.

        Best-effort: usato per capire a quale blocco/mese appartiene
        una cella-giorno, quando il calendario mostra più mesi
        contemporaneamente (pattern comune nei date-picker A/R).
        """

        risultati: list[dict] = []

        try:

            elementi = page.get_by_text(
                PATTERN_INTESTAZIONE_MESE
            )

            count = elementi.count()

            for i in range(count):

                elemento = elementi.nth(i)

                if not elemento.is_visible():
                    continue

                try:
                    box = elemento.bounding_box()
                except Exception:
                    box = None

                if not box:
                    continue

                testo = self.ottieni_testo_elemento(
                    elemento
                )

                if not testo:
                    continue

                risultati.append(
                    {
                        "testo": testo.strip().lower(),
                        "top": box["y"],
                    }
                )

        except Exception:
            pass

        risultati.sort(
            key=lambda h: h["top"]
        )

        return risultati

    def seleziona_data(
        self,
        page: Page,
        data_partenza: date,
    ) -> bool:
        """Seleziona una data evitando il semplice match del giorno."""

        departure = self.trova_campo_data(
            page
        )

        if departure is None:

            print(
                "[volotea] campo departure non trovato."
            )

            return False

        print(
            "[volotea] selezione data:",
            data_partenza.isoformat(),
        )

        try:

            departure.click(
                force=True,
                timeout=5000,
            )

            page.wait_for_timeout(
                DATE_WAIT_MS
            )

        except Exception as exc:

            print(
                "[volotea] errore apertura calendario:",
                repr(exc),
            )

            return False

        giorno = str(
            data_partenza.day
        )

        mese = str(
            data_partenza.month
        )

        anno = str(
            data_partenza.year
        )

        # ====================================================
        # ATTRIBUTI PRECISI
        # ====================================================

        selettori_precisi = [
            f"[data-date='{data_partenza.isoformat()}']:visible",
            f"[data-value='{data_partenza.isoformat()}']:visible",
            f"[aria-label*='{data_partenza.isoformat()}' i]:visible",
        ]

        for selettore in selettori_precisi:

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

                    valore_letto = self.leggi_valore_campo_data(
                        page
                    )

                    print(
                        "[volotea] valore campo data dopo la "
                        "selezione (attributo preciso):",
                        repr(valore_letto),
                    )

                    print(
                        "[volotea] data selezionata tramite attributo preciso:",
                        data_partenza.isoformat(),
                    )

                    return True

            except Exception:
                continue

        # ====================================================
        # ANALISI CALENDARIO
        # ====================================================

        elementi_calendario = page.locator(
            "button:visible, "
            "[role='button']:visible, "
            "[role='gridcell']:visible"
        )

        try:

            count = elementi_calendario.count()

            for i in range(count):

                elemento = elementi_calendario.nth(i)

                if not elemento.is_visible():
                    continue

                testo = self.ottieni_testo_elemento(
                    elemento
                )

                aria = ""

                try:
                    aria = (
                        elemento.get_attribute(
                            "aria-label"
                        )
                        or ""
                    )

                except Exception:
                    pass

                valore = (
                    f"{testo} {aria}"
                ).strip()

                if not valore:
                    continue

                valore_upper = valor_normalizzato(
                    valore
                )

                if (
                    data_partenza.isoformat()
                    in valore
                ):

                    elemento.click(
                        force=True,
                        timeout=5000,
                    )

                    page.wait_for_timeout(
                        800
                    )

                    valore_letto = self.leggi_valore_campo_data(
                        page
                    )

                    print(
                        "[volotea] valore campo data dopo la "
                        "selezione (analisi calendario, ISO):",
                        repr(valore_letto),
                    )

                    print(
                        "[volotea] data selezionata:",
                        data_partenza.isoformat(),
                    )

                    return True

                if (
                    giorno in valore_upper
                    and mese in valore_upper
                    and anno in valore_upper
                ):

                    elemento.click(
                        force=True,
                        timeout=5000,
                    )

                    page.wait_for_timeout(
                        800
                    )

                    valore_letto = self.leggi_valore_campo_data(
                        page
                    )

                    print(
                        "[volotea] valore campo data dopo la "
                        "selezione (analisi calendario, gg/mm/aaaa):",
                        repr(valore_letto),
                    )

                    print(
                        "[volotea] data selezionata:",
                        data_partenza.isoformat(),
                    )

                    return True

        except Exception as exc:

            print(
                "[volotea] errore scansione calendario:",
                repr(exc),
            )

        # ====================================================
        # FALLBACK (con disambiguazione del mese)
        # ====================================================

        try:

            testo_calendario = page.locator(
                "body"
            ).inner_text()

            mese_anno_presenti = (
                mese in testo_calendario
                or
                data_partenza.strftime(
                    "%B"
                ).lower()
                in testo_calendario.lower()
            )

            if mese_anno_presenti:

                elementi = page.locator(
                    "button:visible, "
                    "[role='button']:visible, "
                    "[role='gridcell']:visible"
                )

                intestazioni = self._intestazioni_mese_visibili(
                    page
                )

                testi_mese_atteso = mese_atteso_testi(
                    data_partenza
                )

                candidati_validi = []

                occorrenze_giorno = 0

                for i in range(
                    elementi.count()
                ):

                    elemento = elementi.nth(i)

                    if not elemento.is_visible():
                        continue

                    try:

                        disabilitato = (
                            elemento.get_attribute(
                                "aria-disabled"
                            )
                            == "true"
                            or elemento.get_attribute(
                                "disabled"
                            )
                            is not None
                        )

                    except Exception:
                        disabilitato = False

                    if disabilitato:
                        continue

                    testo = (
                        self.ottieni_testo_elemento(
                            elemento
                        ).strip()
                    )

                    if testo != giorno:
                        continue

                    occorrenze_giorno += 1

                    mese_confermato = False

                    if intestazioni:

                        try:
                            box = elemento.bounding_box()
                        except Exception:
                            box = None

                        if box:

                            header_corrente = None

                            for intestazione in intestazioni:

                                if (
                                    intestazione["top"]
                                    <= box["y"]
                                ):
                                    header_corrente = intestazione
                                else:
                                    break

                            if (
                                header_corrente
                                and header_corrente["testo"]
                                in testi_mese_atteso
                            ):
                                mese_confermato = True

                    else:

                        # Nessuna intestazione trovata: non possiamo
                        # verificare il mese. Se questa è l'unica
                        # cella con questo numero di giorno, la
                        # accettiamo comunque; se ce ne sono più di
                        # una restiamo prudenti (vedi sotto).
                        mese_confermato = True

                    if mese_confermato:
                        candidati_validi.append(
                            elemento
                        )

                if occorrenze_giorno > 1:

                    print(
                        f"[volotea] {occorrenze_giorno} celle con "
                        f"giorno '{giorno}' trovate nel calendario; "
                        f"{len(candidati_validi)} confermate nel mese "
                        "corretto."
                    )

                if (
                    not intestazioni
                    and occorrenze_giorno > 1
                ):

                    # Ambiguità reale e non risolvibile: meglio
                    # fallire esplicitamente che rischiare la data
                    # sbagliata.
                    print(
                        "[volotea] ATTENZIONE: giorno ambiguo "
                        "(più celle, nessuna intestazione mese "
                        "trovata per disambiguare) - selezione "
                        "annullata."
                    )

                    candidati_validi = []

                if candidati_validi:

                    elemento_da_cliccare = candidati_validi[0]

                    elemento_da_cliccare.click(
                        force=True,
                        timeout=5000,
                    )

                    page.wait_for_timeout(
                        800
                    )

                    valore_letto = self.leggi_valore_campo_data(
                        page
                    )

                    print(
                        "[volotea] valore campo data dopo la "
                        "selezione (fallback):",
                        repr(valore_letto),
                    )

                    print(
                        "[volotea] data selezionata tramite fallback:",
                        data_partenza.isoformat(),
                    )

                    return True

        except Exception as exc:

            print(
                "[volotea] errore selezione fallback:",
                repr(exc),
            )

        print(
            "[volotea] data NON selezionata:",
            data_partenza.isoformat(),
        )

        return False

    # ========================================================
    # RICERCA
    # ========================================================

    def trova_pulsante_ricerca(
        self,
        page: Page,
    ):
        """Trova il pulsante di ricerca.

        Privilegia i veri pulsanti type="submit" ed esclude
        esplicitamente elementi dentro <header>/<nav>, per evitare
        di intercettare un CTA generico della pagina invece del
        vero pulsante del widget di ricerca voli.
        """

        def fuori_dal_widget(elemento) -> bool:

            try:
                return bool(
                    elemento.evaluate(
                        "el => !!el.closest('header, nav')"
                    )
                )
            except Exception:
                return False

        # 1) Pulsanti submit reali (i più affidabili)
        try:

            submits = page.locator(
                "button[type='submit']:visible, "
                "input[type='submit']:visible"
            )

            for i in range(
                submits.count()
            ):

                elemento = submits.nth(i)

                if not elemento.is_visible():
                    continue

                if fuori_dal_widget(
                    elemento
                ):
                    continue

                print(
                    "[volotea] pulsante ricerca (type=submit) trovato."
                )

                return elemento

        except Exception:
            pass

        # 2) Pulsanti testuali, escludendo header/nav
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

                testo = self.ottieni_testo_elemento(
                    button
                )

                if not pattern.search(testo):
                    continue

                if fuori_dal_widget(
                    button
                ):
                    print(
                        "[volotea] bottone escluso "
                        "(dentro header/nav):",
                        repr(testo),
                    )
                    continue

                print(
                    "[volotea] pulsante ricerca (testo) trovato:",
                    repr(testo),
                )

                return button

        except Exception:
            pass

        # 3) Fallback finale (comportamento originale)
        try:

            elementi = page.get_by_text(
                pattern
            )

            for i in range(
                elementi.count()
            ):

                elemento = elementi.nth(i)

                if elemento.is_visible():

                    print(
                        "[volotea] pulsante ricerca "
                        "(fallback get_by_text) trovato."
                    )

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

    def esegui_ricerca(
        self,
        page: Page,
        origine: str,
        destinazione: str,
        data_partenza: date,
    ) -> list[dict[str, Any]]:
        """Esegue una singola ricerca reale Volotea."""

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
            PAGE_LOAD_WAIT_MS
        )

        self.chiudi_cookie(
            page
        )

        self.seleziona_solo_andata(
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

            print(
                f"[volotea] data non selezionata: "
                f"{data_partenza.isoformat()}"
            )

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

        url_prima_del_click = page.url

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
            1500
        )

        print(
            "[volotea] URL dopo il click sul pulsante ricerca:",
            page.url,
        )

        if page.url == url_prima_del_click:

            print(
                "[volotea] ATTENZIONE: l'URL non è cambiato dopo "
                "il click sul pulsante ricerca (possibile pulsante "
                "errato o submit non avvenuto)."
            )

        page.wait_for_timeout(
            max(
                SEARCH_WAIT_MS - 1500,
                0,
            )
        )

        if not risposta_json:

            page.wait_for_timeout(
                SEARCH_WAIT_MS
            )

        if not risposta_json:

            print(
                f"[volotea] nessuna risposta di ricerca intercettata "
                f"per {origine} -> {destinazione} "
                f"(nessuna chiamata verso "
                f"{' o '.join(SEARCH_PATHS)})."
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

            if (
                len(risultati)
                >= MAX_FLIGHTS_PER_SEARCH
            ):
                break

        return risultati

    # ========================================================
    # SCAN
    # ========================================================

    def scan(
        self,
    ) -> list[Offerta]:
        """Esegue la scansione Volotea."""

        print("")
        print("=" * 60)
        print(
            "FLIGHT HUNTER - SCANNER VOLOTEA"
        )
        print("=" * 60)

        offerte: list[Offerta] = []

        data_inizio = self.data_inizio()

        giorni_minimi = self.giorni_minimi()
        giorni_massimi = self.giorni_massimi()

        print(
            "[volotea] data iniziale:",
            data_inizio.isoformat(),
        )

        print(
            "[volotea] soggiorno minimo:",
            giorni_minimi,
            "giorni",
        )

        print(
            "[volotea] soggiorno massimo:",
            giorni_massimi,
            "giorni",
        )

        # ====================================================
        # AEROPORTI DI PARTENZA
        # ====================================================

        origini: list[str] = []

        for origine in self.origini:

            codice = str(
                origine
            ).strip().upper()

            if not re.fullmatch(
                r"[A-Z]{3}",
                codice,
            ):
                continue

            if codice in origini:
                continue

            origini.append(
                codice
            )

        print(
            "[volotea] aeroporti di partenza configurati:",
            ", ".join(origini)
            if origini
            else "nessuno",
        )

        if not origini:

            print(
                "[volotea] nessun aeroporto di partenza configurato."
            )

            return []

        browser: Browser | None = None
        context: BrowserContext | None = None

        with sync_playwright() as p:

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

                # ============================================
                # 1. DISCOVERY DELLE ROTTE
                # ============================================

                rotte: dict[str, list[str]] = {}

                for origine in origini:

                    print("")
                    print(
                        f"[volotea] discovery rotte da {origine}"
                    )

                    page = context.new_page()

                    try:

                        page.goto(
                            BOOKING_URL,
                            wait_until="domcontentloaded",
                            timeout=60000,
                        )

                        page.wait_for_timeout(
                            PAGE_LOAD_WAIT_MS
                        )

                        self.chiudi_cookie(
                            page
                        )

                        destinazioni = (
                            self.scopri_destinazioni(
                                page,
                                origine,
                            )
                        )

                        rotte[origine] = (
                            destinazioni
                        )

                    except Exception as exc:

                        print(
                            f"[volotea] errore discovery "
                            f"rotte da {origine}:",
                            repr(exc),
                        )

                        rotte[origine] = []

                    finally:

                        try:
                            page.close()

                        except Exception:
                            pass

                # ============================================
                # RIEPILOGO
                # ============================================

                print("")
                print(
                    "[volotea] riepilogo rotte selezionate:"
                )

                totale_rotte = 0

                for origine, destinazioni in rotte.items():

                    print(
                        f"[volotea] {origine}: "
                        f"{len(destinazioni)} destinazioni"
                    )

                    totale_rotte += len(
                        destinazioni
                    )

                print(
                    "[volotea] totale rotte dirette da scannerizzare:",
                    totale_rotte,
                )

                # ============================================
                # 2. RICERCA VOLI
                # ============================================

                for origine, destinazioni in rotte.items():

                    # Se Volotea non ha riconosciuto l'aeroporto
                    # o non ha restituito rotte, NON viene eseguita
                    # nessuna ricerca.
                    if not destinazioni:

                        print(
                            f"[volotea] nessuna rotta disponibile "
                            f"da {origine}: aeroporto saltato."
                        )

                        continue

                    for destinazione in destinazioni:

                        if origine == destinazione:
                            continue

                        print("")
                        print(
                            f"[volotea] rotta attiva "
                            f"{origine} -> {destinazione}"
                        )

                        data_partenza = data_inizio

                        page = context.new_page()

                        try:

                            voli = self.esegui_ricerca(
                                page,
                                origine,
                                destinazione,
                                data_partenza,
                            )

                            viste = set()

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

                            print(
                                f"[volotea] {origine} -> "
                                f"{destinazione}: "
                                f"{len(viste)} voli trovati"
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

        print("")
        print(
            "VOLOTEA COMPLETATO"
        )

        print(
            "Offerte prodotte:",
            len(offerte),
        )

        return offerte
