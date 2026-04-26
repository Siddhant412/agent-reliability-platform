# `packages/support-demo`

Customer support demo fixtures, seed data, and deterministic local tool stubs
for the first support-ticket-resolution workflow.

These tools should expose realistic metadata (`is_mutating`, risk level,
schemas, and connector scope) so policy and approval behavior can be tested
without hard-coding toy shortcuts in the runtime.

Current implementation:

- `arp_support_demo.tools.kb_search`
- `arp_support_demo.tools.get_customer_profile`
- `arp_support_demo.tools.get_order`
- `arp_support_demo.tools.execute_tool`

The current tools are read-only and deterministic. They are used by the local
worker to persist `tool_calls`, emit tool spans, and build structured support
ticket output from fixture data.
