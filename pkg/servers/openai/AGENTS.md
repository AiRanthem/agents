# OpenAI Agents API

This directory implements the OpenAI Agents webhook API layer. It owns
protocol behavior and delegates session lifecycle to Manager.

## Protocol Contract

- Verify the raw request body before parsing. Invalid signatures are rejected.
- Map only `environment_connection`, `in_progress`, `idle`, and `failed`
  session events; other events return 2xx and are ignored.
- A 2xx response means the mapped Manager operation was accepted, not that
  the sandbox executor has connected to OpenAI.
- Environment keys never enter Claim parameters, annotations, command args,
  or logs. Connection URLs and environment IDs are non-secret initialization
  data only.

## Ownership

- Authentication is the webhook signing secret. Do not reuse E2B API keys.
- Cleanup polling runs only while this replica is Manager primary.
- Interface rate limiting happens before Manager calls or background work.
