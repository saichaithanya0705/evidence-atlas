"""Auditable, bounded research pipeline orchestration for FastAPI."""

from __future__ import annotations

import copy
import inspect
import logging
import re
import threading
import uuid
from time import perf_counter
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, TypedDict

from backend.app.evidence.extraction import EvidenceAnalyzer, EvidenceExtractor
from backend.app.models.request_response import AnswerStatus, EvidenceRecord, ResearchResponse, RetrievalCandidate
from backend.app.conversation.models import CorrectiveResearchProposal, EvidenceGapContext
from backend.app.query.models import QueryPlan
from backend.app.workflow.judge import EvidenceGrade, EvidenceSufficiencyJudge
from backend.app.workflow.synthesis import EvidenceSynthesizer, _claims

logger = logging.getLogger(__name__)


class _DeferredQueryEncoder:
    """Defer MedCPT initialization until an embedding call is actually requested."""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.encoder = None

    def encode_queries(self, queries: List[str]):
        if self.encoder is None:
            from backend.app.retrieval.medcpt import MedCPTQueryEncoder

            self.encoder = MedCPTQueryEncoder(
                model_name_or_path=self.settings.MEDCPT_QUERY_ENCODER,
                device=self.settings.DEVICE,
                cache_dir=self.settings.MODELS_CACHE_DIR,
                allow_mock=bool(getattr(self.settings, "MEDCPT_ALLOW_MOCK", False)),
            )
        return self.encoder.encode_queries(queries)


@dataclass
class _WorkflowState:
    request_id: str
    query: str
    user_filters: Dict[str, Any]
    initial_plan: Optional[QueryPlan] = None
    candidates_by_pmid: Dict[str, RetrievalCandidate] = field(default_factory=dict)
    grade: Optional[EvidenceGrade] = None
    corrective_queries: List[str] = field(default_factory=list)
    retrieval_iterations: List[Dict[str, Any]] = field(default_factory=list)
    stages: List[Dict[str, Any]] = field(default_factory=list)
    stop_reason: Optional[str] = None
    active_stage: str = "start"
    current_query: Optional[str] = None
    current_route: Optional[str] = None
    route_floor: Optional[str] = None
    current_complexity_hint: Optional[str] = None
    loop_count: int = 0
    iteration: int = 0
    pending_plan: Optional[QueryPlan] = None
    pending_candidates: List[RetrievalCandidate] = field(default_factory=list)
    ranked_candidates: List[RetrievalCandidate] = field(default_factory=list)
    evidence_records: List[Any] = field(default_factory=list)
    analysis: Dict[str, Any] = field(default_factory=dict)
    synthesis: Any = None
    response: Optional[ResearchResponse] = None
    technical_failure: bool = False
    trace_payload: Dict[str, Any] = field(default_factory=dict)
    pending_details: Dict[str, Any] = field(default_factory=dict)
    next_query: Optional[str] = None
    timings_ms: List[Dict[str, Any]] = field(default_factory=list)
    event_sink: Optional[Callable[[str, Dict[str, Any]], None]] = field(default=None, repr=False)


class _GraphInput(TypedDict):
    workflow: _WorkflowState
    budget: int
    evidence_limit: int


_LIMITED_CAVEAT = "The full question was not established by the available evidence."
_LIMITED_GAP_NOTICE = "Evidence gaps are listed separately in the response."


def _limited_answer_text(text: str) -> str:
    """Attach fixed non-claim metadata to a LIMITED answer."""
    body_lines = [
        line for line in (text or "").splitlines()
        if line.strip().casefold().rstrip(". ") not in {
            _LIMITED_CAVEAT.casefold().rstrip(". "),
            _LIMITED_GAP_NOTICE.casefold().rstrip(". "),
        }
    ]
    return "\n".join(
        [line for line in body_lines if line.strip()]
        + [_LIMITED_CAVEAT, _LIMITED_GAP_NOTICE]
    )


def _validate_release_text(text: str, records: Sequence[EvidenceRecord], synthesizer: Any) -> Tuple[bool, Any]:
    """Recheck actual claims after release metadata has been attached."""
    validator = getattr(synthesizer, "validator", None)
    if validator is None:
        return False, None
    audit = validator.validate(text, records)
    if not audit.valid:
        return False, audit
    claims = _claims(text)
    if not claims:
        return True, audit
    semantic = getattr(synthesizer, "semantic_verifier", None)
    available = bool(getattr(semantic, "available", False)) if semantic is not None else False
    if available:
        try:
            verdicts = semantic.verify(text, records)
        except Exception:
            return False, audit
        return len(verdicts) == len(claims) and all(item.supported for item in verdicts), audit
    exact_check = getattr(synthesizer, "_is_exact_span_text", None)
    if not callable(exact_check) or not exact_check(text, records):
        return False, audit
    return True, audit


