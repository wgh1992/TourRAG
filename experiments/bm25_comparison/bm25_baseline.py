"""
Pure Python BM25 baseline for TourRAG retrieval experiments.

This module intentionally has no third-party dependencies. It indexes local
database text fields and returns a ranked list of viewpoint IDs for a query.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple


def tokenize(text: str) -> List[str]:
    """
    Tokenize mixed English/CJK text for a lexical baseline.

    English-like alphanumeric runs are grouped. CJK characters are emitted as
    single-character tokens so Chinese place descriptions still contribute
    signal without requiring a segmentation package.
    """
    tokens: List[str] = []
    current: List[str] = []

    def flush_current() -> None:
        if current:
            token = "".join(current).lower()
            if len(token) > 1 or token.isdigit():
                tokens.append(token)
            current.clear()

    for char in text:
        codepoint = ord(char)
        is_cjk = (
            0x3400 <= codepoint <= 0x4DBF
            or 0x4E00 <= codepoint <= 0x9FFF
            or 0xF900 <= codepoint <= 0xFAFF
        )
        if is_cjk:
            flush_current()
            tokens.append(char)
            continue

        category = unicodedata.category(char)
        if category[0] in {"L", "N"}:
            current.append(char)
        else:
            flush_current()

    flush_current()
    return tokens


@dataclass(frozen=True)
class BM25Document:
    viewpoint_id: int
    text: str
    metadata: Dict[str, object]


class BM25Index:
    """Okapi BM25 implementation for ranking viewpoint documents."""

    def __init__(
        self,
        documents: Sequence[BM25Document],
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.documents = list(documents)
        self.k1 = k1
        self.b = b
        self.doc_lengths: List[int] = []
        self.term_freqs: List[Counter[str]] = []
        self.doc_freqs: Dict[str, int] = defaultdict(int)

        for document in self.documents:
            terms = tokenize(document.text)
            term_freq = Counter(terms)
            self.term_freqs.append(term_freq)
            self.doc_lengths.append(len(terms))
            for term in term_freq:
                self.doc_freqs[term] += 1

        self.num_docs = len(self.documents)
        self.avg_doc_len = (
            sum(self.doc_lengths) / self.num_docs if self.num_docs else 0.0
        )

    def _idf(self, term: str) -> float:
        df = self.doc_freqs.get(term, 0)
        return math.log(1.0 + (self.num_docs - df + 0.5) / (df + 0.5))

    def score(self, query: str, doc_index: int) -> float:
        query_terms = tokenize(query)
        if not query_terms or not self.documents:
            return 0.0

        term_freq = self.term_freqs[doc_index]
        doc_len = self.doc_lengths[doc_index]
        length_norm = self.k1 * (
            1.0 - self.b + self.b * doc_len / max(self.avg_doc_len, 1.0)
        )

        score = 0.0
        for term in query_terms:
            tf = term_freq.get(term, 0)
            if tf == 0:
                continue
            numerator = tf * (self.k1 + 1.0)
            denominator = tf + length_norm
            score += self._idf(term) * numerator / denominator
        return score

    def search(self, query: str, top_k: int = 10) -> List[Dict[str, object]]:
        scored: List[Tuple[float, int]] = []
        for idx, _document in enumerate(self.documents):
            score = self.score(query, idx)
            if score > 0:
                scored.append((score, idx))

        scored.sort(
            key=lambda item: (
                item[0],
                float(self.documents[item[1]].metadata.get("popularity") or 0.0),
            ),
            reverse=True,
        )

        results: List[Dict[str, object]] = []
        for score, idx in scored[:top_k]:
            document = self.documents[idx]
            row = {
                "viewpoint_id": document.viewpoint_id,
                "score": score,
                "method": "bm25",
            }
            row.update(document.metadata)
            results.append(row)
        return results


def build_document_text(row: Dict[str, object]) -> str:
    """Combine database fields into the text indexed by the BM25 baseline."""
    parts = [
        row.get("name_primary") or "",
        row.get("name_variants") or "",
        row.get("category_norm") or "",
        row.get("wikipedia_title") or "",
        row.get("extract_text") or "",
        row.get("sections") or "",
    ]
    return " ".join(str(part) for part in parts if part)

