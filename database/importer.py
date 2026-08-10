"""Invio delle offerte a Flight Hunter (POST /api/public/offers/import)."""

import json
import sys

import requests

from config.settings import settings


MAX_PER_RICHIESTA = 500


def _blocchi(elementi, dimensione):
    for i in range(0, len(elementi), dimensione):
        yield elementi[i:i + dimensione]


def _invia(blocco: list) -> int:
    payload = {
        "connettore": settings.connettore,
        "offerte": blocco,
    }

    risposta = requests.post(
        settings.import_url,
        headers={
            "Authorization": f"Bearer {settings.access_token}",
            "Content-Type": "application/json",
        },
        data=json.dumps(payload),
        timeout=settings.timeout,
    )

    print("")
    print("========================================")
    print("RISPOSTA BACKEND IMPORT")
    print("========================================")
    print("HTTP status:", risposta.status_code)
    print("URL:", settings.import_url)

    try:
        print("Risposta backend:")
        print(
            json.dumps(
                risposta.json(),
                indent=2,
                ensure_ascii=False,
            )
        )
    except Exception:
        print("Risposta backend non JSON:")
        print(risposta.text)

    print("========================================")
    print("")

    if risposta.status_code == 401:
        raise SystemExit(
            "Token non valido o scaduto (401): "
            "verifica l'autenticazione del backend."
        )

    if risposta.status_code == 400:
        print(
            f"Payload rifiutato (400): {risposta.text}",
            file=sys.stderr,
        )
        return 0

    if risposta.status_code >= 400:
        print(
            f"Errore {risposta.status_code}: {risposta.text}",
            file=sys.stderr,
        )
        return 0

    try:
        dati = risposta.json()
    except Exception as exc:
        print(
            "ERRORE: il backend ha restituito una risposta "
            "non JSON.",
            file=sys.stderr,
        )
        print(
            f"Dettaglio: {exc}",
            file=sys.stderr,
        )
        return 0

    importate = dati.get("importate", 0)

    print(
        "Offerte importate dichiarate dal backend:",
        importate,
    )

    return int(importate)


def import_offers(offerte: list) -> int:
    if not offerte:
        return 0

    dimensione = min(
        settings.batch_size,
        MAX_PER_RICHIESTA,
    )

    totale = 0

    for blocco in _blocchi(
        offerte,
        dimensione,
    ):
        importate = _invia(blocco)

        print(
            f"Inviate {len(blocco)} offerte -> "
            f"importate {importate}"
        )

        totale += importate

    return totale
