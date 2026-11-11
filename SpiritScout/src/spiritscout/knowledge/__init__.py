"""参考知识库与经验库。

``SEED_VERSION`` 走惰性访问：参考数据（``knowledge/data/seed.json``）与它的
加载器是可选件，安装目录被杀软清理过时不该连带把整个包 import 挂掉。
"""

from spiritscout.knowledge.semantic import (
    HashEmbedding,
    OpenAICompatibleEmbedding,
    SemanticIndex,
    index_store,
)
from spiritscout.knowledge.store import BASES, KnowledgeStore, fts_terms

__all__ = [
    "BASES",
    "SEED_VERSION",
    "HashEmbedding",
    "KnowledgeStore",
    "OpenAICompatibleEmbedding",
    "SemanticIndex",
    "fts_terms",
    "index_store",
]


def __getattr__(name: str):
    """只在真有人要 ``SEED_VERSION`` 时才去碰 seed 模块。"""
    if name == "SEED_VERSION":
        from spiritscout.knowledge.seed import SEED_VERSION

        return SEED_VERSION
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")