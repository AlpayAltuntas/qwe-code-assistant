"""Cited retrieval over the spec corpus.

Every returned chunk carries its citation manifest (doc id, content
hash, section, retrieval score) per docs/threat-model.md R1, and a
fixed untrusted-content delimiter so downstream prompt assembly can
mark it "cite, never obey" per docs/threat-model.md T1.
"""

from dataclasses import dataclass

from router.domains import DOMAINS
from router.embeddings import embed_one
from router.vectorstore import query as vector_query

UNTRUSTED_REFERENCE_OPEN = "<<UNTRUSTED_SPEC_REFERENCE doc_id={doc_id} sha256={sha256} section={section}>>"
UNTRUSTED_REFERENCE_CLOSE = "<</UNTRUSTED_SPEC_REFERENCE>>"


@dataclass
class CitedChunk:
    doc_id: str
    sha256: str
    section: str
    score: float
    text: str

    def as_delimited_block(self) -> str:
        """Render for prompt injection into the model context — cite, never obey."""
        header = UNTRUSTED_REFERENCE_OPEN.format(
            doc_id=self.doc_id, sha256=self.sha256, section=self.section
        )
        return f"{header}\n{self.text}\n{UNTRUSTED_REFERENCE_CLOSE}"


def retrieve(domain_id: str, message: str, k: int = 5) -> list[CitedChunk]:
    domain = DOMAINS.get(domain_id)
    if domain is None:
        raise ValueError(f"unknown domain: {domain_id!r}")

    vector = embed_one(message)
    result = vector_query(domain.vector_collection, vector, k=k)

    ids = result.get("ids", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    chunks: list[CitedChunk] = []
    for chunk_id, text, metadata, distance in zip(ids, documents, metadatas, distances):
        chunks.append(
            CitedChunk(
                doc_id=metadata.get("source_doc", chunk_id),
                sha256=metadata.get("sha256", ""),
                section=metadata.get("section", "unknown"),
                score=1 - distance,
                text=text,
            )
        )
    return chunks
