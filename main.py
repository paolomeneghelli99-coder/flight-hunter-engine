"""Flight Hunter Engine — entry point eseguito da GitHub Actions."""

import sys
import traceback

from config.settings import settings
from database.importer import import_offers
from scanners import SCANNERS
from scanners.returns import aggiungi_ritorni
from connectors.base import BaseConnector


def main() -> int:

    settings.validate()

    tutte = []

    for nome, factory in SCANNERS.items():

        try:

            scanner = factory()

            trovate = scanner.run()

            print(
                f"[{nome}] offerte trovate: {len(trovate)}"
            )

            tutte.extend(trovate)

        except Exception:

            print(
                f"[{nome}] errore durante la scansione:",
                file=sys.stderr
            )

            traceback.print_exc()

    if not tutte:

        print(
            "Nessuna offerta trovata: niente da importare."
        )

        return 0

    # ========================================================
    # DEDUPLICA GLOBALE
    # ========================================================

    viste = set()

    uniche = []

    for o in tutte:

        chiave = (
            o.aeroporto_partenza,
            o.aeroporto_arrivo,
            o.destinazione,
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

    # ========================================================
    # RICERCA VOLI DI RITORNO
    # ========================================================

    print(
        "Ricerca ritorni Ryanair in corso..."
    )

    connector = BaseConnector(
        nome="returns"
    )

    try:

        uniche = aggiungi_ritorni(
            uniche,
            connector
        )

    finally:

        connector.close()

    tot_ritorni = sum(
        len(o.ritorni)
        for o in uniche
    )

    print(
        f"Ritorni trovati: {tot_ritorni}"
    )

    # ========================================================
    # IMPORTAZIONE
    # ========================================================

    totale = import_offers(
        [
            o.to_payload()
            for o in uniche
        ]
    )

    print(
        f"Totale offerte importate: {totale}"
    )

    return 0


if __name__ == "__main__":

    sys.exit(
        main()
    )
