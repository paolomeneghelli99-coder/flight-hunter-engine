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

    dati = risposta.json()

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
            f"Inviate {len(blocco)} offerte -> "
            f"importate {importate}"
        )

        totale += importate

    return totale
