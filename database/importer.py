"""Invio delle offerte a Flight Hunter (POST /api/public/offers/import)."""

import json
import sys

import requests

from config.settings import settings


MAX_PER_RICHIESTA = 500


def _blocchi(elementi: list, dimensione: int):
    """Divide una lista in blocchi senza perdere elementi."""

    if dimensione <= 0:
        raise ValueError(
            "La dimensione del blocco deve essere maggiore di zero."
        )

    for i in range(0, len(elementi), dimensione):
        yield elementi[i:i + dimensione]


def _invia(blocco: list) -> int:
    """Invia un blocco di offerte al backend."""

    payload = {
        "connettore": settings.connettore,
        "offerte": blocco,
    }

    try:

        risposta = requests.post(
            settings.import_url,
            headers={
                "Authorization": (
                    f"Bearer {settings.access_token}"
                ),
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=settings.timeout,
        )

    except requests.RequestException as exc:

        print(
            f"Errore connessione import offerte: {exc}",
            file=sys.stderr,
        )

        return 0

    # ========================================================
    # CONTROLLO HTTP
    # ========================================================

    print(
        "HTTP STATUS BACKEND:",
        risposta.status_code,
    )

    print(
        "RISPOSTA COMPLETA BACKEND:",
        risposta.text,
    )

    # ========================================================
    # AUTENTICAZIONE
    # ========================================================

    if risposta.status_code == 401:

        raise SystemExit(
            "Token non valido o scaduto (401): "
            "verifica l'autenticazione del backend."
        )

    # ========================================================
    # PAYLOAD RIFIUTATO
    # ========================================================

    if risposta.status_code == 400:

        print(
            f"Payload rifiutato (400): {risposta.text}",
            file=sys.stderr,
        )

        return 0

    # ========================================================
    # ALTRI ERRORI HTTP
    # ========================================================

    if risposta.status_code >= 400:

        print(
            f"Errore {risposta.status_code}: "
            f"{risposta.text}",
            file=sys.stderr,
        )

        return 0

    # ========================================================
    # RISPOSTA JSON
    # ========================================================

    try:

        dati = risposta.json()

    except ValueError:

        print(
            "Risposta backend non JSON:",
            risposta.text,
            file=sys.stderr,
        )

        return 0

    # ========================================================
    # NUMERO OFFERTE IMPORTATE
    # ========================================================

    try:

        importate = int(
            dati.get(
                "importate",
                0,
            )
        )

    except (
        TypeError,
        ValueError,
    ):

        print(
            "Campo 'importate' non valido nella risposta:",
            dati,
            file=sys.stderr,
        )

        return 0

    print(
        "Offerte importate dichiarate dal backend:",
        importate,
    )

    return importate


def import_offers(offerte: list) -> int:
    """
    Importa tutte le offerte prodotte dagli scanner.

    Le offerte vengono eventualmente suddivise in più richieste
    HTTP. Il limite MAX_PER_RICHIESTA riguarda esclusivamente
    la dimensione della singola richiesta e NON il numero totale
    di offerte importabili.
    """

    if not offerte:

        return 0

    # ========================================================
    # DIMENSIONE BATCH
    # ========================================================

    dimensione = min(
        settings.batch_size,
        MAX_PER_RICHIESTA,
    )

    if dimensione <= 0:

        raise ValueError(
            "settings.batch_size deve essere maggiore di zero."
        )

    totale = 0

    numero_blocco = 0

    totale_blocchi = (
        len(offerte) + dimensione - 1
    ) // dimensione

    print("")
    print(
        "IMPORTAZIONE OFFERTE"
    )
    print(
        "=" * 60
    )

    print(
        "Offerte da importare:",
        len(offerte),
    )

    print(
        "Dimensione batch:",
        dimensione,
    )

    print(
        "Numero richieste:",
        totale_blocchi,
    )

    print(
        "=" * 60
    )

    # ========================================================
    # INVIO DI TUTTI I BLOCCHI
    # ========================================================

    for blocco in _blocchi(
        offerte,
        dimensione,
    ):

        numero_blocco += 1

        importate = _invia(
            blocco
        )

        totale += importate

        print(
            f"Inviate {len(blocco)} offerte -> "
            f"importate {importate}"
        )

    # ========================================================
    # RISULTATO FINALE
    # ========================================================

    print("")
    print(
        "IMPORTAZIONE COMPLETATA"
    )
    print(
        "=" * 60
    )

    print(
        "Offerte inviate:",
        len(offerte),
    )

    print(
        "Offerte importate:",
        totale,
    )

    print(
        "Offerte non importate:",
        max(
            0,
            len(offerte) - totale,
        ),
    )

    return totale
