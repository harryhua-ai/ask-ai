"""#67 Generation Truth:非空 generation 的 PG chunk 与 serving 投影验证。"""

from types import SimpleNamespace


def test_non_empty_generation_serving_truth_is_not_sentinel_zero_zero():
    from backend.services.chunk_serving import chunk_serving_for_doc

    class _Collection:
        def query(self, *args, **kwargs):
            raise AssertionError("query API should not be used by the truth helper")

        def iterator(self, **kwargs):
            return [
                SimpleNamespace(
                    properties={
                        "source_id": "src/main/ne503.md",
                        "chunk_index": 0,
                        "generation_ordinal": 7,
                    }
                ),
                SimpleNamespace(
                    properties={
                        "source_id": "src/main/ne503.md",
                        "chunk_index": 1,
                        "generation_ordinal": 7,
                    }
                ),
            ]

    truth = chunk_serving_for_doc(
        type("_Client", (), {"collections": type("_Collections", (), {"get": lambda self, _: _Collection()})()})(),
        "Document",
        "src/main/ne503.md",
        total_chunks=2,
        generation_ordinals=(7,),
    )

    payload = truth.to_dict()
    assert payload["total_chunks"] == 2
    assert payload["serving_chunks"] == 2
    assert payload["consistent"] is True
