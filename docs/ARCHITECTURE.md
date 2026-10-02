# System architecture

Helix is an inference gateway. The HTTP service, the model runtime, and the usage database are separate so each one can change without dragging the others along.

```text
┌──────────────────┐     HTTP/JSON      ┌──────────────────────────┐
│  Streamlit UI    │ ◄────────────────► │  FastAPI                 │
│  (requests)      │   Bearer JWT       │  /api/v1                 │
└──────────────────┘                    └────────────┬─────────────┘
                                                     │
                     ┌───────────────────────────────┼───────────────────────────┐
                     ▼                               ▼                           ▼
          ┌────────────────────┐         ┌─────────────────────┐    ┌──────────────────────┐
          │ SQLite             │         │ InferenceService    │    │ OpenAI-compatible    │
          │ users              │         │ prompt + tool loop  │    │ provider             │
          │ usage_events       │         │ Pydantic validation │    │ Ollama or Groq       │
          └────────────────────┘         └──────────┬──────────┘    └──────────────────────┘
                                                    │
                                         ┌──────────▼──────────┐
                                         │ Tool registry       │
                                         │ calculator          │
                                         │ utc_now             │
                                         │ word_stats          │
                                         └─────────────────────┘
```

## Why the model is outside the API image

A local open model is the default, but the weights and the runtime (Ollama) are not baked into the API image. That keeps the image small, makes the build reproducible, and lets the same service talk to:

- Ollama on the laptop or in Compose (`INFERENCE_PROVIDER=ollama`)
- Groq's free tier (`INFERENCE_PROVIDER=groq`)
- Any other OpenAI-compatible server (`INFERENCE_PROVIDER=openai_compatible`)

`OpenAICompatibleProvider` is the outbound client. Routes never import a vendor SDK. FastAPI injects the active provider through `app.state` and `Depends`, so tests replace it with a scripted double and never download a model.

## Backend layers

| Layer | Responsibility | Location |
|-------|----------------|----------|
| Routes | Status codes, auth dependencies, rate-limit headers | `app/api/v1/` |
| Schemas | Inbound contracts (`extra=forbid`) and response models | `app/schemas/` |
| Services | Auth, the inference loop, token accounting | `app/services/` |
| Providers | HTTP chat against the model server | `app/providers/` |
| Prompts | Named system prompts and extraction schemas | `app/prompts/` |
| Tools | Argument validation and sandboxed execution | `app/tools/` |
| Core | JWT, password hashing, errors, rate limit | `app/core/` |
| Models | Users and usage events | `app/models/` |

HTTP stays out of SQL. SQL stays out of the model client.

## Request path

1. `RequestContextMiddleware` assigns `X-Request-ID`.
2. Pydantic v2 rejects unknown fields, oversized strings, and out-of-range sampling settings before a service runs.
3. JWT routes resolve the user from the token `sub` claim, then load that user from the database. The role in the token is not trusted for authorization.
4. Inference routes take one slot from the in-process sliding window, then check the caller's remaining daily token budget.
5. `InferenceService` builds the message list, calls the provider with `httpx`, and validates model output.
6. A usage row is written even when schema validation fails, because the model still spent tokens.
7. The response includes provider name, model id, token counts, and latency.

Prompt text is not written to the logs. The log line is endpoint, user id, provider, model, token total, and latency.

## Authentication

- `POST /api/v1/auth/register` and `POST /api/v1/auth/login` return a bearer token.
- Passwords are hashed with bcrypt. Hashing runs in a worker thread so it does not block the event loop.
- Unknown emails still run a dummy bcrypt check so the failure timing stays close to a real password check.
- `ADMIN_EMAILS` grants the admin role at registration. Admins can read `GET /api/v1/usage/summary`.
- With `DEBUG=false`, startup fails if `SECRET_KEY` is still the development default. Keys shorter than 32 characters are always rejected.

## Structured output

`POST /api/v1/extract` asks the model for one JSON object, parses it, and validates it with a Pydantic model (`SupportTicket`, `SentimentResult`, or `ActionItems`). Unknown keys on model output are dropped. Required fields, enums, and ranges stay strict.

If validation fails, Helix retries once and includes the validator message in the follow-up turn. A second failure is `422 schema_violation`. Inbound API bodies use `extra=forbid`, so clients cannot sneak extra fields past the contract.

## Tool calling

When `tools_enabled` is true, a system prompt requires a single JSON decision:

- `{"action":"tool","name":"...","arguments":{...}}`
- `{"action":"final","content":"..."}`

The service runs at most `MAX_TOOL_STEPS` rounds (default 3). Tool arguments are validated, then executed. The calculator only evaluates numbers and `+ - * /` through `ast`. It does not call `eval`. A bad tool call is returned to the model as an error object so the loop can continue.

If a small local model answers in prose instead of JSON, the response is still returned, with `finish_reason: degraded`. That keeps a 135M model usable while the contract stays explicit for models that follow the protocol.

## Token economics

Provider `usage.prompt_tokens` and `usage.completion_tokens` are stored when the server sends them. If it does not, Helix estimates tokens as `ceil(characters / 4)` and labels that behavior in the prompt docs. The daily budget is checked before each model call using the estimate of the outgoing prompt, so a huge prompt is rejected before it is sent. The completion of the last allowed call can still land slightly over the budget. That overshoot is recorded and the next call is refused.

The rate limit is a per-user sliding window in this process. Running several API workers needs a shared store. Compose starts one API process on purpose.

## Data

SQLite through SQLAlchemy's async engine (`sqlite+aiosqlite`). Two tables:

- `users` — email, password hash, role
- `usage_events` — endpoint, provider, model, token counts, latency, UTC timestamp

Indexes: unique email, and `(user_id, created_at)` on usage events. Timestamps are stored as naive UTC.

## Failure behavior

| Situation | Result |
|-----------|--------|
| Model server down | `503 provider_unavailable` on chat. `/health` stays 200. `/ready` stays 503. |
| Model output is not the schema | One retry, then `422 schema_violation` |
| Rate limit | `429 rate_limited` and `Retry-After: 60` |
| Daily budget | `429 budget_exceeded` |
| Bad or missing JWT | `401 unauthorized` |

## Containers

`backend/Dockerfile` is a two-stage build. The builder installs locked dependencies with uv. The runtime image copies the virtualenv, drops to a non-root user, and serves Uvicorn. Compose adds Ollama and the Streamlit UI. Pull the model after the stack is up (`scripts/pull_model.sh`). Weights are stored in the `ollama-data` volume, not in the API image.
