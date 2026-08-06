from datetime import datetime

from config.settings import (
    FLIGHT_HUNTER_API_URL
)


def start_engine():

    print("✈️ Flight Hunter Engine avviato")
    print("Ora:", datetime.now())

    if FLIGHT_HUNTER_API_URL:
        print("✅ Endpoint Flight Hunter configurato")
    else:
        print("⚠️ Endpoint Flight Hunter non ancora configurato")


if __name__ == "__main__":
    start_engine()
