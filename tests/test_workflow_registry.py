from __future__ import annotations

from arp_core.workflow_registry.validation import (
    WorkflowDefinitionError,
    canonical_support_ticket_workflow_path,
    load_workflow_definition_file,
    parse_workflow_definition,
    validate_workflow_definition,
)


def test_canonical_support_ticket_workflow_example_is_valid() -> None:
    document = load_workflow_definition_file(canonical_support_ticket_workflow_path())

    validate_workflow_definition(document)
    parsed = parse_workflow_definition(document)

    assert parsed.workflow.slug == "support-ticket-resolution"
    assert parsed.workflow.domain == "customer_support"
    assert parsed.workflow_version.version == "1.0.0"
    assert [tool.name for tool in parsed.workflow_version.tool_set] == [
        "kb_search",
        "get_customer_profile",
        "get_order",
        "issue_refund",
        "post_ticket_comment",
        "send_customer_email",
    ]


def test_invalid_json_schema_is_rejected_at_definition_validation_time() -> None:
    document = load_workflow_definition_file(canonical_support_ticket_workflow_path())
    document["workflow"]["input_schema"] = {"type": "definitely-not-a-valid-json-schema-type"}

    try:
        validate_workflow_definition(document)
    except WorkflowDefinitionError as exc:
        assert "input_schema is not a valid JSON Schema" in str(exc)
    else:
        raise AssertionError("expected workflow definition validation to fail")
