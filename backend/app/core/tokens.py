def estimate_tokens(text: str) -> int:
    """Approximate token count. English is roughly four characters per token.

    Provider-reported usage replaces this when the model server sends it.
    """
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def estimate_messages(messages: list[dict[str, str]]) -> int:
    blob = "\n".join(f"{message['role']}: {message['content']}" for message in messages)
    return estimate_tokens(blob)
