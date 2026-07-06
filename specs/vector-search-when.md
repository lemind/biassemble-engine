# When vector search is (and isn't) the right tool

Vector search does one thing: finds text that talks about similar things, by meaning, without exact word matching. Use it when nearness-of-meaning IS your question. Don't use it when your question is recognition (which pattern is this?) or lookup (give me record #12).

Three situations in biassemble, three verdicts:

## 1. Picking which biases fit a story (consumer flow)

Wrong tool for the primary signal. The question isn't "find similar text" — it's "recognize a reasoning pattern."

For topic-shaped biases it accidentally works: a story about doubling down on a bad investment lands near sunk-cost chunks, because the words are neighbors. That's why positive Recall@5 was 0.667, not zero — vector search was carrying the topical biases fine.

For tone-shaped biases like overconfidence, the signal is *how* the person talks ("I know how these go"), not *what* they talk about. Embeddings encode the what. Three rounds of content work in spec-002 moved nothing: improving a map of topics while the target was a pattern of tone.

Hence ADR-003: NLI zero-shot classification (recognition) takes over as primary selection signal. Vector search stays as a secondary union-boost signal because:
- v1 hypotheses are untested; NLI misses aren't guaranteed fixable by better hypotheses alone
- Topic-shaped biases are genuinely better served by nearness
- Two signals with independent failure modes catch more together than either alone
- The code already exists; T-eval-1 tests NLI-alone — if it passes all gates solo, set w_vec=0

Never remove a working signal on reasoning alone the week before the measurement that settles it.

## 2. Finding passages in a customer's documents (b2b audit)

Exactly the right tool, irreplaceable. The question really is "where in this 200-page 10-K is text about Q3 European revenue?" The corpus is arbitrary, different every engagement, and claim wording never matches filing wording exactly ("sales in the EU segment" vs "European revenue"). Meaning-based search is the only mechanism that bridges that gap. No classifier can exist here — there are no fixed classes. This is why pgvector infrastructure stays regardless of what happens to the taxonomy path.

## 3. Fetching full bias documents once selection is done

Never needed. You know the IDs — that's a plain database lookup. It only looked like a vector-search job because selection and fetching were fused in the original pipeline.
