from enum import StrEnum


class MembershipRole(StrEnum):
    PLATFORM_ADMIN = "platform_admin"
    ORG_ADMIN = "org_admin"
    PROJECT_ADMIN = "project_admin"
    AI_ENGINEER = "ai_engineer"
    SUPERVISOR = "supervisor"
    TEAM_LEAD = "team_lead"
    OPERATOR = "operator"
    ANALYST = "analyst"
    API_CLIENT = "api_client"


class ConnectorType(StrEnum):
    MCP = "mcp"
    LOCAL = "local"


class ConnectorAuthMode(StrEnum):
    NONE = "none"
    API_KEY = "api_key"
    OAUTH = "oauth"
    SERVICE_ACCOUNT = "service_account"


class ConnectorStatus(StrEnum):
    ACTIVE = "active"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


class ToolRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class WorkflowVersionStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    RESUMED = "resumed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SpanStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    CANCELLED = "cancelled"
    IN_PROGRESS = "in_progress"


class ToolCallStatus(StrEnum):
    PROPOSED = "proposed"
    BLOCKED = "blocked"
    APPROVED = "approved"
    EXECUTED = "executed"
    REJECTED = "rejected"
    FAILED = "failed"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class PolicyAction(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class RolloutStrategy(StrEnum):
    DIRECT = "direct"
    CANARY = "canary"
    SHADOW = "shadow"
    AB_COMPARE = "ab_compare"


class ProjectEnvironment(StrEnum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class EvalRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EvalCaseStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

