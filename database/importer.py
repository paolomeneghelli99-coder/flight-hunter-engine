"""Invio delle offerte a Flight Hunter (POST /api/public/offers/import)."""

import json
import sys

import requests

from config.settings import settings


MAX_PER_RICHIESTA = 500


def _blocchi(elementi, dimensione):
    """
    Divide una lista in blocchi di dimensione massima indicata.
    """
    for i in range(0, len(elementi), dimensione):
        yield elementi[i:i + dimensione]


def _prepara_offerta(offerta: dict) -> dict:
    """
    Prepara il payload di una singola offerta.

    Manteniamo TUTTI i campi già prodotti dagli scanner
    e aggiungiamo alcuni alias compatibili con il backend.

    Non modifica l'oggetto originale.
    """

    risultato = dict(offerta)

    # --------------------------------------------------
    # NORMALIZZAZIONE TRATTA
    # --------------------------------------------------

    aeroporto_partenza = (
        risultato.get("aeroporto_partenza")
        or risultato.get("partenza")
        or risultato.get("origine")
        or ""
    )

    aeroporto_arrivo = (
        risultato.get("aeroporto_arrivo")
        or risultato.get("arrivo")
        or risultato.get("destinazione_aeroporto")
        or ""
    )

    # --------------------------------------------------
    # NORMALIZZAZIONE DATA
    # --------------------------------------------------

    data_partenza = (
        risultato.get("data_partenza")
        or risultato.get("data")
        or ""
    )

    # --------------------------------------------------
    # CAMPI PRINCIPALI
    # --------------------------------------------------

    if aeroporto_partenza:
        risultato["aeroporto_partenza"] = (
            str(aeroporto_partenza).upper()
        )

    if aeroporto_arrivo:
        risultato["aeroporto_arrivo"] = (
            str(aeroporto_arrivo).upper()
        )

    if data_partenza:
        risultato["data_partenza"] = str(
            data_partenza
        )

    # --------------------------------------------------
    # ALIAS DI COMPATIBILITÀ BACKEND
    # --------------------------------------------------

    if aeroporto_partenza:
        risultato.setdefault(
            "partenza",
            aeroporto_partenza
        )

        risultato.setdefault(
            "origine",
            aeroporto_partenza
        )

    if aeroporto_arrivo:
        risultato.setdefault(
            "arrivo",
            aeroporto_arrivo
        )

        risultato.setdefault(
            "destinazione_aeroporto",
            aeroporto_arrivo
        )

    if data_partenza:
        risultato.setdefault(
            "data",
            data_partenza
        )

    # --------------------------------------------------
    # TRATTA TESTUALE
    # --------------------------------------------------

    if aeroporto_partenza and aeroporto_arrivo:

        risultato.setdefault(
            "tratta",
            f"{str(aeroporto_partenza).upper()}-"
            f"{str(aeroporto_arrivo).upper()}"
        )

    # --------------------------------------------------
    # DESTINAZIONE
    #
    # NON la sovrascriviamo:
    # il campo destinazione prodotto da Ryanair
    # contiene il nome della città.
    # --------------------------------------------------

    # --------------------------------------------------
    # PREZZO
    # --------------------------------------------------

    if risultato.get("prezzo") is not None:

        try:
            risultato["prezzo"] = round(
                float(risultato["prezzo"]),
                2
            )

        except (TypeError, ValueError):
            pass

    # --------------------------------------------------
    # VALUTA
    # --------------------------------------------------

    if risultato.get("valuta"):

        risultato["valuta"] = str(
            risultato["valuta"]
        ).upper()[:3]

    # --------------------------------------------------
    # DEBUG DATI PRINCIPALI
    # --------------------------------------------------

    return risultato


