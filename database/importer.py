import requests

from config.settings import (
    FLIGHT_HUNTER_API_URL,
    FLIGHT_HUNTER_API_TOKEN,
    FLIGHT_HUNTER_CONNECTOR,
    MAX_OFFERS_PER_REQUEST,
    REQUEST_TIMEOUT,
)

ALLOWED_FONTE_DATO = {"reale", "api", "import", "diretta", "scanner"}


def _normalize(offer: dict) -> dict:
    """Riduce l'offerta ai soli campi accettati dal backend Flight Hunter."""
    fonte = offer.get("fonte_dato", "diretta")
    if fonte not in ALLOWED_FONTE_DATO:
        raise ValueError(f"fonte_dato non valido: {fonte}")

    return {
        "aeroporto_partenza": str(offer["aeroporto_partenza"]).upper(),
        "destinazione": str(offer["destinazione"]),
        "compagnia": str(offer["compagnia"]),
        "prezzo": float(offer["prezzo"]),
        "valuta": str(offer.get("valuta") or "EUR").upper(),
        "data_partenza": str(offer["data_partenza"]),
        "data_ritorno": offer.get("data_ritorno") or None,
        "link_prenotazione": offer.get("link_prenotazione") or None,
        "fonte_dato": fonte,
        "opportunity_score": offer.get("opportunity_score"),
    }


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def import_offers(offers, connettore: str | None = None) -> dict:
    """Invia le offerte trovate a Flight Hunter tramite l'endpoint pubblico."""
    if not FLIGHT_HUNTER_API_URL:
        raise RuntimeError("URL Flight Hunter mancante")
    if not FLIGHT_HUNTER_API_TOKEN:
        raise RuntimeError("Token Flight Hunter mancante (FH_ACCESS_TOKEN)")

    payload_offers = [_normalize(o) for o in offers]
    if not payload_offers:
        return {"ok": True, "importate": 0}

    headers = {
        "Authorization": f"Bearer {FLIGHT_HUNTER_API_TOKEN}",
        "Content-Type": "application/json",
    }

    totale = 0
    for blocco in _chunks(payload_offers, MAX_OFFERS_PER_REQUEST):
        body = {
            "connettore": connettore or FLIGHT_HUNTER_CONNECTOR,
            "offerte": blocco,
        }
        response = requests.post(
            FLIGHT_HUNTER_API_URL,
            json=body,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        if not response.ok:
            raise RuntimeError(
                f"Import fallito [{response.status_code}]: {response.text}"
            )
        totale += int(response.json().get("importate") or 0)

    return {"ok": True, "importate": totale}

