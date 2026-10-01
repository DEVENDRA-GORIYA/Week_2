# Prompt patterns

Helix keeps prompts as named templates in `backend/app/prompts/library.py`. The API serves them at `GET /api/v1/prompts`, so the text that shapes the model is part of the contract rather than a string hidden in a route.

## Role, then constraints

Each template starts with a role and then the rules that role has to follow.

`concise_assistant` is a short assistant that must not invent facts and must say when it is unsure. `support_agent` may draft a reply, and it is told not to promise refunds or other actions the message does not verify.

The role is the job. The constraints are the failure modes we care about.

## One output contract

Extraction prompts name every key, the allowed values, and the length limits that the Pydantic model enforces. They also say "no markdown" and "do not add keys", because small models like to wrap JSON in a sentence or a code fence.

The parser still strips a single ```json fence, so a model that ignores "no markdown" can succeed. The instruction is there so the model has a chance to get it right on the first try. The parser is the safety net, not the spec.

Inbound HTTP bodies are stricter than model output. Clients get `extra=forbid`. Model JSON drops unknown keys and then checks types, enums, and ranges. A local model adding `"explanation"` should not fail a ticket that otherwise matches.

## Retry with the validator's words

If parsing or validation fails, Helix appends the model output and a short description of the first Pydantic error, then asks for JSON only. That is one retry. The second failure is a `422`, and the tokens from both calls are still billed.

Sending the validator message back is more useful than repeating the original prompt. The model sees the specific field that broke.

## Tool protocol

Tool use is another output contract, not a hidden function-call channel. The system prompt lists the tools and requires one JSON object:

```json
{"action": "tool", "name": "calculator", "arguments": {"expression": "2*(3+4)"}}
```

or

```json
{"action": "final", "content": "The answer is 14."}
```

Helix validates that object before it runs anything. The calculator accepts only numbers and `+ - * /` with parentheses. A tool error is fed back as JSON so the next turn can correct it. The loop stops at `MAX_TOOL_STEPS`.

When the model never emits JSON, Helix returns the prose and sets `finish_reason` to `degraded`. That is an explicit quality tradeoff: a 135M local model stays usable, and the response tells you the protocol was not followed. A larger local model, or Groq's free-tier instruct model, follows the same prompt more reliably. The service code does not change.

## What we do not put in the prompt

- We do not ask the model to invent token counts. Usage comes from the provider, or from a documented character estimate (`about 4 characters per token`) in `app/core/tokens.py`.
- We do not log the prompt. The template text is already in the repo and on `GET /prompts`.
- We do not let the user replace the tool protocol when tools are enabled. Their messages are appended after it.

## Adding a prompt

1. Add a `PromptTemplate` in `library.py`.
2. If it is an extraction task, add a Pydantic model and include the task name in `ExtractTask`.
3. The catalog endpoint and the service pick it up from that dictionary. There is no second copy of the prompt in the route.
