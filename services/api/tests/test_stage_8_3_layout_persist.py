from app.ingest.layout import LayoutResult, Region, RegionType, Surface, SurfaceKind
from app.ingest.layout_persist import layout_representations


def test_layout_representations_keep_one_real_citation_anchor_per_region():
    layout = LayoutResult(
        surfaces=[Surface(0, SurfaceKind.PDF_PAGE, 1, 612, 792)],
        regions=[
            Region(0, 0, RegionType.HEADING, 0, content="Results", bbox=(.1, .1, .9, .2)),
            Region(1, 0, RegionType.CHART, 1, content="", semantic_summary="Sales rose 20%", bbox=(.1, .2, .9, .8)),
        ],
    )

    reps = layout_representations(layout)

    assert [rep.region_ordinal for rep in reps] == [0, 1, 1]
    assert [rep.representation_type for rep in reps] == ["text", "caption", "visual"]
    assert reps[0].meta["page"] == 1
    assert reps[1].content == "Sales rose 20%"
    assert reps[2].content == "Sales rose 20%"


def test_empty_visual_region_still_has_a_visual_anchor():
    layout = LayoutResult(
        surfaces=[Surface(0, SurfaceKind.IMAGE, 1, 800, 600)],
        regions=[Region(0, 0, RegionType.IMAGE, 0, bbox=(0, 0, 1, 1))],
    )
    reps = layout_representations(layout)
    assert len(reps) == 1
    assert reps[0].representation_type == "visual"
    assert reps[0].content == ""
