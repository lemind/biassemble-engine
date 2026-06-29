from pathlib import Path

from src.config import settings
from src.indexing.sources.base import KnowledgeSource, RawDocument

KNOWLEDGE_DIR = Path("knowledge")

_SECTION_MAP = {
    "definition": "definition",
    "examples": "examples",
    "example": "examples",
    "indicators": "indicators",
    "indicator": "indicators",
    "false positives": "false_positives",
    "false positive": "false_positives",
    "related biases": "related_biases",
    "related bias": "related_biases",
}


class TaxonomySource(KnowledgeSource):
    def __init__(self, knowledge_dir: Path = KNOWLEDGE_DIR) -> None:
        self._knowledge_dir = knowledge_dir

    @property
    def name(self) -> str:
        return "taxonomy"

    @property
    def version(self) -> str:
        return settings.taxonomy_version

    def load(self) -> list[RawDocument]:
        docs: list[RawDocument] = []
        for path in sorted(self._knowledge_dir.glob("*.md")):
            if path.name.upper() == "STYLE_GUIDE.MD":
                continue
            docs.extend(self._parse(path))
        return docs

    def _parse(self, path: Path) -> list[RawDocument]:
        bias_id = path.stem
        lines = path.read_text(encoding="utf-8").splitlines()

        sections: dict[str, list[str]] = {}
        current: str | None = None

        for line in lines:
            if line.startswith("## "):
                current = line[3:].strip()
                sections[current] = []
            elif current is not None:
                sections[current].append(line)

        docs: list[RawDocument] = []
        for heading, text_lines in sections.items():
            chunk_type = _SECTION_MAP.get(heading.lower())
            if chunk_type is None:
                continue
            text = "\n".join(text_lines).strip()
            if not text:
                continue
            docs.append(RawDocument(
                bias_id=bias_id,
                chunk_type=chunk_type,
                text=text,
                source=self.name,
                metadata={"source_file": path.name},
            ))

        return docs
