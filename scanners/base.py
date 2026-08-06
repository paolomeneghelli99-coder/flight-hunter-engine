"""Modello offerta e classe base degli scanner."""

from dataclasses import dataclass
from typing import Optional

from config.settings import settings


FONTI_VALIDE = {"reale", "api", "import", "diretta", "scanner"}
TIPI_VIAGGIO_VALIDI = {"solo_andata", "andata_ritorno"}


@dataclass
class Offerta:
    aeroporto_partenza: str
    destinazione: str
    compagnia: str
    prezzo: float
    data_partenza: str
    valuta: str = "EUR"
    data_ritorno: Optional[str] = None
    link_prenotazione: Optional[str] = None
    fonte_dato: str = "scanner"
    opportunity_score: Optional[int] = None
    tipo_viaggio: str = "solo_andata"

    def valida(self) -> bool:
        if not (3 <= len(self.aeroporto_partenza) <= 8):
            return False

        if not (2 <= len(self.destinazione) <= 80):
            return False

        if not (2 <= len(self.compagnia) <= 60):
            return False

        if not (0 < float(self.prezzo) <= 10000):
            return False

        if len(self.data_partenza) != 10:
            return False

        if self.fonte_dato not in FONTI_VALIDE:
            return False

        if self.tipo_viaggio not in TIPI_VIAGGIO_VALIDI:
            return False

        return True

    def to_payload(self) -> dict:
        payload = {
            "aeroporto_partenza": self.aeroporto_partenza.upper(),
            "destinazione": self.destinazione,
            "compagnia": self.compagnia,
            "prezzo": round(float(self.prezzo), 2),
            "valuta": self.valuta.upper()[:3],
            "data_partenza": self.data_partenza,
            "data_ritorno": self.data_ritorno,
            "fonte_dato": self.fonte_dato,
            "tipo_viaggio": self.tipo_viaggio,
        }

        if self.link_prenotazione:
            payload["link_prenotazione"] = self.link_prenotazione[:1000]

        if self.opportunity_score is not None:
            payload["opportunity_score"] = max(
                0,
                min(100, int(self.opportunity_score))
            )

        return payload


class BaseScanner:

    nome = "base"
    compagnia = "Sconosciuta"

    def __init__(self, connector=None):
        self.connector = connector
        self.origini = settings.origini
        self.prezzo_massimo = settings.prezzo_massimo
        self.tipo_viaggio = settings.tipo_viaggio

    def scan(self):
        raise NotImplementedError

    def run(self):
        offerte = [
            o for o in self.scan()
            if o.valida()
            and o.prezzo <= self.prezzo_massimo
        ]

        viste = set()
        uniche = []

        for o in offerte:
            chiave = (
                o.aeroporto_partenza,
                o.destinazione,
                o.data_partenza,
                o.prezzo,
                o.tipo_viaggio
            )

            if chiave in viste:
                continue

            viste.add(chiave)
            uniche.append(o)

        uniche.sort(key=lambda o: o.prezzo)

        if self.connector:
            self.connector.close()

        return uniche
