"""Modello offerta e classe base degli scanner."""

from dataclasses import dataclass, field
from typing import Optional

from config.settings import settings


FONTI_VALIDE = {"reale", "api", "import", "diretta", "scanner"}


@dataclass
class ReturnOption:
    """Singola opzione di ritorno consigliata."""

    data_ritorno: str
    prezzo: float

    ora_partenza: Optional[str] = None
    ora_arrivo: Optional[str] = None

    durata: Optional[int] = None
    notti: Optional[int] = None

    link_prenotazione: Optional[str] = None

    def to_payload(self) -> dict:
        risultato = {
            "data_ritorno": self.data_ritorno,
            "prezzo": round(float(self.prezzo), 2),
        }

        if self.ora_partenza:
            risultato["ora_partenza"] = self.ora_partenza

        if self.ora_arrivo:
            risultato["ora_arrivo"] = self.ora_arrivo

        if self.durata:
            risultato["durata"] = self.durata

        if self.notti:
            risultato["notti"] = self.notti

        if self.link_prenotazione:
            risultato["link_prenotazione"] = self.link_prenotazione

        return risultato


@dataclass
class Offerta:
    aeroporto_partenza: str
    destinazione: str
    compagnia: str
    prezzo: float
    data_partenza: str

    valuta: str = "EUR"
    data_ritorno: Optional[str] = None

    # codice aeroporto arrivo (necessario per cercare il ritorno)
    aeroporto_arrivo: Optional[str] = None

    # orari volo andata
    ora_partenza: Optional[str] = None
    ora_arrivo: Optional[str] = None

    # compatibilità vecchio formato
    ora_partenza_ritorno: Optional[str] = None
    ora_arrivo_ritorno: Optional[str] = None

    durata_andata: Optional[int] = None
    durata_ritorno: Optional[int] = None

    link_prenotazione: Optional[str] = None

    fonte_dato: str = "scanner"

    opportunity_score: Optional[int] = None

    # nuove opzioni di ritorno
    ritorni: list[ReturnOption] = field(default_factory=list)


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

        return True


    def to_payload(self) -> dict:

        payload = {
            "aeroporto_partenza": self.aeroporto_partenza.upper(),
            "destinazione": self.destinazione,
            "compagnia": self.compagnia,

            "prezzo": round(float(self.prezzo), 2),

            "valuta": (self.valuta or "EUR").upper()[:3],

            "data_partenza": self.data_partenza,
            "data_ritorno": self.data_ritorno,

            "fonte_dato": self.fonte_dato,
        }


        if self.aeroporto_arrivo:
            payload["aeroporto_arrivo"] = self.aeroporto_arrivo


        if self.ora_partenza:
            payload["ora_partenza"] = self.ora_partenza

        if self.ora_arrivo:
            payload["ora_arrivo"] = self.ora_arrivo


        if self.ora_partenza_ritorno:
            payload["ora_partenza_ritorno"] = self.ora_partenza_ritorno

        if self.ora_arrivo_ritorno:
            payload["ora_arrivo_ritorno"] = self.ora_arrivo_ritorno


        if self.durata_andata:
            payload["durata_andata"] = self.durata_andata


        if self.durata_ritorno:
            payload["durata_ritorno"] = self.durata_ritorno


        if self.ritorni:
            payload["ritorni"] = [
                r.to_payload()
                for r in self.ritorni
            ]


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


    def scan(self) -> list:
        raise NotImplementedError


    def run(self) -> list:

        offerte = [
            o
            for o in self.scan()
            if o.valida()
            and o.prezzo <= self.prezzo_massimo
        ]


        viste = set()
        uniche = []


        for o in offerte:

            chiave = (
                o.aeroporto_partenza,
                o.aeroporto_arrivo,
                o.data_partenza,
                o.prezzo
            )

            if chiave in viste:
                continue

            viste.add(chiave)
            uniche.append(o)


        uniche.sort(
            key=lambda o: o.prezzo
        )


        if self.connector:
            self.connector.close()


        return uniche
