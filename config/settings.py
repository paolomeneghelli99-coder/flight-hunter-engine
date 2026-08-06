"""Configurazione letta da variabili d'ambiente (GitHub Secrets)."""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

DEFAULT_IMPORT_URL = "https://flight-hunter.lovable.app/api/public/offers/import"

# Aeroporti di partenza monitorati da Flight Hunter
ORIGINI = ["VRN", "BGY", "VCE", "TSF", "BLQ", "MXP", "TRN", "PSA"]


def _env(nome: str, default: str = "") -> str:
    return (os.environ.get(nome) or default).strip()


@dataclass
class Settings:
    import_url: str = field(default_factory=lambda: _env("FH_IMPORT_URL", DEFAULT_IMPORT_URL))
    access_token: str = field(default_factory=lambda: _env("FH_ACCESS_TOKEN"))
    connettore: str = field(default_factory=lambda: _env("FH_CONNECTOR", "ryanair"))
    fonte_dato: str = field(default_factory=lambda: _env("FH_FONTE_DATO", "scanner"))
    valuta: str = field(default_factory=lambda: _env("FH_VALUTA", "EUR"))
    origini: list = field(default_factory=lambda: [
        a.strip().upper() for a in _env("FH_ORIGINI", ",".join(ORIGINI)).split(",") if a.strip()
    ])
    giorni_anticipo_max: int = field(default_factory=lambda: int(_env("FH_GIORNI_MAX", "120")))
    prezzo_massimo: float = field(default_factory=lambda: float(_env("FH_PREZZO_MAX", "80")))
    batch_size: int = field(default_factory=lambda: min(int(_env("FH_BATCH_SIZE", "200")), 500))
    timeout: int = field(default_factory=lambda: int(_env("FH_TIMEOUT", "30")))

    def validate(self) -> None:
        if not self.access_token:
            raise SystemExit("FH_ACCESS_TOKEN mancante: il workflow deve ottenere il JWT prima di eseguire main.py")
        if not self.import_url:
            raise SystemExit("FH_IMPORT_URL mancante")


settings = Settings()
