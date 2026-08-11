"""Flight Hunter Engine — entry point eseguito da GitHub Actions."""

import sys
import traceback

from config.settings import settings
from database.importer import import_offers
from scanners import SCANNERS
from scanners.returns import aggiungi_ritorni
from connectors.base import BaseConnector


def importa_offerte(
    offerte,
    nome_scanner,
) -> int:
    """Importa le offerte prodotte da uno scanner."""

    if not offerte:
        print(
            f"[{nome_scanner}] Nessuna offerta da importare."
        )
        return 0

    totale = import_offers(
        [
            o.to_payload()
            for o in offerte
        ]
    )

    print(
        f"[{nome_scanner}] Totale offerte importate: {totale}"
    )

    return totale


def deduplica_offerte(
    offerte,
):
    """Deduplica le offerte mantenendo quelle più economiche."""

    viste = set()
    uniche = []

    for o in offerte:

        chiave = (
            o.aeroporto_partenza,
            o.aeroporto_arrivo,
            o.destinazione,
            o.data_partenza,
            o.prezzo,
        )

        if chiave in viste:
            continue

        viste.add(chiave)
        uniche.append(o)

    uniche.sort(
        key=lambda o: o.prezzo
    )

    return uniche


def main() -> int:

    settings.validate()

    totale_importate = 0

    # ============================================================
    # ESECUZIONE SCANNER IN ORDINE
    # ============================================================

    for nome, factory in SCANNERS.items():

        print("")
        print("=" * 60)
        print(
            f"AVVIO SCANNER: {nome.upper()}"
        )
        print("=" * 60)

        try:

            scanner = factory()

            trovate = scanner.run()

            print(
                f"[{nome}] offerte trovate: {len(trovate)}"
            )

            if not trovate:
                print(
                    f"[{nome}] nessuna offerta prodotta."
                )
                continue

            # ====================================================
            # RYANAIR
            #
            # I ritorni vengono cercati SUBITO dopo le offerte
            # Ryanair e PRIMA dell'avvio di qualsiasi altro
            # scanner.
            # ====================================================

            if nome.lower() == "ryanair":

                print("")
                print("=" * 60)
                print(
                    "RICERCA RITORNI RYANAIR"
                )
                print("=" * 60)

                connector = BaseConnector(
                    nome="returns"
                )

                try:

                    trovate = aggiungi_ritorni(
                        trovate,
                        connector,
                    )

                finally:

                    connector.close()

                tot_ritorni = sum(
                    len(o.ritorni)
                    for o in trovate
                )

                print(
                    f"Ritorni Ryanair trovati: {tot_ritorni}"
                )

            # ====================================================
            # DEDUPLICA
            # ====================================================

            trovate = deduplica_offerte(
                trovate
            )

            # ====================================================
            # IMPORTAZIONE IMMEDIATA
            #
            # In questo modo Ryanair viene importato con i suoi
            # ritorni PRIMA che inizi Volotea.
            # ====================================================

            totale_importate += importa_offerte(
                trovate,
                nome,
            )

        except Exception:

            print(
                f"[{nome}] errore durante la scansione:",
                file=sys.stderr,
            )

            traceback.print_exc()

    # ============================================================
    # FINE
    # ============================================================

    print("")
    print("=" * 60)
    print(
        "FLIGHT HUNTER COMPLETATO"
    )
    print("=" * 60)

    print(
        f"Totale offerte importate: {totale_importate}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(
        main()
    )
