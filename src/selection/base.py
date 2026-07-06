from typing import Protocol, runtime_checkable


@runtime_checkable
class SelectionStrategy(Protocol):
    def select(self, story: str) -> dict[str, float]:
        """Return {bias_id: score} for all 38 biases. Score is 0.0 if not selected."""
        ...
