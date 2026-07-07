import re
from pathlib import Path

from src.config import settings
from src.indexing.sources.base import KnowledgeSource, RawDocument

KNOWLEDGE_DIR = Path("knowledge")

_DOMAIN_RE = re.compile(r"^\[([A-Za-z]+)\]\s*")


def _extract_domain(text: str) -> str | None:
    m = _DOMAIN_RE.match(text)
    return m.group(1).lower() if m else None


def _strip_domain_label(text: str) -> str:
    return _DOMAIN_RE.sub("", text)


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
    "story patterns": "story_patterns",
    "story pattern": "story_patterns",
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

        # Capture display name from the first # heading line.
        name_line = next((l for l in lines if l.startswith("# ")), "")
        display_name = name_line[2:].strip() or bias_id.replace("_", " ").title()

        sections: dict[str, list[str]] = {}
        current: str | None = None

        for line in lines:
            if line.startswith("## "):
                heading = line[3:].strip()
                if heading in sections:
                    print(f"taxonomy WARNING: {path.name}: duplicate heading '## {heading}' — content will be overwritten")
                current = heading
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

            if chunk_type in ("examples", "story_patterns"):
                paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
                for i, para in enumerate(paragraphs):
                    domain = _extract_domain(para)
                    clean = _strip_domain_label(para)
                    meta: dict = {"source_file": path.name, "display_name": display_name}
                    if domain:
                        meta["domain"] = domain
                    docs.append(RawDocument(
                        bias_id=bias_id,
                        chunk_type=chunk_type,
                        text=clean,
                        source=self.name,
                        metadata=meta,
                        paragraph_index=i,
                    ))
            else:
                docs.append(RawDocument(
                    bias_id=bias_id,
                    chunk_type=chunk_type,
                    text=text,
                    source=self.name,
                    metadata={"source_file": path.name, "display_name": display_name},
                    paragraph_index=0,
                ))

        return docs
