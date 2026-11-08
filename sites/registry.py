from sites.khelv2 import KhelV2
from sites.dmplay20 import Dmplay20
from sites.dmfirst11 import Dmfirst11
from sites.raxi import Raxi

ADAPTERS = {c.slug: c for c in (KhelV2, Dmplay20, Dmfirst11, Raxi)}


def build(doc: dict):
    cls = ADAPTERS.get(doc["slug"])
    if not cls:
        raise KeyError(f"no adapter for {doc['slug']}")
    return cls(doc)