def _invia(blocco: list, debug=False) -> int:
    """
    Invia un blocco di offerte al backend.

    Restituisce il numero di offerte importate.
    """

    offerte_preparate = [
        _prepara_offerta(offerta)
        for offerta in blocco
    ]

    payload = {
        "connettore": settings.connettore,
        "offerte": offerte_preparate,
    }

    # --------------------------------------------------
    # DEBUG DEL PRIMO BLOCCO
    # --------------------------------------------------

    if debug and offerte_preparate:

        print("")
        print(
            "=================================================="
        )
        print(
            "DEBUG PRIMA OFFERTA INVIATA AL BACKEND"
        )
        print(
            "=================================================="
        )

        print(
            json.dumps(
                offerte_preparate[0],
                ensure_ascii=False,
                indent=2
            )
        )

        print(
            "=================================================="
        )
        print("")

    # --------------------------------------------------
    # CONTROLLO CONFIGURAZIONE
    # --------------------------------------------------

    if not settings.import_url:

        print(
            "ERRORE: FH_IMPORT_URL non configurato.",
            file=sys.stderr
        )

        return 0

    if not settings.access_token:

        print(
            "ERRORE: FH_ACCESS_TOKEN non configurato.",
            file=sys.stderr
        )

        return 0

    # --------------------------------------------------
    # INVIO HTTP
    # --------------------------------------------------

    try:

        risposta = requests.post(

            settings.import_url,

            headers={
                "Authorization":
                    f"Bearer {settings.access_token}",

                "Content-Type":
                    "application/json",
            },

            data=json.dumps(
                payload,
                ensure_ascii=False
            ),

            timeout=settings.timeout,
        )

    except requests.RequestException as exc:

        print(
            f"Errore HTTP durante importazione: {exc}",
            file=sys.stderr
        )

        return 0

    # --------------------------------------------------
    # DEBUG RISPOSTA
    # --------------------------------------------------

    print(
        f"HTTP status: {risposta.status_code}"
    )

    print(
        f"URL: {settings.import_url}"
    )

    # --------------------------------------------------
    # TOKEN NON VALIDO
    # --------------------------------------------------

    if risposta.status_code == 401:

        raise SystemExit(
            "Token non valido o scaduto (401): "
            "verifica l'autenticazione del backend."
        )

    # --------------------------------------------------
    # RISPOSTA TESTUALE
    # --------------------------------------------------

    try:

        dati = risposta.json()

    except ValueError:

        print(
            "Risposta backend non JSON:",
            file=sys.stderr
        )

        print(
            risposta.text,
            file=sys.stderr
        )

        return 0

    # --------------------------------------------------
    # STAMPA RISPOSTA BACKEND
    # --------------------------------------------------

    print(
        "Risposta backend:"
    )

    print(
        json.dumps(
            dati,
            ensure_ascii=False,
            indent=2
        )
    )

    # --------------------------------------------------
    # ERRORI HTTP
    # --------------------------------------------------

    if risposta.status_code == 400:

        print(
            "Payload rifiutato dal backend (400).",
            file=sys.stderr
        )

        return 0

    if risposta.status_code >= 400:

        print(
            f"Errore HTTP {risposta.status_code}.",
            file=sys.stderr
        )

        return 0

    # --------------------------------------------------
    # NUMERO OFFERTE IMPORTATE
    # --------------------------------------------------

    importate = (
        dati.get("importate")
        if isinstance(dati, dict)
        else None
    )

    # Il backend attuale sembra usare "imported".
    if importate is None:

        importate = (
            dati.get("imported")
            if isinstance(dati, dict)
            else None
        )

    # --------------------------------------------------
    # NUMERO RITORNI IMPORTATI
    # --------------------------------------------------

    ritorni_importati = 0

    if isinstance(dati, dict):

        ritorni_importati = (
            dati.get("returns_imported")
            or dati.get("ritorni_importati")
            or 0
        )

    # --------------------------------------------------
    # OUTPUT DIAGNOSTICO
    # --------------------------------------------------

    try:
        importate_int = int(
            importate or 0
        )

    except (TypeError, ValueError):

        importate_int = 0

    try:
        ritorni_int = int(
            ritorni_importati or 0
        )

    except (TypeError, ValueError):

        ritorni_int = 0

    print(
        f"Offerte importate dichiarate dal backend: "
        f"{importate_int}"
    )

    print(
        f"Ritorni importati dichiarati dal backend: "
        f"{ritorni_int}"
    )

    # --------------------------------------------------
    # ERRORI LOGICI DEL BACKEND
    # --------------------------------------------------

    errori = (
        dati.get("errors", [])
        if isinstance(dati, dict)
        else []
    )

    if errori:

        print("")
        print(
            "Backend ha segnalato "
            f"{len(errori)} errore/i."
        )

        # Mostriamo tutti gli errori se sono pochi,
        # altrimenti solo i primi 20 per non rendere
        # il log di GitHub Actions inutilizzabile.

        limite_errori = 20

        for errore in errori[:limite_errori]:

            print(
                f"  - {errore}"
            )

        if len(errori) > limite_errori:

            print(
                f"  ... altri "
                f"{len(errori) - limite_errori} errori."
            )

    return importate_int


def import_offers(offerte: list) -> int:
    """
    Importa tutte le offerte nel backend.

    Le offerte vengono suddivise in blocchi per evitare
    richieste HTTP eccessivamente grandi.
    """

    if not offerte:

        print(
            "Nessuna offerta da importare."
        )

        return 0

    # --------------------------------------------------
    # DIMENSIONE BLOCCO
    # --------------------------------------------------

    dimensione = min(
        settings.batch_size,
        MAX_PER_RICHIESTA,
    )

    # Sicurezza: impedisce un batch nullo o negativo.

    if dimensione <= 0:

        dimensione = MAX_PER_RICHIESTA

    # --------------------------------------------------
    # IMPORTAZIONE
    # --------------------------------------------------

    totale = 0

    primo_blocco = True

    for blocco in _blocchi(
        offerte,
        dimensione
    ):

        importate = _invia(
            blocco,
            debug=primo_blocco
        )

        primo_blocco = False

        print(
            f"Inviate {len(blocco)} offerte -> "
            f"importate {importate}"
        )

        totale += importate

    # --------------------------------------------------
    # RISULTATO FINALE
    # --------------------------------------------------

    print("")
    print(
        "=================================================="
    )

    print(
        f"Totale offerte importate: {totale}"
    )

    print(
        "=================================================="
    )

    return totale