class ResearchService:
    """Coordinate query understanding, hybrid search, CRAG, and citation gates.

    Default collaborators are lazy: constructing/importing this service does not
    initialize Qdrant or load any Hugging Face weights.
    """

    _TRANSITIONS = {
        "start": {"query_analysis"},
        "query_analysis": {"retrieve"},
        "retrieve": {"judge"},
        "judge": {"correct", "evidence"},
        "correct": {"retrieve"},
        "evidence": {"synthesize"},
        "synthesize": {"validate"},
        "validate": {"done"},
    }

    def __init__(
        self,
        settings: Any = None,
        query_analysis_service: Any = None,
        hybrid_retriever: Any = None,
        reranker: Any = None,
        evidence_judge: Any = None,
        evidence_extractor: Any = None,
        synthesizer: Any = None,
        evidence_analyzer: Any = None,
    ) -> None:
        self._settings = settings
        self._initialization_lock = threading.RLock()
        self._search_lock = threading.RLock()
        self._query_analysis_service = query_analysis_service
        self._hybrid_retriever = hybrid_retriever
        self._reranker = reranker
        self._evidence_judge = evidence_judge
        self._evidence_extractor = evidence_extractor or EvidenceExtractor()
        self._synthesizer = synthesizer
        self._evidence_analyzer = evidence_analyzer or EvidenceAnalyzer()
        self._traces: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._trace_lock = threading.RLock()

    @property
    def settings(self) -> Any:
        if self._settings is None:
            from backend.app.core.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _get_query_analysis_service(self) -> Any:
        if self._query_analysis_service is None:
            with self._initialization_lock:
                if self._query_analysis_service is None:
                    from backend.app.query.embeddings import DualQueryEmbeddingGenerator
                    from backend.app.query.query_service import QueryAnalysisService

                    deferred_encoder = _DeferredQueryEncoder(self.settings)
                    self._query_analysis_service = QueryAnalysisService(
                        embedding_generator=DualQueryEmbeddingGenerator(encoder=deferred_encoder)
                    )
        return self._query_analysis_service

    def _get_hybrid_retriever(self) -> Any:
        if self._hybrid_retriever is None:
            with self._initialization_lock:
                if self._hybrid_retriever is None:
                    from backend.app.retrieval.hybrid import HybridRetriever

                    self._hybrid_retriever = HybridRetriever(settings=self.settings)
        return self._hybrid_retriever

    def _get_reranker(self) -> Any:
        if self._reranker is None:
            with self._initialization_lock:
                if self._reranker is None:
                    from backend.app.retrieval.reranker import MedCPTReranker

                    self._reranker = MedCPTReranker(
                        model_name_or_path=self.settings.MEDCPT_CROSS_ENCODER,
                        cache_dir=self.settings.MODELS_CACHE_DIR,
                        device=self.settings.DEVICE,
                        allow_mock=bool(getattr(self.settings, "MEDCPT_ALLOW_MOCK", False)),
                    )
        return self._reranker

    def _get_judge(self) -> Any:
        if self._evidence_judge is None:
            self._evidence_judge = EvidenceSufficiencyJudge(settings=self.settings)
        return self._evidence_judge

    def _get_synthesizer(self) -> Any:
        if self._synthesizer is None:
            self._synthesizer = EvidenceSynthesizer(settings=self.settings)
        return self._synthesizer

    @staticmethod
    def _normalize_user_filters(user_filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if user_filters is None:
            return {}
        if hasattr(user_filters, "model_dump"):
            user_filters = user_filters.model_dump(exclude_none=True)
        data = dict(user_filters)
        if "study_types" not in data and "study_type_filters" in data:
            data["study_types"] = data.pop("study_type_filters")
        return {key: value for key, value in data.items() if value is not None}

    def _build_plan(
        self,
        query: str,
        user_filters: Optional[Dict[str, Any]] = None,
        route_override: Optional[str] = None,
        agent_complexity_hint: Optional[str] = None,
        route_floor: Optional[str] = None,
        agent_rewrite: Optional[str] = None,
    ) -> QueryPlan:
        query_analysis = self._get_query_analysis_service()
        effective_floor = route_floor
        if route_override:
            route = str(route_override).upper()
            if route not in {"SIMPLE", "MODERATE", "COMPLEX"}:
                raise ValueError("route_override must be SIMPLE, MODERATE, or COMPLEX")
            ranks = {"SIMPLE": 0, "MODERATE": 1, "COMPLEX": 2}
            if (
                effective_floor is None
                or str(effective_floor).upper() not in ranks
                or ranks[route] > ranks[str(effective_floor).upper()]
            ):
                effective_floor = route

        plan_kwargs: Dict[str, Any] = {}
        if agent_complexity_hint is not None:
            plan_kwargs["agent_complexity_hint"] = agent_complexity_hint
        if effective_floor is not None:
            plan_kwargs["route_floor"] = effective_floor
        if agent_rewrite is not None:
            plan_kwargs["agent_rewrite"] = agent_rewrite
        parameters = inspect.signature(query_analysis.build_query_plan).parameters
        if not any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            plan_kwargs = {key: value for key, value in plan_kwargs.items() if key in parameters}

        plan, _ = query_analysis.build_query_plan(
            raw_query=query,
            user_filters=self._normalize_user_filters(user_filters),
            generate_embeddings=False,
            **plan_kwargs,
        )
        if (
            effective_floor
            and "route_floor" not in parameters
            and plan.route in {"SIMPLE", "MODERATE", "COMPLEX"}
        ):
            route = str(effective_floor).upper()
            if route in {"SIMPLE", "MODERATE", "COMPLEX"}:
                ranks = {"SIMPLE": 0, "MODERATE": 1, "COMPLEX": 2}
                final_route = max((plan.route, route), key=ranks.__getitem__)
                route_source = (
                    "route_floor"
                    if final_route == route and final_route != plan.route
                    else "rule"
                )
                plan = plan.model_copy(
                    update={"route": final_route, "route_floor": route, "route_source": route_source}
                )
        elif route_override:
            route = str(route_override).upper()
            if route in {"SIMPLE", "MODERATE", "COMPLEX"} and plan.route in {"SIMPLE", "MODERATE", "COMPLEX"}:
                ranks = {"SIMPLE": 0, "MODERATE": 1, "COMPLEX": 2}
                if ranks[route] > ranks[plan.route]:
                    plan = plan.model_copy(update={"route": route})
        return plan

    def _search_plan(self, plan: QueryPlan, top_k: int) -> Tuple[List[RetrievalCandidate], Dict[str, Any]]:
        # The shared retriever/reranker own mutable model weights and last_trace.
        # Serialize each pass so concurrent requests cannot release each other's models.
        with self._search_lock:
            return self._search_plan_locked(plan, top_k)

    def _search_plan_locked(self, plan: QueryPlan, top_k: int) -> Tuple[List[RetrievalCandidate], Dict[str, Any]]:
        timings_ms: Dict[str, float] = {}
        started = perf_counter()
        retrieval = self._get_hybrid_retriever()
        reranker = self._get_reranker()
        # Query and cross encoders are both large checkpoints.  A corrective
        # pass needs the query encoder again, so release the prior reranker
        # before dense retrieval and release the query encoder before reranking.
        retain_models = bool(getattr(self.settings, "MEDCPT_KEEP_MODELS_LOADED", False))
        if not retain_models and hasattr(reranker, "release"):
            reranker.release()
        timings_ms["release_reranker"] = round((perf_counter() - started) * 1000, 2)
        started = perf_counter()
        candidates = retrieval.search(plan, top_k=max(top_k, int(getattr(self.settings, "RERANKER_TOP_N", top_k))))
        timings_ms["hybrid_retrieval"] = round((perf_counter() - started) * 1000, 2)
        started = perf_counter()
        if not retain_models and hasattr(retrieval, "release_query_encoder"):
            retrieval.release_query_encoder()
        timings_ms["release_query_encoder"] = round((perf_counter() - started) * 1000, 2)
        started = perf_counter()
        query = plan.original_query or plan.canonical_query
        reranked, reranker_trace = reranker.rerank(
            query,
            candidates,
            top_n=int(getattr(self.settings, "RERANKER_TOP_N", top_k)),
        )
        timings_ms["reranking"] = round((perf_counter() - started) * 1000, 2)
        return reranked[:top_k], {
            "retrieval": copy.deepcopy(getattr(retrieval, "last_trace", {})),
            "reranker": reranker_trace,
            "timings_ms": timings_ms,
        }

    def search(
        self,
        query: str,
        top_k: int = 10,
        user_filters: Optional[Dict[str, Any]] = None,
        route_override: Optional[str] = None,
    ) -> Tuple[QueryPlan, List[RetrievalCandidate], Dict[str, Any]]:
        """Run one query-analysis and retrieval pass; suitable for ``POST /search``."""
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        started = perf_counter()
        plan = self._build_plan(query, user_filters, route_override)
        analysis_ms = round((perf_counter() - started) * 1000, 2)
        candidates, details = self._search_plan(plan, top_k)
        trace = {
            "stages": [
                {"stage": "query_analysis", "status": "completed"},
                {"stage": "router", "status": "completed", "route": plan.route},
                {"stage": "retrieval", "status": "completed", **details.get("retrieval", {})},
                {"stage": "reranking", "status": "completed", **details.get("reranker", {})},
            ],
            "query_plan": plan.model_dump(mode="json"),
            "candidate_pmids": [candidate.pmid for candidate in candidates],
            "timings_ms": {"query_analysis": analysis_ms, **details.get("timings_ms", {})},
        }
        return plan, candidates, trace

    def _transition(self, state: _WorkflowState, target: str, **details: Any) -> None:
        if target not in self._TRANSITIONS.get(state.active_stage, set()):
            raise RuntimeError(f"Invalid research workflow transition: {state.active_stage} -> {target}")
        state.active_stage = target
        state.stages.append({"stage": target, "status": "started", **details})
        if state.event_sink:
            payload = {"status": "started"}
            for key in ("iteration", "corrective_attempt", "remaining_budget", "stop_reason", "route"):
                if key in details:
                    payload[key] = details[key]
            state.event_sink(target, payload)

    @staticmethod
    def _merge_candidates(
        existing: Dict[str, RetrievalCandidate],
        incoming: Sequence[RetrievalCandidate],
        iteration: int,
    ) -> None:
        for candidate in incoming:
            previous = existing.get(candidate.pmid)
            if previous is None:
                existing[candidate.pmid] = candidate
                continue
            old_score = float(previous.reranker_score or 0.0)
            new_score = float(candidate.reranker_score or 0.0)
            stronger = candidate if new_score > old_score else previous
            rank_sources = dict(previous.channel_ranks)
            score_sources = dict(previous.channel_scores)
            for channel, value in candidate.channel_ranks.items():
                name = channel if channel not in rank_sources else f"iteration_{iteration}_{channel}"
                rank_sources[name] = value
            for channel, value in candidate.channel_scores.items():
                name = channel if channel not in score_sources else f"iteration_{iteration}_{channel}"
                score_sources[name] = value
            existing[candidate.pmid] = stronger.model_copy(
                update={
                    "rrf_score": max(previous.rrf_score, candidate.rrf_score),
                    "channel_ranks": rank_sources,
                    "channel_scores": score_sources,
                    "graph_path": candidate.graph_path or previous.graph_path,
                    "filter_satisfied": previous.filter_satisfied and candidate.filter_satisfied,
                }
            )

    @staticmethod
    def _select_evidence_candidates(
        candidates: Sequence[RetrievalCandidate], limit: int
    ) -> List[RetrievalCandidate]:
        """Keep the evidence pack focused while retaining ranked search results.

        MedCPT logits are useful for ordering but are not calibrated across
        queries.  A relative cutoff plus a three-study floor avoids feeding the
        synthesis unrelated tail results without pretending the scores are
        absolute probabilities.
        """
        ranked = list(candidates[: max(1, limit)])
        if not ranked:
            return []
        scored = [item for item in ranked if item.reranker_score is not None]
        if not scored:
            return ranked[: min(3, len(ranked))]
        top_score = max(float(item.reranker_score or 0.0) for item in scored)
        relative_floor = max(0.0, top_score * 0.05)
        selected = [item for item in ranked if float(item.reranker_score or 0.0) >= relative_floor]
        minimum = min(3, len(ranked))
        if len(selected) < minimum:
            selected = ranked[:minimum]
        return selected[:limit]

    def _corrective_query(self, plan: QueryPlan, grade: EvidenceGrade, used: Sequence[str]) -> Optional[str]:
        missing = [item for item in grade.missing_concepts if item.casefold() not in plan.original_query.casefold()]
        options = []
        if missing:
            options.append(f"{plan.original_query} {' '.join(missing[:3])}")
        options.extend(
            [
                f"{plan.canonical_query} clinical outcomes evidence",
                f"{plan.canonical_query} systematic review research findings",
                f"{plan.original_query} {' '.join((plan.mesh_terms or [])[:3])}",
            ]
        )
        used_normalized = {re.sub(r"\s+", " ", query).strip().casefold() for query in used}
        for option in options:
            correction = re.sub(r"\s+", " ", option).strip()
            if correction and correction.casefold() not in used_normalized:
                return correction
        return None

    def research(
        self,
        query: str,
        user_filters: Optional[Dict[str, Any]] = None,
        max_loops: int = 2,
        request_id: Optional[str] = None,
        event_sink: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        *,
        agent_rewrite: Optional[str] = None,
        agent_complexity_hint: Optional[str] = None,
        route_floor: Optional[str] = None,
        gap_reviewer: Optional[Callable[[EvidenceGapContext], Optional[CorrectiveResearchProposal]]] = None,
    ) -> ResearchResponse:
        """Run the bounded route→retrieve→judge→correct→evidence→validate graph."""
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        request_id = request_id or str(uuid.uuid4())
        filters = self._normalize_user_filters(user_filters)
        configured_budget = max(0, int(getattr(self.settings, "MAX_CORRECTIVE_LOOPS", max_loops)))
        budget = min(max(0, int(max_loops)), configured_budget)
        state = _WorkflowState(request_id=request_id, query=query, user_filters=filters, event_sink=event_sink)
        route_ranks = {"SIMPLE": 0, "MODERATE": 1, "COMPLEX": 2}

        def normalize_query(value: str) -> str:
            return re.sub(r"\s+", " ", value).strip().casefold()

        initial_floor = str(route_floor or "SIMPLE").upper()
        if initial_floor not in route_ranks:
            raise ValueError("route_floor must be SIMPLE, MODERATE, or COMPLEX")
        state.route_floor = initial_floor
        state.current_complexity_hint = agent_complexity_hint
        used_queries = [query]
        research_started = perf_counter()
        from langgraph.graph import END, START, StateGraph

        def query_analysis_node(data: _GraphInput) -> Dict[str, _WorkflowState]:
            workflow = data["workflow"]
            self._transition(workflow, "query_analysis")
            workflow.initial_plan = self._build_plan(
                query, filters, agent_complexity_hint=agent_complexity_hint,
                route_floor=workflow.route_floor, agent_rewrite=agent_rewrite,
            )
            workflow.current_query = agent_rewrite or query
            workflow.current_route = workflow.initial_plan.route
            workflow.route_floor = max(
                (workflow.route_floor, workflow.initial_plan.route), key=route_ranks.__getitem__
            )
            if workflow.event_sink:
                workflow.event_sink("query_enhanced", {"iteration": 0, "rewrite_applied": bool(agent_rewrite)})
                workflow.event_sink("route_arbitrated", {"iteration": 0, "route": workflow.current_route, "route_floor": workflow.route_floor})
            workflow.stages.append(
                {
                    "stage": "router",
                    "status": "completed",
                    "route": workflow.initial_plan.route,
                    "reasoning": workflow.initial_plan.router_reasoning,
                }
            )
            return {"workflow": workflow}

        def retrieve_node(data: _GraphInput) -> Dict[str, _WorkflowState]:
            workflow = data["workflow"]
            current_query = workflow.current_query or query
            self._transition(workflow, "retrieve", iteration=workflow.iteration, query=current_query)
            plan = workflow.initial_plan if workflow.iteration == 0 else self._build_plan(
                query, filters, route_floor=workflow.route_floor,
                agent_rewrite=current_query,
                agent_complexity_hint=workflow.current_complexity_hint,
            )
            workflow.route_floor = max(
                (workflow.route_floor, plan.route), key=route_ranks.__getitem__
            )
            workflow.current_route = plan.route
            if workflow.iteration > 0 and workflow.event_sink:
                workflow.event_sink("query_enhanced", {"iteration": workflow.iteration, "rewrite_applied": True})
                workflow.event_sink("route_arbitrated", {"iteration": workflow.iteration, "route": workflow.current_route, "route_floor": workflow.route_floor})
            if workflow.event_sink:
                workflow.event_sink("retrieval_attempt", {"iteration": workflow.iteration, "route": plan.route})
            try:
                candidates, details = self._search_plan(
                    plan, top_k=int(getattr(self.settings, "DENSE_TOP_K", 30))
                )
            except Exception:
                workflow.technical_failure = True
                workflow.stop_reason = "retrieval_failed"
                candidates, details = [], {"retrieval": {}, "reranker": {}, "timings_ms": {}}
            self._merge_candidates(workflow.candidates_by_pmid, candidates, workflow.iteration)
            all_candidates = sorted(
                workflow.candidates_by_pmid.values(),
                key=lambda item: (-(item.reranker_score or 0.0), -item.rrf_score, item.pmid),
            )
            workflow.pending_plan = plan
            workflow.pending_candidates = candidates
            workflow.ranked_candidates = all_candidates
            workflow.pending_details = details
            return {"workflow": workflow}

        def judge_node(data: _GraphInput) -> Dict[str, _WorkflowState]:
            workflow = data["workflow"]
            self._transition(workflow, "judge", iteration=workflow.iteration)
            judge_candidates = self._select_evidence_candidates(
                workflow.ranked_candidates,
                int(getattr(self.settings, "RERANKER_TOP_N", 10)),
            )
            if workflow.technical_failure:
                workflow.grade = EvidenceGrade("INSUFFICIENT", [], {}, "Retrieval failed before evidence could be judged.")
            else:
                workflow.grade = self._get_judge().judge(workflow.initial_plan, judge_candidates)
            if workflow.event_sink:
                workflow.event_sink("evidence_judged", {
                    "iteration": workflow.iteration, "grade": workflow.grade.grade,
                    "missing_count": len(workflow.grade.missing_concepts),
                    "conflict_count": len(workflow.grade.conflicts),
                })
            plan = workflow.pending_plan
            workflow.retrieval_iterations.append(
                {
                    "iteration": workflow.iteration,
                    "query": workflow.current_query,
                    "query_plan": plan.model_dump(mode="json"),
                    "candidate_pmids": [candidate.pmid for candidate in workflow.pending_candidates],
                    "accumulated_pmids": [candidate.pmid for candidate in workflow.ranked_candidates],
                    **workflow.pending_details,
                    "grade": workflow.grade.to_dict()
                    if hasattr(workflow.grade, "to_dict")
                    else dict(workflow.grade),
                }
            )
            workflow.next_query = None
            if workflow.technical_failure:
                workflow.stop_reason = "retrieval_failed"
            elif workflow.grade.grade == "SUFFICIENT":
                workflow.stop_reason = "evidence_sufficient"
            elif workflow.grade.conflicts:
                workflow.stop_reason = "unresolved_conflict"
            elif workflow.loop_count >= data["budget"]:
                workflow.stop_reason = "correction_budget_exhausted" if data["budget"] else "correction_disabled"
            else:
                proposal_query = None
                if gap_reviewer is not None:
                    gap_context = EvidenceGapContext(
                        standalone_question=query,
                        deterministic_grade=workflow.grade.grade,
                        missing_concepts=workflow.grade.missing_concepts[:20],
                        missing_subquestions=workflow.grade.missing_subquestions[:20],
                        conflicts=workflow.grade.conflicts[:20],
                        prior_queries=[normalize_query(item) for item in used_queries[-20:]],
                        route_floor=workflow.route_floor,
                    )
                    try:
                        proposal = gap_reviewer(gap_context)
                        if proposal is not None:
                            if not isinstance(proposal, CorrectiveResearchProposal):
                                proposal = CorrectiveResearchProposal.model_validate(proposal)
                            if route_ranks[proposal.complexity_hint] >= route_ranks[workflow.route_floor]:
                                proposal_query = proposal.standalone_query
                                workflow.current_complexity_hint = proposal.complexity_hint
                            else:
                                workflow.stop_reason = "correction_rejected_below_route_floor"
                    except Exception:
                        proposal_query = None
                    if workflow.event_sink:
                        workflow.event_sink("agent_decision", {
                            "iteration": workflow.iteration,
                            "accepted": bool(proposal_query),
                            "route_floor": workflow.route_floor,
                        })
                normalized_used = {normalize_query(item) for item in used_queries}
                if proposal_query and normalize_query(proposal_query) not in normalized_used:
                    workflow.next_query = proposal_query
                else:
                    workflow.next_query = self._corrective_query(
                        workflow.initial_plan, workflow.grade, used_queries
                    )
                    workflow.current_complexity_hint = None
                if workflow.next_query is None:
                    workflow.stop_reason = workflow.stop_reason or "correction_stalled"
                    if workflow.event_sink:
                        workflow.event_sink("correction_stopped", {"reason": workflow.stop_reason, "iteration": workflow.iteration})
            return {"workflow": workflow}

        def route_after_judge(data: _GraphInput) -> str:
            workflow = data["workflow"]
            return "correct" if workflow.next_query is not None else "evidence"

        def correct_node(data: _GraphInput) -> Dict[str, _WorkflowState]:
            workflow = data["workflow"]
            workflow.current_query = workflow.next_query
            workflow.corrective_queries.append(workflow.current_query)
            used_queries.append(workflow.current_query)
            workflow.loop_count += 1
            workflow.iteration += 1
            self._transition(
                workflow,
                "correct",
                corrective_query=workflow.current_query,
                corrective_attempt=workflow.loop_count,
                remaining_budget=data["budget"] - workflow.loop_count,
            )
            # Corrective searches retain the original route's retrieval channels.
            return {"workflow": workflow}

        def evidence_node(data: _GraphInput) -> Dict[str, _WorkflowState]:
            workflow = data["workflow"]
            stop_details: Dict[str, Any] = {"stop_reason": workflow.stop_reason}
            if workflow.grade is not None and workflow.grade.grade != "SUFFICIENT":
                stop_details["final_grade"] = workflow.grade.grade
            self._transition(workflow, "evidence", **stop_details)
            evidence_limit = data["evidence_limit"]
            workflow.ranked_candidates = sorted(
                workflow.candidates_by_pmid.values(),
                key=lambda item: (-(item.reranker_score or 0.0), -item.rrf_score, item.pmid),
            )[:evidence_limit]
            evidence_candidates = self._select_evidence_candidates(
                workflow.ranked_candidates, evidence_limit
            )
            workflow.evidence_records = self._evidence_extractor.extract_all(
                evidence_candidates, workflow.initial_plan
            )
            workflow.analysis = self._evidence_analyzer.analyze(
                workflow.evidence_records, workflow.initial_plan
            )
            workflow.stages.append(
                {
                    "stage": "evidence_extraction",
                    "status": "completed",
                    "record_count": len(workflow.evidence_records),
                    "supporting_span_count": sum(
                        len(record.supporting_text_spans) for record in workflow.evidence_records
                    ),
                }
            )
            return {"workflow": workflow}

        def synthesize_node(data: _GraphInput) -> Dict[str, _WorkflowState]:
            workflow = data["workflow"]
            self._transition(workflow, "synthesize")
            insufficient = not workflow.grade or workflow.grade.grade != "SUFFICIENT"
            workflow.synthesis = self._get_synthesizer().synthesize(
                query,
                workflow.evidence_records,
                list(dict.fromkeys(
                    workflow.analysis["evidence_gaps"]
                    + (workflow.grade.missing_concepts if workflow.grade else [])
                    + (workflow.grade.missing_subquestions if workflow.grade else [])
                    + (workflow.grade.conflicts if workflow.grade else [])
                )),
                insufficient=insufficient,
            )
            return {"workflow": workflow}

        def validate_node(data: _GraphInput) -> Dict[str, _WorkflowState]:
            workflow = data["workflow"]
            synthesis = workflow.synthesis
            self._transition(
                workflow,
                "validate",
                citation_precision=synthesis.audit.precision,
                citations_valid=synthesis.audit.valid,
            )
            if workflow.technical_failure:
                workflow.stop_reason = "retrieval_failed"
                response_text = "A technical failure prevented retrieval and evidence validation."
                citations = []
                audit_valid = False
                precision = 0.0
                audit_dict = {"valid": False, "technical_failure": True, "cited_pmids": [], "citation_precision": 0.0}
            elif not synthesis.audit.valid:
                workflow.stop_reason = "citation_validation_failed_fail_closed"
                response_text = "The available retrieved evidence is insufficient to provide a validated research summary."
                citations: List[str] = []
                audit_valid = True
                precision = 1.0
                audit_dict = {
                    "valid": False,
                    "final_response_fail_closed": True,
                    "pre_fail_closed_audit": synthesis.audit.to_dict(),
                    "cited_pmids": [],
                    "citation_precision": 1.0,
                }
            else:
                response_text = synthesis.text
                citations = synthesis.audit.cited_pmids
                audit_valid = True
                precision = synthesis.audit.precision
                audit_dict = synthesis.audit.to_dict()
                if workflow.stop_reason is None:
                    workflow.stop_reason = "completed"
            response_gaps = [] if workflow.technical_failure else list(dict.fromkeys(
                workflow.analysis["evidence_gaps"]
                + (workflow.grade.missing_concepts if workflow.grade else [])
                + (workflow.grade.missing_subquestions if workflow.grade else [])
                + (workflow.grade.conflicts if workflow.grade else [])
            ))
            if workflow.technical_failure:
                answer_status = AnswerStatus.FAILED
            elif workflow.analysis["consensus_level"] == "conflicting" or (workflow.grade and workflow.grade.conflicts):
                answer_status = AnswerStatus.INSUFFICIENT
            elif workflow.grade and workflow.grade.grade == "SUFFICIENT" and synthesis.audit.valid and synthesis.audit.cited_pmids:
                answer_status = AnswerStatus.SUPPORTED
            elif synthesis.audit.valid and synthesis.audit.cited_pmids:
                answer_status = AnswerStatus.LIMITED
            else:
                answer_status = AnswerStatus.INSUFFICIENT

            synthesizer = self._get_synthesizer()
            if answer_status == AnswerStatus.LIMITED:
                response_text = _limited_answer_text(response_text)
            if answer_status in {AnswerStatus.SUPPORTED, AnswerStatus.LIMITED}:
                release_valid, final_audit = _validate_release_text(
                    response_text, workflow.evidence_records, synthesizer
                )
                if release_valid and final_audit is not None:
                    citations = final_audit.cited_pmids
                    precision = final_audit.precision
                    audit_valid = True
                    audit_dict = final_audit.to_dict()
                else:
                    answer_status = AnswerStatus.INSUFFICIENT
                    response_text = _limited_answer_text(
                        "The available retrieved evidence is insufficient to provide a validated research summary."
                    )
                    citations = []
                    audit_valid = True
                    precision = 1.0
                    audit_dict = {
                        "valid": False,
                        "final_response_fail_closed": True,
                        "cited_pmids": [],
                        "citation_precision": 1.0,
                    }
            workflow.stages.append(
                {
                    "stage": "citation_verification",
                    "status": "completed",
                    "precision": precision,
                    "valid": audit_valid,
                    "cited_pmids": list(citations),
                }
            )
            workflow.response = ResearchResponse(
                answer_status=answer_status,
                request_id=request_id,
                query=query,
                canonical_query=workflow.initial_plan.canonical_query,
                route=workflow.initial_plan.route,
                synthesis=response_text,
                evidence_table=workflow.evidence_records,
                cited_pmids=citations,
                citations_valid=audit_valid,
                citation_precision=precision,
                consensus_level=workflow.analysis["consensus_level"],
                evidence_gaps=response_gaps,
                audit_trace_url=f"/trace/{request_id}",
                retrieved_papers=workflow.ranked_candidates,
            )
            if workflow.event_sink:
                released_claims = len(_claims(response_text)) if audit_valid and citations else 0
                workflow.event_sink("claim_verified", {"claim_count": released_claims, "supported_count": released_claims})
                workflow.event_sink("answer_released", {"status": workflow.response.answer_status.value, "claim_count": len(workflow.response.cited_pmids), "gap_count": len(workflow.response.evidence_gaps)})
            insufficient = not workflow.grade or workflow.grade.grade != "SUFFICIENT"
            workflow.trace_payload = {
                "request_id": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "original_query": query,
                "query_plan": workflow.initial_plan.model_dump(mode="json"),
                "route": workflow.initial_plan.route,
                "stages": workflow.stages,
                "retrieval_iterations": workflow.retrieval_iterations,
                "corrective_queries": workflow.corrective_queries,
                "correction_budget": data["budget"],
                "correction_attempts": workflow.loop_count,
                "stop_reason": workflow.stop_reason,
                "final_evidence_pmids": [record.pmid for record in workflow.evidence_records],
                "cross_study_analysis": workflow.analysis,
                "synthesis_metadata": {
                    "mode": synthesis.mode,
                    "fallback_reason": synthesis.fallback_reason,
                    "insufficient_evidence": insufficient,
                    "timings_ms": synthesis.timings_ms,
                },
                "citation_audit": audit_dict,
            }
            return {"workflow": workflow}

        def done_node(data: _GraphInput) -> Dict[str, _WorkflowState]:
            workflow = data["workflow"]
            self._transition(workflow, "done", stop_reason=workflow.stop_reason)
            workflow.trace_payload["stages"] = workflow.stages
            with self._trace_lock:
                self._traces[request_id] = workflow.trace_payload
                self._traces.move_to_end(request_id)
                maximum = int(getattr(self.settings, "TRACE_MAX_ENTRIES", 500))
                while len(self._traces) > maximum:
                    self._traces.popitem(last=False)
            return {"workflow": workflow}

        def timed_node(name: str, node: Any) -> Any:
            def completed_details(workflow: _WorkflowState) -> Dict[str, Any]:
                if name == "query_analysis" and workflow.initial_plan:
                    return {
                        "query_plan": {
                            "route": workflow.initial_plan.route,
                            "canonical_query": workflow.initial_plan.canonical_query[:240],
                        },
                        "route": workflow.current_route,
                        "rule_route": workflow.initial_plan.rule_route,
                        "agent_complexity_hint": workflow.initial_plan.agent_complexity_hint,
                    }
                if name == "retrieve":
                    return {"candidate_pmids": [item.pmid for item in workflow.pending_candidates[:20]], "candidate_count": len(workflow.pending_candidates)}
                if name == "judge" and workflow.grade:
                    return {"grade": workflow.grade.grade, "missing_count": len(workflow.grade.missing_concepts), "conflict_count": len(workflow.grade.conflicts), "stop_reason": workflow.stop_reason}
                if name == "evidence":
                    return {"evidence_count": len(workflow.evidence_records), "evidence": [{"pmid": record.pmid, "supporting_span_count": len(record.supporting_text_spans)} for record in workflow.evidence_records[:20]]}
                if name == "validate":
                    return {"citation_audit": {"valid": bool(workflow.response and workflow.response.citations_valid), "precision": workflow.response.citation_precision if workflow.response else 0.0}, "cited_pmids": workflow.response.cited_pmids[:20] if workflow.response else []}
                if name == "done":
                    return {"stop_reason": workflow.stop_reason}
                return {}

            def wrapped(data: _GraphInput) -> Dict[str, _WorkflowState]:
                started = perf_counter()
                status = "completed"
                try:
                    return node(data)
                except Exception:
                    status = "failed"
                    raise
                finally:
                    workflow = data["workflow"]
                    if name == "retrieve" and workflow.technical_failure:
                        status = "failed"
                    duration_ms = round((perf_counter() - started) * 1000, 2)
                    workflow.timings_ms.append(
                        {
                            "stage": name,
                            "iteration": workflow.iteration if name in {"retrieve", "judge", "correct"} else None,
                            "duration_ms": duration_ms,
                        }
                    )
                    for stage in reversed(workflow.stages):
                        if stage.get("stage") == name and stage.get("status") == "started":
                            stage["status"] = status
                            stage["duration_ms"] = duration_ms
                            break
                    if workflow.event_sink:
                        payload = {"status": status, "duration_ms": duration_ms}
                        if status == "completed":
                            payload.update(completed_details(workflow))
                        workflow.event_sink(name, payload)
            return wrapped

        graph = StateGraph(_GraphInput)
        graph.add_node("query_analysis", timed_node("query_analysis", query_analysis_node))
        graph.add_node("retrieve", timed_node("retrieve", retrieve_node))
        graph.add_node("judge", timed_node("judge", judge_node))
        graph.add_node("correct", timed_node("correct", correct_node))
        graph.add_node("evidence", timed_node("evidence", evidence_node))
        graph.add_node("synthesize", timed_node("synthesize", synthesize_node))
        graph.add_node("validate", timed_node("validate", validate_node))
        graph.add_node("done", timed_node("done", done_node))
        graph.add_edge(START, "query_analysis")
        graph.add_edge("query_analysis", "retrieve")
        graph.add_edge("retrieve", "judge")
        graph.add_conditional_edges(
            "judge", route_after_judge, {"correct": "correct", "evidence": "evidence"}
        )
        graph.add_edge("correct", "retrieve")
        graph.add_edge("evidence", "synthesize")
        graph.add_edge("synthesize", "validate")
        graph.add_edge("validate", "done")
        graph.add_edge("done", END)
        result = graph.compile().invoke(
            {
                "workflow": state,
                "budget": budget,
                "evidence_limit": int(getattr(self.settings, "RERANKER_TOP_N", 10)),
            }
        )
        completed = result["workflow"]
        completed.trace_payload["timings_ms"] = {
            "total": round((perf_counter() - research_started) * 1000, 2),
            "stages": completed.timings_ms,
        }
        with self._trace_lock:
            if request_id in self._traces:
                self._traces[request_id] = completed.trace_payload
        return completed.response

    def answer_from_evidence(
        self,
        query: str,
        *,
        candidates: Sequence[RetrievalCandidate],
        evidence: Sequence[EvidenceRecord],
        event_sink: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> ResearchResponse:
        """Answer from supplied evidence only; re-run deterministic and semantic gates."""
        request_id = str(uuid.uuid4())
        try:
            plan = self._build_plan(query)
            records = list(evidence)
            analysis = self._evidence_analyzer.analyze(records, plan)
            grade = self._get_judge().judge(plan, list(candidates))
            gaps = list(dict.fromkeys(
                analysis["evidence_gaps"] + list(grade.missing_concepts)
                + list(grade.missing_subquestions) + list(grade.conflicts)
            ))
            synthesizer = self._get_synthesizer()
            synthesis = synthesizer.synthesize(
                query, records, gaps, insufficient=grade.grade != "SUFFICIENT"
            )
            text = synthesis.text
            validator = getattr(synthesizer, "validator", None)
            audit = validator.validate(text, records) if validator is not None else synthesis.audit
            semantic = getattr(synthesizer, "semantic_verifier", None)
            semantic_available = bool(getattr(semantic, "available", False)) if semantic is not None else False
            exact_check = getattr(synthesizer, "_is_exact_span_text", None)
            if (
                audit.valid and records and _claims(text) and not semantic_available
                and (not callable(exact_check) or not exact_check(text, records))
            ):
                text = synthesizer.deterministic_text(
                    query, records, gaps, grade.grade != "SUFFICIENT"
                )
                audit = validator.validate(text, records)
            if audit.valid and semantic is not None and bool(getattr(semantic, "available", True)) and records:
                verdicts = semantic.verify(text, records)
                expected = len(_claims(text))
                if len(verdicts) != expected or not all(item.supported for item in verdicts):
                    kept = synthesizer._verified_records(text, records, verdicts)
                    records = kept
                    text = synthesizer.deterministic_text(
                        query, records, gaps, grade.grade != "SUFFICIENT" or not records
                    )
                    audit = validator.validate(text, records)
                    if records:
                        final_verdicts = semantic.verify(text, records)
                        if len(final_verdicts) != len(_claims(text)) or not all(item.supported for item in final_verdicts):
                            records = synthesizer._verified_records(text, records, final_verdicts)
                            text = synthesizer.deterministic_text(query, records, gaps, True)
                            audit = validator.validate(text, records)
            if not audit.valid:
                text = "The available evidence could not be validated for a safe research answer."
                records = []
                audit = validator.validate(text, []) if validator is not None else synthesis.audit
            if grade.grade == "SUFFICIENT" and audit.valid and audit.cited_pmids:
                status = AnswerStatus.SUPPORTED
            elif audit.valid and audit.cited_pmids and analysis["consensus_level"] != "conflicting" and not grade.conflicts:
                status = AnswerStatus.LIMITED
            else:
                status = AnswerStatus.INSUFFICIENT
            if status == AnswerStatus.LIMITED:
                text = _limited_answer_text(text)
            if status in {AnswerStatus.SUPPORTED, AnswerStatus.LIMITED}:
                release_valid, final_audit = _validate_release_text(text, records, synthesizer)
                if release_valid and final_audit is not None:
                    audit = final_audit
                else:
                    status = AnswerStatus.INSUFFICIENT
                    text = _limited_answer_text(
                        "The available evidence is insufficient to provide a validated research answer."
                    )
                    audit = validator.validate(text, []) if validator is not None else synthesis.audit
            if event_sink:
                released_claims = len(_claims(text)) if status in {AnswerStatus.SUPPORTED, AnswerStatus.LIMITED} else 0
                event_sink("claim_verified", {"claim_count": released_claims, "supported_count": released_claims})
            response = ResearchResponse(
                answer_status=status,
                request_id=request_id,
                query=query,
                canonical_query=plan.canonical_query,
                route=plan.route,
                synthesis=text,
                evidence_table=records,
                cited_pmids=audit.cited_pmids,
                citations_valid=audit.valid,
                citation_precision=audit.precision,
                consensus_level=analysis["consensus_level"],
                evidence_gaps=gaps,
                audit_trace_url=f"/trace/{request_id}",
                retrieved_papers=list(candidates),
            )
            if event_sink:
                event_sink("answer_released", {"status": status.value, "claim_count": len(audit.cited_pmids), "gap_count": len(response.evidence_gaps)})
            return response
        except Exception:
            if event_sink:
                event_sink("answer_released", {"status": AnswerStatus.FAILED.value, "claim_count": 0, "gap_count": 0})
            return ResearchResponse(
                answer_status=AnswerStatus.FAILED,
                request_id=request_id,
                query=query,
                canonical_query=query,
                route="SIMPLE",
                synthesis="A technical failure prevented evidence validation.",
                citations_valid=False,
                citation_precision=0.0,
                consensus_level="insufficient",
                evidence_gaps=[],
                audit_trace_url=f"/trace/{request_id}",
                retrieved_papers=list(candidates),
            )

    def get_trace(self, request_id: str) -> Optional[Dict[str, Any]]:
        with self._trace_lock:
            trace = self._traces.get(str(request_id))
            return copy.deepcopy(trace) if trace is not None else None

    def get_paper(self, pmid: str) -> Optional[Dict[str, Any]]:
        return self._get_hybrid_retriever().get_paper(str(pmid))

    def close(self) -> None:
        if self._hybrid_retriever is not None and hasattr(self._hybrid_retriever, "close"):
            self._hybrid_retriever.close()
