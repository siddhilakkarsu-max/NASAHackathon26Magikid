"""
Claude (Anthropic API) as the planner's AI model. search.py uses it whenever ANTHROPIC_API_KEY is set, for the
same three jobs as the OpenRouter / local-model path: reading a goal (JSON), explaining a plan, labelling the map.

    ANTHROPIC_API_KEY   the key (keep it in the server's ai.env, never in git)
    CLAUDE_MODEL        default claude-haiku-5-5
    CLAUDE_EFFORT       default low (fast answers; the page streams the model's summarized thinking)
"""
import os
import time

import anthropic

MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")
EFFORT = os.environ.get("CLAUDE_EFFORT", "low")
_client = None


def enabled():
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def _api():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(timeout=90.0, max_retries=2)
    return _client


def _split(messages):
    """OpenAI-style message list -> (system text, user/assistant messages) for the Messages API."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    return system, [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]


def _request(messages, schema, max_tokens, think):
    system, msgs = _split(messages)
    kw = dict(model=MODEL, max_tokens=max_tokens, messages=msgs, output_config={"effort": EFFORT},
              thinking={"type": "adaptive", "display": "summarized"} if think else {"type": "disabled"})
    if system:
        kw["system"] = system
    if schema:
        kw["output_config"]["format"] = {"type": "json_schema", "schema": schema}
    return kw


def _error(e):
    """A short reason for the page (the technical part after ' | ')."""
    if isinstance(e, anthropic.AuthenticationError):
        return "The AI is unavailable right now. | Claude API: the API key was rejected."
    if isinstance(e, anthropic.PermissionDeniedError):
        return "The AI is unavailable right now. | Claude API: this key may not use " + MODEL + "."
    if isinstance(e, anthropic.RateLimitError):
        return "The AI is busy; try again in a minute. | Claude API: rate limited."
    if isinstance(e, anthropic.APIStatusError):
        return f"The AI couldn't answer. | Claude API error {e.status_code}: {e.message}"
    if isinstance(e, anthropic.APIConnectionError):
        return "The AI couldn't be reached. | Claude API: connection failed."
    return f"The AI couldn't answer. | {type(e).__name__}: {e}"


def stream(messages, schema=None, max_tokens=4000, think=True, think_seconds=None):
    """Stream an answer: yields ("reasoning", text) for Claude's summarized thinking and ("content", text) for the
    answer, then ("done", answer, model) or ("error", reason). If thinking runs longer than think_seconds before
    the answer starts, it is stopped and the answer is asked for again without thinking."""
    parts, t_think, cut, final = [], None, False, None
    try:
        with _api().messages.stream(**_request(messages, schema, max_tokens, think)) as s:
            for event in s:
                if event.type == "content_block_delta":
                    if event.delta.type == "thinking_delta" and event.delta.thinking:
                        t_think = t_think or time.time()
                        yield ("reasoning", event.delta.thinking)
                    elif event.delta.type == "text_delta" and event.delta.text:
                        parts.append(event.delta.text)
                        yield ("content", event.delta.text)
                if think_seconds and not parts and t_think and time.time() - t_think > think_seconds:
                    cut = True                       # leaving the block closes the stream
                    break
            if not cut:
                final = s.get_final_message()
    except anthropic.BadRequestError as e:
        if schema:                                   # a schema the API won't take: ask for JSON without it
            yield from stream(messages, None, max_tokens, think, think_seconds)
            return
        yield ("error", _error(e))
        return
    except anthropic.APIError as e:
        yield ("error", _error(e))
        return
    if cut:
        yield ("reasoning", f"\n\n[Thinking stopped after {think_seconds:.0f} s; answering now.]")
        yield from stream(messages, schema, max_tokens, think=False)
        return
    if final.stop_reason == "refusal":
        yield ("error", "The AI declined to answer this one. | Claude API: stop_reason refusal.")
        return
    yield ("done", "".join(parts), final.model)


def write(messages, schema=None, max_tokens=3000):
    """One quick answer without thinking: (text, model) or raises anthropic.APIError."""
    r = _api().messages.create(**_request(messages, schema, max_tokens, think=False))
    if r.stop_reason == "refusal":
        raise ValueError("the AI declined to answer")
    return "".join(b.text for b in r.content if b.type == "text").strip(), r.model
