import os

from dotenv import load_dotenv

load_dotenv()

FH_BACKEND_URL = (os.getenv("FH_BACKEND_URL") or "").rstrip("/")
FH_PUBLISHABLE_KEY = os.getenv("FH_PUBLISHABLE_KEY")

# Endpoint di importazione di Flight Hunter (override possibile per l'ambiente di anteprima)
FLIGHT_HUNTER_API_URL = os.getenv(
    "FH_IMPORT_URL",
    "https://flight-hunter.lovable.app/api/public/offers/import",
)

# Il workflow GitHub Actions esporta il JWT come FH_ACCESS_TOKEN.
# FH_TOKEN resta accettato come fallback per esecuzioni locali.
FLIGHT_HUNTER_API_TOKEN = os.getenv("FH_ACCESS_TOKEN") or os.getenv("FH_TOKEN")

# Connettore associato all'import: kiwi_tequila | amadeus | ryanair | wizzair | easyjet | volotea
FLIGHT_HUNTER_CONNECTOR = os.getenv("FH_CONNECTOR", "ryanair")

# Limite imposto dal backend: massimo 500 offerte per richiesta
MAX_OFFERS_PER_REQUEST = 500

REQUEST_TIMEOUT = int(os.getenv("FH_REQUEST_TIMEOUT", "60"))
