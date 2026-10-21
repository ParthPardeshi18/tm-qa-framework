from src import report


def test_report_builds_to_exactly_one_page(tmp_path):
    assert report.build(tmp_path / "r.pdf") == 1


def test_report_facts_reconcile_with_qa_records():
    f = report.facts()
    assert sum(f["outcomes"].values()) == len(f["reviews"]) == 24
    assert len(f["scored"]) + len(f["obs"]) == len(report.app_data.load_qa()[1])
    assert f["mean_score"] == round(f["reviews"]["quality_score"].mean(), 1)
