"""Reuse of embeddings for byte-identical documents.

A file whose extracted text hashes to an already-indexed file's hash yields identical
chunks, so its vectors can be copied instead of paying the embedding server again —
~12.5s per 460-token chunk on a CPU-only endpoint, against a corpus that duplicates
heavily.

Kept free of application imports (no models, no database, no embedding client) so the
decision can be unit-tested on its own; importing the router that calls it would pull
in the ORM models and leave `Base.metadata` half-populated for other tests.
"""

import ast
import uuid

from open_webui.retrieval.vector.main import VectorItem


def reused_embedding_items(
    source_items: list[VectorItem] | None,
    engine: str,
    model: str,
    metadata: dict | None,
    texts: list[str],
    metadatas: list[dict],
) -> list[dict] | None:
    """Embeddings of an identical document, keyed by chunk text instead of recomputed.

    Matching on the chunk text rather than on position is what makes adoption safe:
    a vector may only be reused for the exact bytes it was computed from. The engine
    and model of the source must match too, since vectors from another model live in
    an unrelated space and the vector store cannot tell they were computed elsewhere.

    Returns None to mean "embed normally", which is also the fallback when the two
    runs split the text differently.
    """
    if not source_items:
        return None

    stored = source_items[0].metadata.get('embedding_config')
    if isinstance(stored, str):
        # Chroma stores dict metadata as its repr, so the model identity arrives as
        # a string, not the dict the writer put in.
        try:
            stored = ast.literal_eval(stored)
        except (ValueError, SyntaxError):
            return None
    if not isinstance(stored, dict):
        return None
    if stored.get('engine') != engine or stored.get('model') != model:
        return None

    # The hash is the contract that both sides indexed the same text; a mismatch
    # means the caller's candidate lookup went wrong somewhere upstream.
    if metadata and 'hash' in metadata and source_items[0].metadata.get('hash') != metadata['hash']:
        return None

    # Repeated chunks within one document carry the same vector, so a text->vector
    # map loses nothing; any chunk absent from the source forces a full re-embed.
    vectors = {item.text: item.vector for item in source_items}
    if any(text not in vectors for text in texts):
        return None

    return [
        {
            'id': str(uuid.uuid4()),
            'text': text,
            'vector': vectors[text],
            # Metadata of the written chunk identifies the file that owns it, never
            # the file the vector was borrowed from.
            'metadata': metadatas[idx],
        }
        for idx, text in enumerate(texts)
    ]
