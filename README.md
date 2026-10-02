# Helix

Helix is a containerized FastAPI inference microservice. It exposes versioned API contracts for chat, structured extraction, and tool calls. Routes are protected with JWT. Request and response bodies use Pydantic v2. Models run locally with Ollama, or through a hosted free-tier API such as Groq.

```text
┌──────────────┐   HTTP + JWT    ┌─────────────────────┐
│ Streamlit UI │ ──────────────► │ FastAPI  /api/v1    │
└──────────────┘                 │ auth · inference    │
                                 │ usage · prompts     │
                                 └──────────┬──────────┘
                                            │
                          ┌─────────────────┼──────────────────┐
                          ▼                 ▼                  ▼
                    SQLite users      Per-user rate       Model providers
                    + usage events    limit and daily     Ollama / Groq /
                                      token budget        OpenAI-compatible
```

The API image does not bundle model weights. Inference runs in a separate process or remote API so providers can be swapped without rebuilding the service.

---

## Features

- Register and log in with a JWT bearer token
- Chat completions against a local open model or a hosted API
- Reusable prompts (`concise_assistant`, `support_agent`)
- Structured extraction into validated schemas: support ticket, sentiment, action items
- Tool calls: calculator, UTC clock, word stats (arguments validated before execution)
- Per-user request rate limit and daily token budget
- Usage history for the caller, and a daily summary for admins
- Runtime provider switch (`GET` / `PUT /api/v1/provider`)
- `/ready` reports whether the active model endpoint is reachable

---

## Stack

| Layer | Technology |
|-------|------------|
| API | FastAPI · Pydantic v2 · SQLAlchemy 2 · JWT · bcrypt |
| Model providers | Ollama · Groq · OpenAI-compatible |
| UI | Streamlit · requests |
| Data | SQLite (users and usage events) |
| Tooling | uv · ruff · pytest · Docker multi-stage · GitHub Actions · pre-commit |

---

## Project structure

```text
.
├── backend/app/
│   ├── api/v1/          # HTTP routes
│   ├── core/            # JWT, dependencies, rate limit, errors
│   ├── models/          # users, usage events
│   ├── schemas/         # Pydantic v2 request and response contracts
│   ├── services/        # auth, inference loop, usage accounting
│   ├── providers/       # model clients (Ollama / Groq / OpenAI-compatible)
│   ├── prompts/         # reusable prompt catalog
│   └── tools/           # sandboxed tool registry
├── ui/app.py            # Streamlit client
├── docs/
│   ├── ARCHITECTURE.md
│   ├── API.md
│   └── PROMPTS.md
├── docker-compose.yml
└── README.md
```

---

## Run locally

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
cd backend
uv sync --all-groups
cp .env.example .env
uv run uvicorn app.main:app --reload --port 8000
```

- API docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/api/v1/health
- Readiness: http://127.0.0.1:8000/api/v1/ready

### Local open model (Ollama)

In another terminal:

```bash
ollama pull smollm2:135m
```

Ollama listens on `http://127.0.0.1:11434` by default. That matches `backend/.env.example`. `/api/v1/ready` returns 200 only after the model is pulled. A small model may ignore the JSON tool protocol; Helix then returns the prose with `finish_reason: degraded` instead of failing the request. For clearer tool-calling results, set `OLLAMA_MODEL` to a stronger local model such as `qwen2.5:0.5b` or `llama3.2:1b`.

### Free-tier API (Groq)

Create a key at https://console.groq.com and put this in `backend/.env`:

```bash
INFERENCE_PROVIDER=groq
GROQ_API_KEY=your-key
GROQ_MODEL=qwen/qwen3.8-27b
```

Confirm the model id in the Groq console. Names on the free tier can change.

Restart the API after changing keys. Switch between Ollama and Groq with `PUT /api/v1/provider` or the Streamlit sidebar.

### Any OpenAI-compatible server

```bash
INFERENCE_PROVIDER=openai_compatible
OPENAI_BASE_URL=http://127.0.0.1:8080/v1
OPENAI_API_KEY=not-needed
OPENAI_MODEL=your-model-name
```

This covers llama.cpp server, vLLM, and other OpenAI-compatible hosts.

### Streamlit UI

```bash
python3 -m pip install -r ui/requirements.txt
cd ui
streamlit run app.py
```

App: http://127.0.0.1:8501

Keep the API running. The UI defaults to `http://127.0.0.1:8000`. Override it with `HELIX_API_URL`.

---

## Docker

```bash
docker compose up --build
./scripts/pull_model.sh smollm2:135m
```

| Service | URL |
|---------|-----|
| API | http://localhost:8000 |
| UI | http://localhost:8501 |
| Ollama | http://localhost:11434 |

The first model pull downloads weights and can take a few minutes. Until it finishes, `/api/v1/ready` returns 503 and chat requests fail with a provider error. Health stays 200 either way.

Set a real `SECRET_KEY` before sharing the stack. With `DEBUG=false`, Helix refuses to boot on the development secret.

---

## Tests and lint

No live model server is required. Tests inject a scripted provider.

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

`make test` and `make lint` run the same commands. Pre-commit runs ruff on `backend/`:

```bash
pip install pre-commit
pre-commit install
```

---

## Environment variables

Copy `backend/.env.example` to `backend/.env`.

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | JWT signing secret, at least 32 characters |
| `DEBUG` | When false, the development secret is rejected |
| `ADMIN_EMAILS` | Comma-separated emails that register as `admin` |
| `DATABASE_URL` | Async SQLite URL |
| `INFERENCE_PROVIDER` | `ollama`, `groq`, or `openai_compatible` |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | Local model server |
| `GROQ_API_KEY` / `GROQ_MODEL` | Groq API |
| `OPENAI_BASE_URL` / `OPENAI_MODEL` | Generic OpenAI-compatible server |
| `RATE_LIMIT_RPM` | Per-user requests per minute (this process only) |
| `DAILY_TOKEN_BUDGET` | Per-user tokens per UTC day |
| `HELIX_API_URL` | Base URL the Streamlit app calls |

Do not commit real secrets. `.env` is gitignored.

---

## Demo checklist

1. Confirm `/api/v1/health` and `/api/v1/ready`
2. Register or log in (Streamlit or `/docs`)
3. Send a chat completion and note tokens, latency, and provider
4. Run `/extract` on a short support message
5. Enable tools and ask `2*(3+4)`; show the tool trace
6. Open Usage and confirm rate limit / daily budget fields

---

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [API contracts](docs/API.md)
- [Prompt patterns](docs/PROMPTS.md)

Interactive API reference: `/docs` on the running backend.
