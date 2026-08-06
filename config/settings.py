import os
from dotenv import load_dotenv

load_dotenv()

FLIGHT_HUNTER_API_URL = os.getenv("FH_BACKEND_URL") + "/api/public/offers/import"

FLIGHT_HUNTER_API_TOKEN = os.getenv("FH_TOKEN")
