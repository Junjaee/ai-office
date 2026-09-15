from .gosi import GosiAdapter
from .bbs import BbsAdapter
from .gnews import GnewsAdapter

_REGISTRY = {"gosi": GosiAdapter, "bbs": BbsAdapter, "gnews": GnewsAdapter}


def get_adapter(name: str):
    return _REGISTRY[name]()
