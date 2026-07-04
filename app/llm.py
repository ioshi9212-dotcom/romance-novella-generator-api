from typing import Protocol


class LLMClient(Protocol):
    def generate_json(self, prompt: str) -> dict:
        ...


class NotConfiguredLLM:
    def generate_json(self, prompt: str) -> dict:
        raise RuntimeError(
            "LLM client is not configured in starter v1. "
            "Use manual_gpt or local_stub, or plug your provider here."
        )
