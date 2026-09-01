"""Stage 2.1 — regression test for a real live bug: PostgREST serializes
a `halfvec` column (chunks.embedding) as a JSON *string* containing the
vector's text representation ("[-0.045,0.03,...]"), not a real JSON
array of numbers. A real recluster run against production silently
produced zero clusters until this was caught — see storage.py's module
docstring for the full story, including why Stage 1.5's retrieval never
hit this (its RPC computes distance server-side and never returns a raw
embedding through PostgREST at all).
"""
from app.graph.storage import _parse_embedding


def test_parse_embedding_handles_the_real_postgrest_string_shape():
    raw = "[-0.045898438,-0.027023315,0.10443115]"
    assert _parse_embedding(raw) == [-0.045898438, -0.027023315, 0.10443115]


def test_parse_embedding_passes_through_a_real_list_unchanged():
    # In case PostgREST's serialization ever changes to a real array —
    # this should keep working either way.
    assert _parse_embedding([0.1, 0.2]) == [0.1, 0.2]


def test_parse_embedding_returns_none_for_none():
    assert _parse_embedding(None) is None
