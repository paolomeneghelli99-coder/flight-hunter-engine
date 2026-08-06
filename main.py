from database.importer import import_offers


def start_engine():

    print("✈️ Flight Hunter Engine avviato")

    test_offer = {
        "connettore": "ryanair",
        "offerte": [
            {
                "aeroporto_partenza": "VRN",
                "destinazione": "Barcellona",
                "compagnia": "Ryanair",
                "prezzo": 24.99,
                "valuta": "EUR",
                "data_partenza": "2026-09-14",
                "data_ritorno": "2026-09-18",
                "link_prenotazione": "https://www.ryanair.com",
                "fonte_dato": "scanner",
                "opportunity_score": 88
            }
        ]
    }

    risultato = import_offers(test_offer)

    print("Risultato import:")
    print(risultato)


if __name__ == "__main__":
    start_engine()
