# STYLE_GUIDE

## Authoring Principle

**Write in the language people think, not the language psychologists use to describe thinking.**

This applies most critically to `## Indicators`. Each indicator must describe behavior or reasoning as it appears in text produced by someone exhibiting the bias — not as an analyst would characterize it from the outside.

| Before (analyst register) | After (thinking register) |
|---|---|
| Dismisses contradictory evidence as flawed or biased | Explains away contradictory evidence as unreliable or exceptional |
| Confidence intervals too narrow relative to outcome distributions | States an outcome as certain or inevitable without acknowledging the possibility of being wrong |
| Risk and benefit estimates moving in opposite directions | Uses the strength of a feeling as a reason to act rather than examining evidence about consequences |

The test: could this sentence appear (or nearly appear) in a story told by someone reasoning through a decision? If not, rewrite it.

## Tone
Factual, no hedging. State what the bias is. No "it could be" or "some researchers suggest."

## Section Length Limits
- **Definition**: ≤250 words
- **Examples**: ≤350 words — must cover ≥2 distinct domains (finance, medicine, politics, academia, law, sport, technology, journalism, etc.)
- **Indicators**: ≤10 bullets
- **False Positives**: ≤10 bullets — must be substantive, not placeholders
- **Related Biases**: comma-separated display names

## Domain Label Vocabulary

When adding domain-tagged example paragraphs, use only these labels in `[Label]` prefix format:

`Political`, `Social`, `Management`, `Consumer`, `Legal`, `Medical`

Multi-word labels, hyphens, and ampersands are not supported. One label per paragraph. Non-tagged paragraphs have no label.

## Naming Conventions
- Filename = bias_id in snake_case: `confirmation_bias.md`
- First heading = display name: `# Confirmation Bias`

## Mandatory Sections
All five sections required. Missing `## False Positives` causes the indexer to halt.
