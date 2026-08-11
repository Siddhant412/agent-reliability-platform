# `infra/otel`

[`collector-config.yaml`](collector-config.yaml) is the local OpenTelemetry
Collector configuration used by `infra/docker/docker-compose.yml`. It accepts
OTLP over gRPC (`4317`) and HTTP (`4318`) and prints batched telemetry through
the Collector debug exporter.

The current API and worker persist product traces in PostgreSQL but do not yet
include an OTLP instrumentation/exporter dependency. Consequently, the
collector is available for manual or future instrumented clients, but it does
not receive telemetry from the current application by itself.

The debug exporter is appropriate only for an isolated local environment. Do
not send credentials, authorization headers, full request bodies, or customer
data to it. A production deployment needs a protected backend exporter,
retention controls, and stronger project-level redaction before telemetry
leaves the application boundary.
