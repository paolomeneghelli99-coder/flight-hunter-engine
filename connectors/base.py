"""Client HTTP condiviso: sessione, header, retry con backoff."""

import time

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class BaseConnector:
    def __init__(self, nome: str, timeout: int = 30, tentativi: int = 3, pausa: float = 1.0):
        self.nome = nome
        self.timeout = timeout
        self.tentativi = tentativi
        self.pausa = pausa
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
        })

    def get(self, url: str, params: dict | None = None) -> requests.Response | None:
        ultimo_errore = None
        for tentativo in range(1, self.tentativi + 1):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                if r.status_code == 429 or r.status_code >= 500:
                    raise requests.HTTPError(f"status {r.status_code}")
                r.raise_for_status()
                return r
            except Exception as exc:  # noqa: BLE001
                ultimo_errore = exc
                time.sleep(self.pausa * tentativo)
        print(f"[{self.nome}] richiesta fallita: {url} -> {ultimo_errore}")
        return None

    def get_json(self, url: str, params: dict | None = None):
        r = self.get(url, params=params)
        if r is None:
            return None
        try:
            return r.json()
        except ValueError:
            return None

    def close(self) -> None:
        self.session.close()

