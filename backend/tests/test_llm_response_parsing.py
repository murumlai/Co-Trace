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


def test_github_models_populated_json_fields_are_returned_verbatim():
    root, solution = llm_client._parse_json_content(
        '{"root_cause":"fixture open","suggested_solution":"reseat DUT"}',
        "E123",
        "voltage droop",
    )

    assert root == "fixture open"
    assert solution == "reseat DUT"


def test_github_models_malformed_content_returns_actionable_fallback():
    root, solution = llm_client._parse_json_content("not json at all", "E123", "voltage droop")

    assert "failure code 'E123'" in root
    assert "reanalyze with more failure evidence" in solution


def test_copilot_malformed_content_returns_actionable_fallback_solution():
    root, solution = copilot_client._parse_json_content("", "FFFFFFFF", "Reading 20V failed")

    assert "failure code 'FFFFFFFF'" in root
    assert "See root cause above" not in solution
    assert "reanalyze with more failure evidence" in solution