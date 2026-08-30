"""Playbook retrieval: section chunking plus a small BM25 index, no external deps."""

import math
import re
from functools import lru_cache
from typing import Dict, List

from app.config import DATA_DIR

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


def load_chunks() -> List[Dict]:
    """Split playbook.md into section chunks keyed by their heading."""
    text = (DATA_DIR / "playbook.md").read_text(encoding="utf-8")
    chunks: List[Dict] = []
    current_title, current_lines = None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if current_title:
                chunks.append({"title": current_title, "text": "\n".join(current_lines).strip()})
            current_title, current_lines = line[3:].strip(), []
        elif current_title:
            current_lines.append(line)
    if current_title:
        chunks.append({"title": current_title, "text": "\n".join(current_lines).strip()})
    return chunks


class BM25Index:
    def __init__(self, chunks: List[Dict], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.docs = [_tokenize(c["title"] + " " + c["text"]) for c in chunks]
        self.doc_lens = [len(d) for d in self.docs]
        self.avg_len = sum(self.doc_lens) / max(len(self.docs), 1)
        self.df: Dict[str, int] = {}
        for doc in self.docs:
            for term in set(doc):
                self.df[term] = self.df.get(term, 0) + 1
        self.tf: List[Dict[str, int]] = []
        for doc in self.docs:
            counts: Dict[str, int] = {}
            for term in doc:
                counts[term] = counts.get(term, 0) + 1
            self.tf.append(counts)

    def _idf(self, term: str) -> float:
        n, df = len(self.docs), self.df.get(term, 0)
        return math.log((n - df + 0.5) / (df + 0.5) + 1)

    def search(self, query: str, top_k: int = 3) -> List[Dict]:
        q_terms = _tokenize(query)
        scores = []
        for i in range(len(self.docs)):
            score = 0.0
            for term in q_terms:
                tf = self.tf[i].get(term, 0)
                if tf == 0:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * self.doc_lens[i] / self.avg_len)
                score += self._idf(term) * tf * (self.k1 + 1) / denom
            scores.append((score, i))
        scores.sort(reverse=True)
        return [
            {**self.chunks[i], "score": round(s, 3)}
            for s, i in scores[:top_k]
            if s > 0
        ]


@lru_cache(maxsize=1)
def get_index() -> BM25Index:
    return BM25Index(load_chunks())


def search_playbook(query: str, top_k: int = 3) -> List[Dict]:
    return get_index().search(query, top_k)
