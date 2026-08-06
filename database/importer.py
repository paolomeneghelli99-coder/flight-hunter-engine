import requests

from config.settings import (
    FLIGHT_HUNTER_API_URL,
    FLIGHT_HUNTER_API_TOKEN
)


def import_offers(offers):
    """
    Invia le offerte trovate al database Flight Hunter.
    """

    if not FLIGHT_HUNTER_API_URL:
        raise Exception("URL Flight Hunter mancante")

    headers = {
        "Authorization": f"Bearer {FLIGHT_HUNTER_API_TOKEN}",
        "Content-Type": "application/json"
    }

    response = requests.post(
        FLIGHT_HUNTER_API_URL,
        json=offers,
        headers=headers
    )

    response.raise_for_status()

    return response.json()
