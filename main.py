"""Flight Hunter Engine — punto di ingresso eseguito da GitHub Actions."""

import sys

from config.settings import (
    FLIGHT_HUNTER_API_TOKEN,
    FLIGHT_HUNTER_API_URL,
    FLIGHT_HUNTER_CONNECTOR,
)
from database.importer import import_offers


def raccogli_offerte() -> list[dict]:
    """Raccoglie le offerte reali dalle fonti gratuite.

    Sostituisci il corpo con la tua logica di scraping/parsing.
    Ogni elemento deve avere questi campi:

        {
            "aeroporto_partenza": "VRN",      # IATA, 3-8 caratteri
            "destinazione": "Barcellona",     # 2-80 caratteri
            "compagnia": "Ryanair",           # 2-60 caratteri
            "prezzo": 24.99,                  # float > 0 e <= 10000
            "valuta": "EUR",                  # 3 lettere
            "data_partenza": "2026-09-14",    # YYYY-MM-DD
            "data_ritorno": None,             # YYYY-MM-DD oppure None
            "link_prenotazione": "https://...",
            "fonte_dato": "diretta",          # reale|api|import|diretta|scanner
            "opportunity_score": None,        # 0-100 oppure None (lo calcola il backend)
        }
    """
    offerte: list[dict] = []

    # TODO: implementa qui la raccolta reale (una funzione per compagnia).
    # Esempio:
    # from scanners.ryanair import scan_ryanair
    # offerte.extend(scan_ryanair(["VRN", "BGY", "VCE", "TSF", "BLQ", "MXP", "TRN", "PSA"]))

    return offerte


def main() -> int:
    if not FLIGHT_HUNTER_API_TOKEN:
        print("FH_ACCESS_TOKEN mancante: il workflow non ha ottenuto il JWT.")
        return 1

    print(f"Endpoint: {FLIGHT_HUNTER_API_URL}")
    print(f"Connettore: {FLIGHT_HUNTER_CONNECTOR}")

    offerte = raccogli_offerte()
    print(f"Offerte raccolte: {len(offerte)}")

    if not offerte:
        print("Nessuna offerta da importare.")
        return 0

    try:
        risultato = import_offers(offerte)
    except Exception as errore:  # noqa: BLE001
        print(f"Errore durante l'import: {errore}")
        return 1

    print(f"Offerte importate in Flight Hunter: {risultato['importate']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
