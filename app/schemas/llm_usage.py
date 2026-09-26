from dataclasses import dataclass

@dataclass
class LLMUsage:
    provider: str
    model: str
    input_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    output_tokens: int
    total_tokens: int