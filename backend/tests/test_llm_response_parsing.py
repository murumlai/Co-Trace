from app import copilot_client, llm_client


def test_copilot_empty_json_fields_return_actionable_fallback():
    root, solution = copilot_client._parse_json_content(
        '{"root_cause":"","suggested_solution":""}',
        "E123",
        "voltage droop",
    )

    assert "No root cause returned" not in root
    assert "failure code 'E123'" in root
    assert "voltage droop" in root
    assert "reanalyze with more failure evidence" in solution


def test_github_models_empty_json_fields_return_actionable_fallback():
    root, solution = llm_client._parse_json_content(
        '{"root_cause":"","suggested_solution":""}',
        "E123",
        "voltage droop",
    )

    assert "No root cause returned" not in root
    assert "failure code 'E123'" in root
    assert "voltage droop" in root
    assert "reanalyze with more failure evidence" in solution