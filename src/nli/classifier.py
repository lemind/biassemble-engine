import time
from dataclasses import dataclass

import structlog
import torch
from transformers import pipeline as hf_pipeline

from src.config import settings

log = structlog.get_logger()


@dataclass
class NLIResult:
    scores: dict[str, float]
    raw_scores: dict[str, dict[str, float]]
    latency_ms: float
    truncated_premise: bool


class NLIClassifier:
    """Zero-shot NLI classifier over 38 bias hypotheses.

    Uses one batched forward pass for all hypotheses — cheaper than the pipeline's
    per-pair loop and gives us the full entailment/neutral/contradiction triplet
    needed for raw_scores without a second forward pass.
    """

    def __init__(self) -> None:
        _pipe = hf_pipeline("zero-shot-classification", model=settings.nli_model, device=-1)
        self._tokenizer = _pipe.tokenizer
        self._model = _pipe.model
        self._model.eval()
        id2label = self._model.config.id2label
        if not isinstance(next(iter(id2label.keys())), int):
            raise RuntimeError(
                f"NLI model id2label has non-int keys: {list(id2label.keys())!r} — "
                "update NLIClassifier to handle string keys"
            )
        self._entailment_idx = next(
            i for i, label in id2label.items() if "entail" in label.lower()
        )
        self._id2label = id2label

    def classify(self, story: str, hypotheses: list[tuple[str, str]]) -> NLIResult:
        """Score story against all hypotheses in one batched forward pass.

        hypothesis_template="{}" is hardcoded — hypothesis text IS the NLI premise,
        no template expansion. multi_label=True semantics: independent softmax per pair.
        """
        t0 = time.monotonic()

        premises = [story] * len(hypotheses)
        hyp_texts = [h for _, h in hypotheses]

        # Truncation threshold is story-specific per hypothesis due to varying hypothesis
        # lengths. Use the longest hypothesis as the worst case so the flag is always
        # accurate — story tokens that survive in the shortest-hypothesis pair also survive
        # in the longest.
        max_hyp_tokens = max(
            len(self._tokenizer.encode(h, add_special_tokens=False)) for h in hyp_texts
        )
        max_story_tokens = 512 - max_hyp_tokens - 3  # [CLS] story [SEP] hypothesis [SEP]

        tokens = self._tokenizer.encode(story, add_special_tokens=False)
        truncated_premise = len(tokens) > max_story_tokens
        if truncated_premise:
            story = self._tokenizer.decode(tokens[:max_story_tokens], skip_special_tokens=True)
            log.warning("nli_premise_truncated", original_tokens=len(tokens), max_allowed=max_story_tokens)
            premises = [story] * len(hypotheses)

        inputs = self._tokenizer(
            premises,
            hyp_texts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=512,
        )
        with torch.no_grad():
            logits = self._model(**inputs).logits

        probs = torch.softmax(logits, dim=-1)

        scores: dict[str, float] = {}
        raw_scores: dict[str, dict[str, float]] = {}
        for i, (bias_id, _) in enumerate(hypotheses):
            p = probs[i]
            score = float(p[self._entailment_idx])
            # Multi-phrasing: keep max entailment score across phrasings.
            if score > scores.get(bias_id, -1.0):
                scores[bias_id] = score
                raw_scores[bias_id] = {
                    self._id2label[j]: float(p[j]) for j in range(probs.shape[1])
                }

        return NLIResult(
            scores=scores,
            raw_scores=raw_scores,
            latency_ms=(time.monotonic() - t0) * 1000,
            truncated_premise=truncated_premise,
        )
