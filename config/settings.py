import os
from dotenv import load_dotenv

load_dotenv()

FLIGHT_HUNTER_API_URL = os.getenv("FLIGHT_HUNTER_API_URL")
FLIGHT_HUNTER_API_TOKEN = os.getenv("FLIGHT_HUNTER_API_TOKEN")
