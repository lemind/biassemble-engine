from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg
from fastapi import FastAPI

from pathlib import Path

import structlog

from src.api.routes import retrieve
from src.config import settings
from src.db.queries import ROSTER_QUERY
from src.observability import configure_logging
from src.providers.sentence_transformer import SentenceTransformerProvider
from src.schemas.response import BiasResult
from src.nli.classifier import NLIClassifier
from src.nli.hypothesis_loader import load_hypotheses
from src.selection.nli_union import NLIUnionStrategy
from src.selection.vector_only import VectorOnlyStrategy


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging(settings.log_level)
    provider = SentenceTransformerProvider(settings.embedding_model)
    if provider.dimension != settings.embedding_dimension:
        raise RuntimeError(
            f"Embedding dimension mismatch: "
            f"model={provider.dimension}, config={settings.embedding_dimension}"
        )
    try:
        # statement_cache_size=0 required: Supabase routes through pgbouncer in
        # transaction mode, which doesn't support asyncpg's prepared statements.
        pool: asyncpg.Pool | None = await asyncpg.create_pool(
            settings.database_url, statement_cache_size=0
        )
    except Exception:
        pool = None
    app.state.provider = provider
    app.state.pool = pool
    _log = structlog.get_logger()
    if settings.selection_strategy == "nli_union":
        hypotheses = load_hypotheses(settings.hypotheses_path)
        hypotheses_version = Path(settings.hypotheses_path).stem
        _log.info("hypotheses_loaded", version=hypotheses_version, count=len(hypotheses))

        try:
            nli_classifier = NLIClassifier()
        except Exception as exc:
            raise RuntimeError(f"NLI model load failed — aborting startup: {exc}") from exc
        app.state.nli_classifier = nli_classifier
        _log.info("nli_classifier_loaded", model=settings.nli_model)

        # Warmup: profile latency on a ~200-word story, log result (T013).
        _warmup_story = (
            "Marcus bought NovaTech shares at $142 six months ago. The stock has since fallen "
            "to $40 after a series of poor earnings reports. His financial advisor recommends "
            "selling and reinvesting, but Marcus insists the stock will recover to its original "
            "price. He keeps reminding himself how much he paid for it and believes the market "
            "will eventually correct. Meanwhile the company has announced further write-downs "
            "and two board members have resigned. His advisor warns that holding is costing him "
            "opportunity elsewhere, but Marcus refuses to realise the loss."
        )
        _warmup = nli_classifier.classify(
            _warmup_story,
            [("warmup", "The decision-maker commits more resources despite clear failure signals.")],
        )
        _log.info("nli_warmup_complete", latency_ms=round(_warmup.latency_ms, 1))

        app.state.selection_strategy = NLIUnionStrategy(
            nli_classifier,
            combiner=None,
            vector_strategy=VectorOnlyStrategy(provider, pool),
            hypotheses=hypotheses,
            hypotheses_version=hypotheses_version,
        )
    else:
        app.state.selection_strategy = VectorOnlyStrategy(provider, pool)

    roster: list[BiasResult] = []
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(ROSTER_QUERY, settings.taxonomy_version)
            roster = [
                BiasResult(
                    id=r["bias_id"],
                    name=r["name"] or r["bias_id"],
                    retrieval_score=0.0,
                    definition=r["definition"] or "",
                    examples="",
                    indicators="",
                    false_positives="",
                    related_biases="",
                )
                for r in rows
            ]
        except Exception:
            pass
    app.state.roster = roster

    yield
    if pool is not None:
        await pool.close()


app = FastAPI(lifespan=lifespan)
app.include_router(retrieve.router)
