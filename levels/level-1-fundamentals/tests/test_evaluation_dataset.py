from services.evaluation_dataset import EvaluationDataset


def test_evaluation_dataset_loads():
    dataset = EvaluationDataset("data/evaluation_dataset.json")

    cases = dataset.load()

    assert len(cases) == 5


def test_evaluation_case_contains_required_fields():
    dataset = EvaluationDataset("data/evaluation_dataset.json")

    cases = dataset.load()

    for case in cases:
        assert "question" in case
        assert "expected_answer" in case
        assert "expected_source" in case
        assert "expected_chunk" in case


def test_annual_leave_ground_truth():
    dataset = EvaluationDataset("data/evaluation_dataset.json")

    cases = dataset.load()

    annual_leave_case = cases[1]

    assert annual_leave_case["expected_answer"] == "20 days"
    assert annual_leave_case["expected_source"] == "company_policy.pdf"
    assert annual_leave_case["expected_chunk"] == 0