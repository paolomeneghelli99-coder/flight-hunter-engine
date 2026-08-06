import os
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


def connect_supabase():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise Exception("Configurazione Supabase mancante")

    return create_client(
        SUPABASE_URL,
        SUPABASE_KEY
    )


def start_scan():
    print("✈️ Flight Hunter Engine avviato")
    print("Ora:", datetime.now())

    supabase = connect_supabase()

    print("✅ Collegamento Supabase riuscito")


if __name__ == "__main__":
    start_scan()
