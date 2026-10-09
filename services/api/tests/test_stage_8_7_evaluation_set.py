from evaluation.layout_rag_v1 import EVALUATION_SET


def test_layout_evaluation_set_is_versioned_balanced_and_has_100_questions():
    assert len(EVALUATION_SET) == 100
    assert len({item["id"] for item in EVALUATION_SET}) == 100
    assert sum(not item["answerable"] for item in EVALUATION_SET) == 20
    assert {item["expected_region_type"] for item in EVALUATION_SET} >= {
        "paragraph", "table", "chart", "image", "caption", "footnote", "code", "list"
    }
