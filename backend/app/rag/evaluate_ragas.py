import argparse
import asyncio
import hashlib
import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient
from ragas.llms import llm_factory
from ragas.metrics.collections import (
    ContextPrecision,
    ContextRecall,
    FactualCorrectness,
    Faithfulness,
)

from app.core.config import settings
from app.rag.evaluate import EvaluationCase, _generate_answer
from app.rag.knowledge import KnowledgeBase, KnowledgeDocument, content_version_for

BASELINE_PATH = Path("/app/knowledge/baseline.json")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    metric_names = (
        "context_precision",
        "context_recall",
        "faithfulness",
        "factual_correctness",
    )
    metrics = {}
    for name in metric_names:
        values = [case["ragas_metrics"][name] for case in cases if case["ragas_metrics"][name] is not None]
        metrics[name] = {
            "mean": sum(values) / len(values) if values else None,
            "evaluated_cases": len(values),
        }
    no_answer_cases = [case for case in cases if not case["relevant_document_ids"]]
    metrics["no_answer_accuracy"] = {
        "mean": (
            sum(not case["retrieved_context_ids"] for case in no_answer_cases)
            / len(no_answer_cases)
            if no_answer_cases else None
        ),
        "evaluated_cases": len(no_answer_cases),
    }
    return {"case_count": len(cases), "metrics": metrics, "cases": cases}


async def evaluate_file(path: Path, output_path: Path | None = None) -> dict[str, Any]:
    if settings.openrouter_api_key is None or not settings.openrouter_api_key.get_secret_value().strip():
        raise ValueError("Set OPENROUTER_API_KEY before running RAGAS evaluation")
    if not BASELINE_PATH.is_file():
        raise ValueError(f"Isolated evaluation corpus not found: {BASELINE_PATH}")

    cases = [EvaluationCase.model_validate(row) for row in json.loads(path.read_text(encoding="utf-8"))]
    if not cases:
        raise ValueError("Evaluation file must contain at least one case")
    baseline = [
        KnowledgeDocument.model_validate(row)
        for row in json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    ]
    baseline_ids = {document.document_id for document in baseline}
    unknown_ids = {
        document_id
        for case in cases
        for document_id in case.relevant_document_ids
        if document_id not in baseline_ids
    }
    if unknown_ids:
        raise ValueError(f"Evaluation labels refer to documents outside the isolated baseline: {sorted(unknown_ids)}")

    collection_name = f"ragas_eval_{uuid4().hex}"
    eval_settings = settings.model_copy(update={"rag_collection_name": collection_name})
    qdrant = AsyncQdrantClient(url=settings.qdrant_url, timeout=30)
    knowledge = KnowledgeBase(eval_settings, qdrant)
    answer_client = AsyncOpenAI(
        api_key=settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        timeout=60.0,
        max_retries=1,
    )
    ragas_client = AsyncOpenAI(
        api_key=settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        timeout=60.0,
        max_retries=1,
    )
    evaluator_llm = llm_factory(
        settings.llm_classifier_model,
        client=ragas_client,
        temperature=0,
        max_tokens=4096,
    )
    metrics = {
        "context_precision": ContextPrecision(llm=evaluator_llm),
        "context_recall": ContextRecall(llm=evaluator_llm),
        "faithfulness": Faithfulness(llm=evaluator_llm),
        "factual_correctness": FactualCorrectness(llm=evaluator_llm),
    }
    report_cases: list[dict[str, Any]] = []
    collection_created = False
    try:
        await knowledge.initialize()
        collection_created = True
        for document in baseline:
            await knowledge.ingest(document)
            version = content_version_for(document)
            await knowledge.activate_document_version(document.document_id, version, None)
            knowledge.activate_sparse_document(
                document.document_id,
                knowledge.pending_chunks(document.document_id),
            )

        for case in cases:
            retrieved = await knowledge.search(case.query, limit=4)
            contexts = [chunk.text for chunk in retrieved]
            retrieved_ids = list(dict.fromkeys(chunk.document_id for chunk in retrieved))
            answer = await _generate_answer(answer_client, case.query, retrieved) if retrieved else (
                "Saya belum menemukan sumber terverifikasi yang cukup untuk menjawab pertanyaan ini."
            )
            scores: dict[str, float | None] = {
                name: None for name in metrics
            }
            if contexts:
                scores["faithfulness"] = (
                    await metrics["faithfulness"].ascore(
                        user_input=case.query,
                        response=answer,
                        retrieved_contexts=contexts,
                    )
                ).value
            if case.reference_answer and contexts:
                scores["context_precision"] = (
                    await metrics["context_precision"].ascore(
                        user_input=case.query,
                        reference=case.reference_answer,
                        retrieved_contexts=contexts,
                    )
                ).value
                scores["context_recall"] = (
                    await metrics["context_recall"].ascore(
                        user_input=case.query,
                        reference=case.reference_answer,
                        retrieved_contexts=contexts,
                    )
                ).value
                scores["factual_correctness"] = (
                    await metrics["factual_correctness"].ascore(
                        response=answer,
                        reference=case.reference_answer,
                    )
                ).value
            report_cases.append({
                "case_id": case.case_id,
                "user_input": case.query,
                "relevant_document_ids": case.relevant_document_ids,
                "retrieved_context_ids": retrieved_ids,
                "retrieved_contexts": contexts,
                "response": answer,
                "reference": case.reference_answer,
                "ragas_metrics": scores,
            })

        report = {
            "metadata": {
                "framework": "RAGAS",
                "ragas_version": importlib.metadata.version("ragas"),
                "run_at_utc": datetime.now(timezone.utc).isoformat(),
                "evaluation_file": path.name,
                "evaluation_file_sha256": sha256_file(path),
                "corpus_file": BASELINE_PATH.name,
                "corpus_file_sha256": sha256_file(BASELINE_PATH),
                "corpus_document_ids": sorted(baseline_ids),
                "retrieval_k": 4,
                "judge_max_tokens": 4096,
                "embedding_model": settings.rag_embedding_model,
                "reranker_model": settings.rag_rerank_model,
                "answer_model": settings.llm_conversation_model,
                "judge_model": settings.llm_classifier_model,
            },
            **summarize_cases(report_cases),
        }
        if output_path:
            output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report
    finally:
        await answer_client.close()
        await ragas_client.close()
        await knowledge.close()
        if collection_created:
            await qdrant.delete_collection(collection_name)
        await qdrant.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate isolated RAG fixtures using RAGAS")
    parser.add_argument("--file", type=Path, default=Path("/app/knowledge/rag-evaluation.json"))
    parser.add_argument("--output", type=Path, default=Path("/app/knowledge/ragas-evaluation-results.json"))
    args = parser.parse_args()
    report = asyncio.run(evaluate_file(args.file, args.output))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
