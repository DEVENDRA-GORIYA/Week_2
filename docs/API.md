# API contracts

Base URL: `http://127.0.0.1:8000`

Version prefix: `/api/v1`

Interactive schema: `/docs`

Authenticated routes expect `Authorization: Bearer <access_token>`.

## Errors

Every error uses the same body:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": []
  }
}
```

`details` is present for request validation only.

| HTTP | `code` | When |
|------|--------|------|
| 401 | `unauthorized` | Missing, expired, or wrong token, or bad login |
| 403 | `forbidden` | Admin route called by a normal user |
| 404 | `not_found` | Unknown prompt id |
| 409 | `conflict` | Email already registered |
| 422 | `validation_error` | Request body failed Pydantic validation |
| 422 | `schema_violation` | Model output failed the task schema, or a chat prompt id points at an extract task |
| 429 | `rate_limited` | Per-user requests per minute exceeded |
| 429 | `budget_exceeded` | Daily token budget exceeded |
| 502 | `provider_error` | Model server returned an error payload |
| 503 | `provider_unavailable` | Model server is unreachable, or `/ready` and the model is not loaded |
| 504 | `provider_unavailable` | Model request timed out |

Request models set `extra=forbid`. A field the contract does not list is a 422.

## Health

### `GET /api/v1/health`

Public. Process is up. Does not check the model.

```json
{"status": "ok", "service": "helix", "version": "1.0.0"}
```

### `GET /api/v1/ready`

Public. 200 when the configured model is listed by the model server. 503 otherwise.

```json
{"status": "ready", "provider": "ollama", "model": "smollm2:135m"}
```

### `GET /api/v1/models`

Authenticated. Same readiness check, plus the capabilities this service exposes.

```json
{
  "provider": "ollama",
  "model": "smollm2:135m",
  "ready": true,
  "capabilities": ["chat", "structured_output", "tools"]
}
```

## Auth

### `POST /api/v1/auth/register`

`201`

```json
{"email": "ada@example.com", "password": "password123"}
```

Password length is 8 to 72 characters. Email is stored lowercase. Emails listed in `ADMIN_EMAILS` receive `role: admin`.

### `POST /api/v1/auth/login`

`200`. Same body as register. Wrong email or password returns the same 401 message.

### Response

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": {"id": 1, "email": "ada@example.com", "role": "user"}
}
```

### `GET /api/v1/auth/me`

`200` with the `user` object above.

## Prompts

### `GET /api/v1/prompts`

Authenticated. Returns the catalog, including the system text, so the contract is visible.

```json
[
  {
    "id": "support_ticket",
    "kind": "extract",
    "title": "Support ticket",
    "description": "Classify a customer message into a ticket.",
    "system": "..."
  }
]
```

Chat ids: `concise_assistant`, `support_agent`.

Extract ids: `support_ticket`, `sentiment`, `action_items`.

## Provider switch

### `GET /api/v1/provider`

Authenticated. Returns the active backend and the options this server can use.

```json
{
  "active": "groq",
  "model": "qwen/qwen3.8-27b",
  "ready": true,
  "options": [
    {
      "name": "ollama",
      "label": "Ollama (local)",
      "model": "smollm2:135m",
      "configured": true
    },
    {
      "name": "groq",
      "label": "Groq (free API)",
      "model": "qwen/qwen3.8-27b",
      "configured": true
    }
  ]
}
```

`configured` is false for Groq when `GROQ_API_KEY` is missing.

### `PUT /api/v1/provider`

Authenticated. Switches the live provider without restarting the process.

```json
{"provider": "groq"}
```

Allowed values: `ollama`, `groq`, and `openai_compatible` when configured.

Response shape matches `GET /provider`. The change lasts until the API process exits; the next cold start still uses `INFERENCE_PROVIDER` from `.env`.

## Completions

### `POST /api/v1/completions`

Authenticated. Headers on success:

- `X-RateLimit-Limit`
- `X-RateLimit-Remaining`

```json
{
  "messages": [
    {"role": "user", "content": "What is 2*(3+4)?"}
  ],
  "temperature": 0.2,
  "max_tokens": 1024,
  "prompt_id": "concise_assistant",
  "tools_enabled": true
}
```

