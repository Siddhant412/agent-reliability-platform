from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

from arp_core.domain.enums import MembershipRole, PolicyAction


class PolicyEvaluationError(ValueError):
    """Raised when a policy condition uses unsupported syntax."""


@dataclass(frozen=True)
class PolicyDecision:
    action: PolicyAction
    policy_name: str | None = None
    approver_role: MembershipRole | None = None
    reason: str | None = None


def evaluate_policy_pack(
    policy_pack: list[dict[str, Any]],
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    input_payload: dict[str, Any],
) -> PolicyDecision:
    context = {
        "tool": {"name": tool_name, "args": tool_args},
        "input": input_payload,
    }
    for policy in policy_pack:
        condition = str(policy.get("when", "")).strip()
        if not condition:
            continue
        if not _evaluate_condition(condition, context):
            continue

        action = PolicyAction(policy["action"])
        approver_role = (
            MembershipRole(policy["approver_role"])
            if policy.get("approver_role") is not None
            else None
        )
        return PolicyDecision(
            action=action,
            policy_name=str(policy.get("name") or "unnamed_policy"),
            approver_role=approver_role,
            reason=f"matched policy {policy.get('name') or 'unnamed_policy'}",
        )

    return PolicyDecision(action=PolicyAction.ALLOW)


def _evaluate_condition(condition: str, context: dict[str, Any]) -> bool:
    try:
        parsed = ast.parse(condition, mode="eval")
    except SyntaxError as exc:
        raise PolicyEvaluationError(f"invalid policy condition: {condition}") from exc
    return bool(_eval_node(parsed.body, context))


def _eval_node(node: ast.AST, context: dict[str, Any]) -> Any:
    if isinstance(node, ast.BoolOp):
        values = [_eval_node(value, context) for value in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
        raise PolicyEvaluationError("unsupported boolean operator")

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not bool(_eval_node(node.operand, context))

    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, context)
        for operator, comparator in zip(node.ops, node.comparators, strict=True):
            right = _eval_node(comparator, context)
            if not _compare(left, operator, right):
                return False
            left = right
        return True

    if isinstance(node, ast.Name):
        if node.id not in context:
            raise PolicyEvaluationError(f"unknown policy identifier: {node.id}")
        return context[node.id]

    if isinstance(node, ast.Attribute):
        value = _eval_node(node.value, context)
        if isinstance(value, dict):
            return value.get(node.attr)
        return getattr(value, node.attr)

    if isinstance(node, ast.Subscript):
        value = _eval_node(node.value, context)
        key = _eval_node(node.slice, context)
        if isinstance(value, dict):
            return value.get(key)
        return value[key]

    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.List):
        return [_eval_node(item, context) for item in node.elts]

    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(item, context) for item in node.elts)

    raise PolicyEvaluationError(f"unsupported policy syntax: {node.__class__.__name__}")


def _compare(left: Any, operator: ast.cmpop, right: Any) -> bool:
    if isinstance(operator, ast.Eq):
        return left == right
    if isinstance(operator, ast.NotEq):
        return left != right
    if isinstance(operator, ast.Gt):
        return left > right
    if isinstance(operator, ast.GtE):
        return left >= right
    if isinstance(operator, ast.Lt):
        return left < right
    if isinstance(operator, ast.LtE):
        return left <= right
    if isinstance(operator, ast.In):
        return left in right
    if isinstance(operator, ast.NotIn):
        return left not in right
    raise PolicyEvaluationError("unsupported comparison operator")
