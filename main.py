"""Flight Hunter Engine — entry point eseguito da GitHub Actions."""

import sys
import traceback

from config.settings import settings
from database.importer import import_offers
from scanners import SCANNERS


def main() -> int:
    settings.validate()

    tutte = []
    for nome, factory in SCANNERS.items():
        try:
            scanner = factory()
            trovate = scanner.run()
            print(f"[{nome}] offerte trovate: {len(trovate)}")
            tutte.extend(trovate)
        except Exception:
            print(f"[{nome}] errore durante la scansione:", file=sys.stderr)
            traceback.print_exc()

    if not tutte:
        print("Nessuna offerta trovata: niente da importare.")
        return 0

    # deduplica globale
    viste = set()
    uniche = []
    for o in tutte:
        chiave = (o.aeroporto_partenza, o.destinazione, o.data_partenza, o.prezzo)
        if chiave in viste:
            continue
        viste.add(chiave)
        uniche.append(o)

    uniche.sort(key=lambda o: o.prezzo)

    totale = import_offers([o.to_payload() for o in uniche])
    print(f"Totale offerte importate: {totale}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
