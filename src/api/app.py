import functools
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import asyncpg
import structlog
from fastapi import FastAPI

from src.api.routes import retrieve
from src.config import settings
from src.db.connection import init_pool_connection
from src.db.queries import ROSTER_QUERY
from src.llm.generator import LLMGenerator
from src.llm.prompt import load_catalog
from src.nli.classifier import NLIClassifier
from src.nli.combiner import CombinerConfig, combine
from src.nli.hypothesis_loader import load_hypotheses
from src.observability import configure_logging
from src.providers.sentence_transformer import SentenceTransformerProvider
from src.schemas.response import BiasResult
from src.selection.llm_union import LLMUnionStrategy
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
    _log = structlog.get_logger()
    try:
        # statement_cache_size=0 required: Supabase routes through pgbouncer in
        # transaction mode, which doesn't support asyncpg's prepared statements.
        pool: asyncpg.Pool | None = await asyncpg.create_pool(
            settings.database_url, statement_cache_size=0, init=init_pool_connection
        )
        _log.info("db_pool_created", min_size=10, max_size=10)
    except Exception as exc:
        _log.error("db_pool_failed", error=str(exc))
        pool = None
    app.state.provider = provider
    app.state.pool = pool
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

        combiner_fn = functools.partial(
            combine,
            config=CombinerConfig(
                w_nli=settings.w_nli,
                w_vec=settings.w_vec,
                nli_gate=settings.nli_gate,
                vec_gate=settings.vec_gate,
                combined_threshold=settings.combined_threshold,
            ),
        )
        app.state.selection_strategy = NLIUnionStrategy(
            nli_classifier,
            combiner=combiner_fn,
            vector_strategy=VectorOnlyStrategy(provider, pool),
            hypotheses=hypotheses,
            hypotheses_version=hypotheses_version,
        )
    elif settings.selection_strategy == "llm_union":
        if pool is None:
            raise RuntimeError(
                "llm_union requires the DB pool to load the bias catalog — aborting startup"
            )
        catalog = await load_catalog(pool, settings.taxonomy_version)
        _log.info("llm_catalog_loaded", count=len(catalog))

        try:
            generator = LLMGenerator(
                model_repo=settings.llm_model_repo,
                gguf_file=settings.llm_gguf_file,
                context_tokens=settings.llm_context_tokens,
                threads=settings.llm_threads,
                max_output_tokens=settings.llm_max_output_tokens,
                temperature=settings.llm_temperature,
            )
        except Exception as exc:
            # Only model LOAD failure aborts startup — parity with the NLI branch.
            raise RuntimeError(f"LLM model load failed — aborting startup: {exc}") from exc
        _log.info("llm_model_loaded", repo=settings.llm_model_repo, file=settings.llm_gguf_file)

        # Warmup is informational, NOT fatal — a transient hiccup must not block boot
        # (unlike model load above). Same ~200-word story as the NLI warmup.
        _warmup_story = (
            "Marcus bought NovaTech shares at $142 six months ago. The stock has since fallen "
            "to $40 after a series of poor earnings reports. His financial advisor recommends "
            "selling and reinvesting, but Marcus insists the stock will recover to its original "
            "price. He keeps reminding himself how much he paid for it and believes the market "
            "will eventually correct. Meanwhile the company has announced further write-downs "
            "and two board members have resigned. His advisor warns that holding is costing him "
            "opportunity elsewhere, but Marcus refuses to realise the loss."
        )
        try:
            _t0 = time.monotonic()
            generator.generate(
                "You are a cognitive-bias detector. Reply with just: []",
                _warmup_story,
            )
            _log.info(
                "llm_warmup_complete", latency_ms=round((time.monotonic() - _t0) * 1000, 1)
            )
        except Exception as exc:
            _log.warning("llm_warmup_failed", error=str(exc))

        app.state.selection_strategy = LLMUnionStrategy(
            generator,
            catalog=catalog,
            vector_strategy=VectorOnlyStrategy(provider, pool),
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
            if not roster:
                _log.warning("roster_empty", taxonomy_version=settings.taxonomy_version,
                             msg="index may not be built yet — fallback will return empty list")
        except Exception as exc:
            _log.warning("roster_query_failed", error=str(exc))
    app.state.roster = roster

    yield
    if pool is not None:
        await pool.close()


app = FastAPI(lifespan=lifespan)
app.include_router(retrieve.router)