| Field | Rules |
|-------|--------|
| `messages` | 1 to 20. Roles: `system`, `user`, `assistant`. Each content is 1 to 8000 characters. At least one `user` message. |
| `temperature` | 0 to 2. Default 0.2. |
| `max_tokens` | 1 to 4096. Default 1024. Raise this for long answers (recipes, guides). |
| `prompt_id` | Optional chat prompt. Extract ids are rejected. |
| `tools_enabled` | Default false. |

```json
{
  "id": "cmpl_0123456789abcdef",
  "model": "smollm2:135m",
  "provider": "ollama",
  "output": "The answer is 14.",
  "finish_reason": "stop",
  "usage": {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52},
  "latency_ms": 840.2,
  "tool_trace": [
    {
      "name": "calculator",
      "arguments": {"expression": "2*(3+4)"},
      "result": "{\"expression\": \"2*(3+4)\", \"value\": 14}"
    }
  ]
}
```

`finish_reason`:

| Value | Meaning |
|-------|---------|
| `stop` | Normal answer, or a final tool-protocol answer |
| `tool_limit` | The tool loop hit `MAX_TOOL_STEPS` and then produced a final answer |
| `degraded` | The model ignored the JSON tool protocol and the prose was returned as-is |

Tools the model may call:

| Name | Arguments |
|------|-----------|
| `calculator` | `{"expression": "numbers with + - * / and parentheses"}` |
| `utc_now` | `{}` |
| `word_stats` | `{"text": "string"}` |

## Extract

### `POST /api/v1/extract`

Authenticated. Temperature is fixed at 0 inside the service. One automatic retry on schema failure.

```json
{
  "task": "support_ticket",
  "text": "I was charged twice for the same invoice and need it reversed.",
  "max_tokens": 400
}
```

`task` is `support_ticket`, `sentiment`, or `action_items`.

```json
{
  "id": "ext_0123456789abcdef",
  "task": "support_ticket",
  "result": {
    "category": "billing",
    "priority": "high",
    "summary": "Customer was charged twice and wants a reversal.",
    "customer_intent": "Get the duplicate charge reversed."
  },
  "model": "smollm2:135m",
  "provider": "ollama",
  "usage": {"prompt_tokens": 30, "completion_tokens": 40, "total_tokens": 70},
  "latency_ms": 900.0,
  "retries": 0
}
```

Result shapes:

**support_ticket**

- `category`: `billing` \| `technical` \| `account` \| `other`
- `priority`: `low` \| `medium` \| `high`
- `summary`: string, 1–300 characters
- `customer_intent`: string, 1–300 characters

**sentiment**

- `label`: `positive` \| `neutral` \| `negative`
- `confidence`: number from 0 to 1
- `rationale`: string, 1–500 characters

**action_items**

- `summary`: string
- `items`: up to 10 objects of `{owner, task, due}`. `due` may be null.

Labels are lowercased before validation, so `"Negative"` still matches.

## Usage

### `GET /api/v1/usage/me`

Authenticated. Totals are for the current UTC day. `events` is the latest 50 calls, newest first. `created_at` is UTC with a `Z` suffix.

```json
{
  "day_tokens": 70,
  "daily_budget": 20000,
  "remaining_tokens": 19930,
  "events": [
    {
      "id": 1,
      "endpoint": "completions",
      "provider": "ollama",
      "model": "smollm2:135m",
      "prompt_tokens": 40,
      "completion_tokens": 12,
      "latency_ms": 840.2,
      "created_at": "2026-09-28T08:00:00Z"
    }
  ]
}
```

### `GET /api/v1/usage/summary`

Admin only. Totals across all users for the current UTC day.

```json
{
  "day_requests": 4,
  "day_prompt_tokens": 100,
  "day_completion_tokens": 80,
  "day_total_tokens": 180,
  "daily_budget_per_user": 20000
}
```

## curl

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/register \
  -H 'content-type: application/json' \
  -d '{"email":"ada@example.com","password":"password123"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -s http://127.0.0.1:8000/api/v1/completions \
  -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":"Explain JWT in one sentence."}]}'
```
