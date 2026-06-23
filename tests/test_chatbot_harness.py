"""CI coverage for the chatbot harness — runs its automated checks (model mocked)."""

from chatbot_harness import check_context_scenarios, check_conversation_flow


def test_context_scenarios_all_pass():
    passed, total = check_context_scenarios(verbose=False)
    assert passed == total, f"only {passed}/{total} CONTEXT scenarios passed"


def test_conversation_flow_all_pass():
    passed, total = check_conversation_flow(verbose=False)
    assert passed == total, f"only {passed}/{total} flow checks passed"
