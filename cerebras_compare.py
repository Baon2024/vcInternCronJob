import os
import time

from cerebras.cloud.sdk import Cerebras
from dotenv import load_dotenv
from IPython.display import HTML, display
from openai import OpenAI
from rich import print

load_dotenv()

CEREBRAS_API_KEY = os.environ["CEREBRAS_API_KEY"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
CEREBRAS_MODEL = "gpt-oss-120b"
OPENAI_MODEL = "gpt-4.1-mini"

cerebras_client = Cerebras(api_key=CEREBRAS_API_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

prompt = """
Explain in 5 short bullets why fast inference changes 
product design for LLM applications."""

cerebras_start = time.perf_counter()
cerebras_response = cerebras_client.chat.completions.create(
    model=CEREBRAS_MODEL,
    messages=[{"role": "user", "content": prompt}],
    max_completion_tokens=220,
)
total_time = time.perf_counter() - cerebras_start
tokens_per_second = round(cerebras_response.usage.completion_tokens / total_time, 1)

print(cerebras_response)
print(f"Total Time: {total_time:.3f}s")
print(f"Tokens per second: {tokens_per_second:.3f}s")

openai_start = time.perf_counter()
openai_response = openai_client.chat.completions.create(
    model=OPENAI_MODEL,
    messages=[{"role": "user", "content": prompt}],
    max_tokens=220,
)
total_time = time.perf_counter() - openai_start
tokens_per_second = round(openai_response.usage.completion_tokens / total_time, 1)

print(openai_response)
print(f"Total Time: {total_time:.3f}s")
print(f"Tokens per second: {tokens_per_second:.3f}s")

##
from pydantic import BaseModel

class StreamMetrics(BaseModel):
    ttft: float
    total_time: float
    tokens_per_second: float

def stream_chat(client, model, prompt, max_tokens=220):
    """Stream a chat completion and return (text, StreamMetrics)."""
    # The Cerebras and OpenAI SDKs use different names for the token budget.
    if isinstance(client, Cerebras):
        kwargs = {"max_completion_tokens": max_tokens}
    else:
        kwargs = {"max_tokens": max_tokens}

    start = time.perf_counter()
    ttft = None
    tokens = 0
    chunks = []

    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
        **kwargs,
    )

    for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            if ttft is None:
                ttft = time.perf_counter() - start  # first token arrived
            tokens += 1
            chunks.append(delta)

    total = time.perf_counter() - start  # stream finished
    metrics = StreamMetrics(
        ttft=round(ttft, 3) if ttft is not None else 0.0,
        total_time=round(total, 3),
        tokens_per_second=round(tokens / total, 1) if total else 0.0,
    )
    return "".join(chunks), metrics