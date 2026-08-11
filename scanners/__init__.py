```python
"""Registro degli scanner attivi."""

from scanners.base import BaseScanner, Offerta
from scanners.ryanair import RyanairScanner
from scanners.volotea import VoloteaScanner


SCANNERS = {
    "ryanair": RyanairScanner,
    "volotea": VoloteaScanner,
}


__all__ = [
    "BaseScanner",
    "Offerta",
    "SCANNERS",
]
```
