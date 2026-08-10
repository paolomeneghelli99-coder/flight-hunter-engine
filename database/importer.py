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

    headers = {
        "Authorization": f"Bearer {settings.access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        risposta = requests.post(
            settings.import_url,
            headers=headers,
            data=json.dumps(payload),
            timeout=settings.timeout,
        )
    except requests.RequestException as exc:
        print(
            f"Errore di connessione all'API di import: {exc}",
            file=sys.stderr,
        )
        return 0

    print(
        f"Import API HTTP status: {risposta.status_code}"
    )

    if risposta.status_code == 401:
        print(
            "IMPORT API: HTTP 401 Unauthorized",
            file=sys.stderr,
        )

        print(
            "Risposta API:",
            risposta.text,
            file=sys.stderr,
        )

        print(
            "Content-Type risposta:",
            risposta.headers.get("content-type", "MANCANTE"),
            file=sys.stderr,
        )

        print(
            "WWW-Authenticate:",
            risposta.headers.get(
                "www-authenticate",
                "MANCANTE",
            ),
            file=sys.stderr,
        )

        raise SystemExit(
            "L'API di importazione ha rifiutato il JWT con HTTP 401."
        )

    if risposta.status_code == 400:
        print(
            f"Payload rifiutato (400): {risposta.text}",
            file=sys.stderr,
        )
        return 0

    if risposta.status_code >= 400:
        print(
            f"Errore HTTP {risposta.status_code}: "
            f"{risposta.text}",
            file=sys.stderr,
        )
        return 0

    try:
        dati = risposta.json()
    except ValueError:
        print(
            "Risposta API non JSON:",
            risposta.text,
            file=sys.stderr,
        )
        return 0

    return int(dati.get("importate", 0))


def import_offers(offerte: list) -> int:
    if not offerte:
        return 0

    dimensione = min(
        settings.batch_size,
        MAX_PER_RICHIESTA,
    )

    totale = 0

    for blocco in _blocchi(offerte, dimensione):
        importate = _invia(blocco)

        print(
            f"Inviate {len(blocco)} offerte "
            f"-> importate {importate}"
        )

        totale += importate

    return totale
