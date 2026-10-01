import os

import requests
import streamlit as st

API_URL = os.getenv("HELIX_API_URL", "http://127.0.0.1:8000").rstrip("/")

st.set_page_config(page_title="Helix", layout="wide")
st.title("Helix")
st.caption("Inference gateway — Ollama, Groq, or Anthropic Claude")


def call(method: str, path: str, token: str | None = None, payload: dict | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        response = requests.request(
            method,
            f"{API_URL}{path}",
            headers=headers,
            json=payload,
            timeout=120,
        )
    except requests.RequestException as exc:
        st.error(f"Could not reach the API at {API_URL}. {exc}")
        return None
    if response.status_code >= 400:
        try:
            body = response.json()
        except ValueError:
            st.error(response.text)
            return None
        error = body.get("error", {})
        message = error.get("message", response.text) if isinstance(error, dict) else response.text
        st.error(message)
        return None
    return response.json()


if "token" not in st.session_state:
    st.session_state.token = None
if "email" not in st.session_state:
    st.session_state.email = ""
if "messages" not in st.session_state:
    st.session_state.messages = []


with st.sidebar:
    st.subheader("Account")
    if st.session_state.token:
        me = call("GET", "/api/v1/auth/me", st.session_state.token)
        if me:
            st.write(me["email"])
            st.caption(me["role"])
        if st.button("Log out"):
            st.session_state.token = None
            st.session_state.messages = []
            st.rerun()
    else:
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        col_a, col_b = st.columns(2)
        if col_a.button("Register", use_container_width=True):
            created = call(
                "POST",
                "/api/v1/auth/register",
                payload={"email": email, "password": password},
            )
            if created:
                st.session_state.token = created["access_token"]
                st.session_state.email = created["user"]["email"]
                st.rerun()
        if col_b.button("Log in", use_container_width=True):
            created = call(
                "POST",
                "/api/v1/auth/login",
                payload={"email": email, "password": password},
            )
            if created:
                st.session_state.token = created["access_token"]
                st.session_state.email = created["user"]["email"]
                st.rerun()

    st.divider()
    st.subheader("Model provider")
    if not st.session_state.token:
        st.caption("Log in to switch providers.")
        try:
            ready = requests.get(f"{API_URL}/api/v1/ready", timeout=5)
        except requests.RequestException:
            st.warning(f"API is not reachable at {API_URL}.")
        else:
            if ready.ok:
                body = ready.json()
                st.success(f"{body['provider']} · {body['model']}")
            else:
                st.warning("Model server is not ready yet.")
    else:
        status = call("GET", "/api/v1/provider", st.session_state.token)
        if status:
            labels = {
                item["name"]: f"{item['label']} — {item['model']}"
                + ("" if item["configured"] else " (not configured)")
                for item in status["options"]
            }
            names = [item["name"] for item in status["options"]]
            current = status["active"] if status["active"] in names else names[0]
            choice = st.radio(
                "Use",
                names,
                index=names.index(current),
                format_func=lambda name: labels.get(name, name),
            )
            if st.button("Switch provider", use_container_width=True):
                if choice == status["active"]:
                    st.info(f"Already using {choice}.")
                else:
                    updated = call(
                        "PUT",
                        "/api/v1/provider",
                        st.session_state.token,
                        {"provider": choice},
                    )
                    if updated:
                        st.success(f"Switched to {updated['active']} · {updated['model']}")
                        st.rerun()
            if status["ready"]:
                st.success(f"Active: {status['active']} · {status['model']}")
            else:
                st.warning(
                    f"Active: {status['active']} · {status['model']} (not ready). "
                    "For Ollama, start it and pull the model."
                )


chat_tab, extract_tab, usage_tab = st.tabs(["Chat", "Extract", "Usage"])

with chat_tab:
    st.checkbox("Enable tools", key="tools_enabled")
    prompt_id = st.selectbox(
        "Prompt",
        ["(none)", "concise_assistant", "support_agent"],
    )
    max_tokens = st.slider(
        "Max reply tokens",
        min_value=128,
        max_value=4096,
        value=1024,
        step=128,
        help="Raise this if answers stop mid-sentence (recipes, long guides).",
    )
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])
            if message.get("meta"):
                st.caption(message["meta"])
            if message.get("trace"):
                with st.expander("Tool trace"):
                    st.json(message["trace"])

    prompt = st.chat_input("Message Helix")
    if prompt:
        if not st.session_state.token:
            st.warning("Register or log in first.")
        else:
            st.session_state.messages.append({"role": "user", "content": prompt})
            payload = {
                "messages": [
                    {"role": item["role"], "content": item["content"]}
                    for item in st.session_state.messages
                    if item["role"] in {"system", "user", "assistant"}
                ],
                "tools_enabled": st.session_state.tools_enabled,
                "max_tokens": max_tokens,
            }
            if prompt_id != "(none)":
                payload["prompt_id"] = prompt_id
            result = call("POST", "/api/v1/completions", st.session_state.token, payload)
            if result:
                usage = result["usage"]
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": result["output"],
                        "trace": result["tool_trace"],
                        "meta": (
                            f"{result['finish_reason']} · {usage['total_tokens']} tokens · "
                            f"{result['latency_ms']} ms · {result['provider']}/{result['model']}"
                        ),
                    }
                )
                st.rerun()
            else:
                st.session_state.messages.pop()

with extract_tab:
    task = st.selectbox("Task", ["support_ticket", "sentiment", "action_items"])
    text = st.text_area("Text", height=180)
    if st.button("Extract"):
        if not st.session_state.token:
            st.warning("Register or log in first.")
        elif not text.strip():
            st.warning("Enter some text.")
        else:
            result = call(
                "POST",
                "/api/v1/extract",
                st.session_state.token,
                {"task": task, "text": text},
            )
            if result:
                st.json(result["result"])
                st.caption(
                    f"retries {result['retries']} · {result['usage']['total_tokens']} tokens · "
                    f"{result['latency_ms']} ms · {result['provider']}/{result['model']}"
                )

with usage_tab:
    if not st.session_state.token:
        st.info("Log in to see token usage.")
    else:
        usage = call("GET", "/api/v1/usage/me", st.session_state.token)
        if usage:
            left, middle, right = st.columns(3)
            left.metric("Used today", usage["day_tokens"])
            middle.metric("Daily budget", usage["daily_budget"])
            right.metric("Remaining", usage["remaining_tokens"])
            if usage["events"]:
                st.dataframe(usage["events"], use_container_width=True)
            else:
                st.info("No inference calls yet today.")
