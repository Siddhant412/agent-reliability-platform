# `infra/otel`

[`collector-config.yaml`](collector-config.yaml) is the local OpenTelemetry
Collector configuration used by `infra/docker/docker-compose.yml`. It accepts
OTLP over gRPC (`4317`) and HTTP (`4318`) and prints batched telemetry through
the Collector debug exporter.

When `ARP_OTEL_ENDPOINT` is set, the API exports FastAPI request spans and the
worker exports processing/tool-execution spans plus queue outcome counters.
The Compose stack sets the endpoint to `otel-collector:4317`; on a host process
use `localhost:4317`. Product traces remain in PostgreSQL for the console and
are separate from this runtime telemetry stream.

The debug exporter is appropriate only for an isolated local environment. Do
not send credentials, authorization headers, full request bodies, or customer
data to it. A production deployment needs a protected backend exporter,
retention controls, and stronger project-level redaction before telemetry
leaves the application boundary.
