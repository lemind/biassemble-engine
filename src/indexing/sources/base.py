from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RawDocument:
    bias_id: str
    chunk_type: str
    text: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)


class KnowledgeSource(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def version(self) -> str: ...

    @abstractmethod
    def load(self) -> list[RawDocument]: ...
