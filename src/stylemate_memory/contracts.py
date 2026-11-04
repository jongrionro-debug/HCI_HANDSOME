"""A0 interfaces for opt-in lumi-memory-v1; these do not enable a v1 runtime.

TypedDict keys are required unless total=False or marked NotRequired. Nullable
fields must be sent as null. These definitions are NOT runtime validators: each owning
module must reject unknown keys, invalid references and unauthorized transitions.
No registry values are duplicated here. See docs/project.md for policy/ownership.
"""

import hashlib
import json
from typing import Literal, NotRequired, Protocol, TypedDict, get_args

from .errors import StyleMateError


CONTRACT_VERSION = "lumi-memory-v1"
V1_REGISTRY_VERSION = "park-2025-source-v1"
LEGACY_REGISTRY_VERSION = "consumer-17-v1"
CATALOG_FORMAT_VERSION = "lumi-catalog-v1"

JSONValue = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]
Scope = Literal["short_term", "long_term"]
Origin = Literal["explicit", "inferred"]
Polarity = Literal["prefer", "avoid", "require", "indifferent"]
Strength = Literal["soft", "hard"]
Lifecycle = Literal["candidate", "active", "superseded", "withdrawn"]
MapStatus = Literal[
    "unspecified", "inferred", "specified", "indifferent",
    "not_applicable", "unsupported", "conflict",
]
ReviewPurpose = Literal[
    "confirm_content", "confirm_bindings", "future_reuse",
    "replace", "withdraw", "delete", "delete_request",
]
RefType = Literal[
    "evidence", "memory", "binding", "confirmation", "consent", "feedback",
    "interpretation", "round", "candidate_set", "question", "display", "event", "derived",
]


class ObjectRef(TypedDict):
    type: RefType
    id: str
    version: int


class Expected(TypedDict):
    request_revision: int
    profile_revision: int
    object_versions: list[ObjectRef]


class ProductVersion(TypedDict):
    product_id: str
    raw_version: int
    map_version: int


class ImageVersion(TypedDict):
    image_id: str
    version: int


class CatalogVersions(TypedDict):
    catalog_version: int
    products: list[ProductVersion]
    images: list[ImageVersion]


class Basis(Expected):
    request_id: str
    contract_version: str
    registry_version: str
    index_version: str | None
    catalog: CatalogVersions | None
    valid_until: str | None  # earliest dependency expiry; recheck the clock too


class StoredObject(TypedDict):
    id: str
    user_id: str
    request_id: str | None
    contract_version: str
    version: int
    created_at: str
    retention_until: str


class Selector(TypedDict):
    garment_type: str | None
    slot_id: str | None


class Conditions(TypedDict, total=False):
    occasion: str
    activity: str
    goal: str


class Fact(TypedDict):
    key: Literal["occasion", "activity", "goal"]
    value: str


class MemoryContent(TypedDict):
    kind: Literal["preference", "requirement", "situation"]
    content: str
    fact: Fact | None
    selector: Selector
    conditions: Conditions
    polarity: Polarity
    strength: Strength
    valid_from: str | None
    valid_until: str | None


class MemoryMeaning(MemoryContent):
    scope: Scope


class LegacyRecord(TypedDict):
    registry_version: str
    original: dict[str, JSONValue]  # original content/values/refs/consent, never a new quote
    evidence_status: Literal["reference_only", "missing"]
    mapping_status: Literal["unmapped", "requires_review", "equivalent"]


class MemoryItem(StoredObject, MemoryMeaning):
    origin: Origin
    confirmed: bool
    status: Lifecycle
    source_refs: list[ObjectRef]
    confirmation_ref: ObjectRef | None
    consent_ref: ObjectRef | None
    family_id: str
    legacy: NotRequired[LegacyRecord]


class PIPath(TypedDict):
    domain: Literal["PI"]
    feature: str


class FEAPath(TypedDict):
    domain: Literal["FEA"]
    category: str
    subcategory: str
    tag: str


FeaturePath = PIPath | FEAPath


class PIBindingSpec(PIPath):
    values: list[str] | None
    match: Literal["any", "all", "range"] | None
    polarity: Polarity
    strength: Strength


class FEABindingSpec(FEAPath):
    polarity: Polarity
    strength: Strength


BindingSpec = PIBindingSpec | FEABindingSpec


class BindingState(StoredObject):
    subject: Literal["user_target"]
    memory_id: str
    registry_version: str
    origin: Origin
    confirmed: bool
    status: Lifecycle
    source_refs: list[ObjectRef]
    confirmation_ref: ObjectRef | None


class PIBinding(BindingState, PIBindingSpec):
    pass


class FEABinding(BindingState, FEABindingSpec):
    pass


FeatureBinding = PIBinding | FEABinding


class PartRef(TypedDict):
    image_id: str
    image_version: int
    region_id: str | None
    box: list[float] | None  # exactly one of region_id / [x0,y0,x1,y1]


class Selection(TypedDict):
    target_id: str
    candidate_id: str
    part_ref: PartRef | None


class SelectionEvidence(Selection):
    round_ref: ObjectRef
    candidate_set_ref: ObjectRef
    product_id: str
    product_map_version: int
    image_id: str | None
    image_version: int | None


class Evidence(StoredObject):
    kind: Literal["user_text", "image_selection", "ui_response", "consent_snapshot"]
    quote: str | None
    context: str | None
    selector: Selector
    selection: SelectionEvidence | None
    display_ref: ObjectRef | None
    snapshot: MemoryMeaning | None  # independent, minimal long-term evidence


class ReviewSnapshot(TypedDict):
    meaning: MemoryMeaning | None
    bindings: list[BindingSpec]
    subject_refs: list[ObjectRef]


class ReviewDisplay(StoredObject):
    purpose: ReviewPurpose
    snapshot: ReviewSnapshot
    basis: Basis


class TrustedUserEvent(StoredObject):
    purpose: ReviewPurpose
    display_ref: ObjectRef
    command_id: str


class Confirmation(StoredObject):
    memory_id: str
    snapshot: ReviewSnapshot
    source_refs: list[ObjectRef]
    event_ref: ObjectRef
    confirmed_at: str


class Consent(StoredObject):
    memory_id: str
    purpose: Literal["future_reuse"]
    snapshot: ReviewSnapshot
    source_refs: list[ObjectRef]
    event_ref: ObjectRef
    consented_at: str
    status: Literal["active", "withdrawn"]


class MemoryLink(StoredObject):
    relation: Literal["supports", "derived_from", "supersedes", "promoted_from"]
    source_ref: ObjectRef
    target_ref: ObjectRef


class Question(StoredObject):
    text: str
    target_id: str | None
    subject_refs: list[ObjectRef]
    options: list[str]
    status: Literal["open", "answered", "skipped"]


class TargetSpec(TypedDict):
    target_id: str
    garment_type: str


class ModelSource(TypedDict):
    source_id: str  # per-call alias, resolved to ObjectRef by code
    kind: Literal["user_text", "image_selection", "memory"]
    content: str
    selector: Selector


class ExtractionInput(TypedDict):
    sources: list[ModelSource]
    targets: list[TargetSpec]
    registry: dict[str, JSONValue]


class ExtractedCandidate(TypedDict):
    candidate_key: str  # temporary key, not a database ID
    content: str
    kind: Literal["preference", "requirement", "situation"]
    fact: Fact | None
    selector: Selector
    conditions: Conditions
    condition_quotes: Conditions
    polarity: Polarity
    strength: Strength
    origin_hint: Origin  # a proposal; a selection alone is always inferred
    scope_hint: Literal["current", "baseline", "unknown"]
    source_ids: list[str]
    quote: str | None  # exact text for explicit claims; null for a selection hypothesis
    bindings: list[BindingSpec]


class ExtractionResult(TypedDict):
    candidates: list[ExtractedCandidate]
    questions: list[str]


class Suggestion(TypedDict):
    target_id: str
    binding: BindingSpec  # soft only; never specified/confirmed/consented
    source_ids: list[str]
    reason: str
    fea_constraint_ids: NotRequired[list[str]]  # FEA->PI hypothesis, never a direct PI claim


class Proposal(TypedDict):
    suggestions: list[Suggestion]
    questions: list[str]


class ModelConstraint(TypedDict):
    id: str
    target_id: str
    binding: BindingSpec
    selector: Selector
    conditions: Conditions
    source_ids: list[str]


class ProposalInput(ExtractionInput):
    constraints: list[ModelConstraint]


class Constraint(TypedDict):
    id: str
    target_id: str
    binding_ref: ObjectRef | None
    binding: BindingSpec
    selector: Selector
    conditions: Conditions
    origin: Origin
    confirmed: bool
    source_refs: list[ObjectRef]


class MemoryContext(TypedDict):
    context_id: str
    basis: Basis
    model_input: ProposalInput
    source_refs: dict[str, list[ObjectRef]]  # alias -> complete internal evidence bundle
    constraints: list[Constraint]
    questions: list[str]
    blocked: bool
    retrieval_status: Literal["complete", "partial", "unavailable"]


class PIValue(TypedDict):
    status: MapStatus
    values: list[str] | None
    constraint_ids: list[str]
    source_refs: list[ObjectRef]


class FEAValue(TypedDict):
    status: MapStatus
    preference: Literal["prefer", "avoid", "require"] | None
    constraint_ids: list[str]
    source_refs: list[ObjectRef]


class Target(TypedDict):
    target_id: str
    garment_type: str  # target selector, not PI Type
    product_information: dict[str, PIValue]
    consumer_needs: dict[str, dict[str, dict[str, FEAValue]]]


class TargetMap(TypedDict):
    contract_version: str
    registry_version: str
    context_id: str
    targets: list[Target]
    constraints: list[Constraint]
    questions: list[str]
    basis: Basis


class ProductSource(TypedDict):
    source_id: str
    url: str
    collected_at: str


class ProductProvenance(TypedDict):
    kind: Literal["raw_metadata", "provided_label", "verified_label", "model_interpretation", "unknown"]
    source_field: str | None
    quote: str | None
    verifier: str | None
    evidence_ref: str | None  # supplier's evidence, never a user MemoryItem reference
    verified_at: str | None


class PIObservation(TypedDict):
    domain: Literal["PI"]
    feature: str
    values: list[str] | None


class FEAObservation(TypedDict):
    domain: Literal["FEA"]
    category: str
    subcategory: str
    tag: str
    present: bool | None  # product claim, not the user's preference


class ProductAssertion(TypedDict):
    observation: PIObservation | FEAObservation
    status: Literal["confirmed", "inferred", "unknown", "conflict"]
    provenance: list[ProductProvenance]


class ImageRegion(TypedDict):
    region_id: str
    garment_type: str
    box: list[float]


class ImageSource(TypedDict):
    image_id: str
    kind: Literal["local", "remote"]
    location: str  # relative to configured image root, or supplier HTTPS URL; no fetching
    source_revision: str  # supplier must change this when bytes/regions change
    sha256: str | None  # supplied bytes fingerprint, not inferred from a URL
    regions: list[ImageRegion]  # [] if no supplied named regions; custom boxes remain possible


class CatalogRecord(TypedDict):
    format_version: str
    product_id: str
    source: ProductSource
    title: str
    description: str | None
    garment_type: str
    raw_metadata: dict[str, JSONValue]
    images: list[ImageSource]
    labels: list[ProductAssertion]


class ProductMap(TypedDict):
    subject: Literal["product"]
    product_id: str
    raw_version: int
    map_version: int
    registry_version: str
    assertions: list[ProductAssertion]


class SearchHit(TypedDict):
    product_id: str
    product_map_version: int
    score: float
    matched_constraint_ids: list[str]
    unknown_constraint_ids: list[str]


class SearchResult(TypedDict):
    target_id: str
    hits: list[SearchHit]
    status: Literal["results", "no_results", "blocked"]
    basis: Basis


class CandidateCard(TypedDict):
    candidate_id: str
    target_id: str
    product_id: str
    product_map_version: int
    image_id: str | None
    image_version: int | None
    position: int


class CandidateSet(StoredObject):
    target_ids: list[str]
    cards: list[CandidateCard]
    compared_features: list[FeaturePath]
    basis: Basis


class ComparisonRound(StoredObject):
    candidate_set_ref: ObjectRef
    question_refs: list[ObjectRef]
    status: Literal["active", "replaced", "closed"]


class FeedbackAction(TypedDict):
    op: Literal["submit_feedback"]
    round_id: str | None
    candidate_set_id: str | None
    reaction: Literal["selected", "none", "unsure", "text_only", "question_skipped"]
    selections: list[Selection]
    text: str | None
    question_id: str | None


class Feedback(StoredObject):
    reaction: Literal["selected", "none", "unsure", "text_only", "question_skipped"]
    round_ref: ObjectRef | None
    candidate_set_ref: ObjectRef | None
    question_ref: ObjectRef | None
    evidence_refs: list[ObjectRef]
    interpretation_ref: ObjectRef


class PublicError(TypedDict):
    code: str
    message: str


class InterpretationState(StoredObject):
    feedback_ref: ObjectRef
    status: Literal["pending", "complete", "failed", "stale"]
    extraction_key: str | None
    candidate_refs: list[ObjectRef]
    question_refs: list[ObjectRef]
    error: PublicError | None


class CreateAction(TypedDict):
    op: Literal["create", "create_long_term"]
    memory: MemoryContent
    source_refs: list[ObjectRef]
    bindings: list[BindingSpec]
    confirmation_event_ref: ObjectRef | None
    consent_event_ref: ObjectRef | None  # null for short-term create


class ConfirmAction(TypedDict):
    op: Literal["confirm", "confirm_bindings"]
    memory_id: str
    expected_version: int
    confirmation_event_ref: ObjectRef
    binding_confirmations: list[ObjectRef]


class ProposeBindingsAction(TypedDict):
    op: Literal["propose_bindings"]
    memory_id: str
    expected_version: int
    bindings: list[BindingSpec]
    source_refs: list[ObjectRef]


class PromoteAction(TypedDict):
    op: Literal["promote"]
    memory_id: str
    expected_version: int
    consent_event_ref: ObjectRef


class ReplaceAction(TypedDict):
    op: Literal["replace"]
    memory_id: str
    expected_version: int
    memory: MemoryContent
    bindings: list[BindingSpec]
    source_refs: list[ObjectRef]
    confirmation_event_ref: ObjectRef
    consent_event_ref: ObjectRef | None


class RemoveAction(TypedDict):
    op: Literal["withdraw", "delete"]
    memory_id: str
    expected_version: int
    user_event_ref: ObjectRef


class RecordExtractionAction(TypedDict):
    op: Literal["record_extraction"]  # internal service only; never an HTTP/model command
    feedback_ref: ObjectRef
    extraction_key: str
    result: ExtractionResult | None
    error: PublicError | None


class SelectFinalAction(TypedDict):
    op: Literal["select_final"]
    candidate_set_ref: ObjectRef
    candidate_id: str


class EndRequestAction(TypedDict):
    op: Literal["end_request"]


class RecordComparisonAction(TypedDict):
    op: Literal["record_comparison"]  # trusted service, atomic response + confirmed interpretation
    feedback: FeedbackAction
    memory: MemoryContent | None
    source_refs: list[ObjectRef]
    bindings: list[BindingSpec]
    confirmation_event_ref: ObjectRef | None


StoreAction = (
    FeedbackAction | CreateAction | ConfirmAction | ProposeBindingsAction | PromoteAction
    | ReplaceAction | RemoveAction | RecordExtractionAction | SelectFinalAction | EndRequestAction | RecordComparisonAction
)


class BatchInput(TypedDict):
    contract_version: str
    batch_id: str
    request_id: str
    expected: Expected
    actions: list[StoreAction]


class BatchReceipt(TypedDict):
    outcome: Literal["applied", "unchanged"]  # rejection raises StyleMateError, no partial receipt
    batch_id: str
    request_id: str
    request_revision: int
    profile_revision: int
    changed_refs: list[ObjectRef]
    evidence_refs: list[ObjectRef]
    interpretation_ref: ObjectRef | None


class FinalSelection(TypedDict):
    candidate_set_ref: ObjectRef
    candidate_id: str
    target_id: str
    product_id: str
    product_map_version: int


class RequestState(TypedDict):
    id: str
    revision: int
    status: Literal["open", "closed", "expired"]
    mode: Literal["onboarding", "shopping"]
    targets: list[TargetSpec]
    final_selection: FinalSelection | None


class RequestRecord(RequestState):
    """Internal store request; ConsumerState uses the smaller RequestState view."""

    user_id: str
    contract_version: str
    registry_version: str
    timezone: str
    created_at: str
    updated_at: str
    retention_until: str
    max_until: str


class MemorySnapshot(TypedDict):
    contract_version: str
    registry_version: str
    request: RequestRecord
    profile_revision: int
    now: str
    memories: list[MemoryItem]
    evidence: list[Evidence]
    bindings: list[FeatureBinding]
    confirmations: list[Confirmation]
    consents: list[Consent]
    links: list[MemoryLink]
    feedback: list[Feedback]
    interpretations: list[InterpretationState]
    rounds: list[ComparisonRound]
    candidate_sets: list[CandidateSet]
    questions: list[Question]


class StartRequestUI(TypedDict):
    op: Literal["start_request"]
    mode: Literal["onboarding", "shopping"]
    timezone: str
    targets: list[TargetSpec]
    text: str | None


class SimpleUI(TypedDict):
    op: Literal["resume_request", "explore", "end_request"]


class RetryExtractionUI(TypedDict):
    op: Literal["retry_extraction"]
    feedback_ref: ObjectRef


class ReviewUI(TypedDict):
    op: Literal["prepare_review"]
    purpose: ReviewPurpose
    subject_refs: list[ObjectRef]
    proposed_text: str | None  # edit input only; server builds the displayed meaning


class RespondReviewUI(TypedDict):
    op: Literal["respond_review"]
    display_ref: ObjectRef
    decision: Literal["accept", "decline", "skip"]


class RespondComparisonUI(TypedDict):
    op: Literal["respond_comparison"]
    candidate_set_ref: ObjectRef
    candidate_id: str | None
    decision: Literal["choose", "neither", "unsure"]
    text: NotRequired[str | None]  # optional reason/correction, accepted with the image choice


UIAction = StartRequestUI | SimpleUI | RetryExtractionUI | ReviewUI | RespondReviewUI | RespondComparisonUI | FeedbackAction | SelectFinalAction


class ConsumerCommand(TypedDict):
    contract_version: str
    command_id: str
    request_id: str | None
    expected: Expected | None
    action: UIAction


class MemoryView(TypedDict):
    ref: ObjectRef
    content: str
    scope: Scope
    confirmed: bool
    status: Lifecycle


class CardView(CandidateCard):
    title: str
    image_url: str | None  # server-resolved ID route or permitted supplier reference


class ReviewView(TypedDict):
    ref: ObjectRef
    purpose: ReviewPurpose
    snapshot: ReviewSnapshot  # visible meaning only, never accepted back as authority


class QuestionView(TypedDict):
    ref: ObjectRef
    text: str
    target_id: str | None
    options: list[str]
    status: Literal["open", "answered", "skipped"]


class ConsumerState(TypedDict):
    comparison: NotRequired[dict[str, JSONValue] | None]
    contract_version: str
    state_version: int
    request: RequestState | None
    requests: list[RequestState]
    expected: Expected | None
    phase: Literal["onboarding", "request", "exploring", "review", "wrap_up"]
    operation: Literal["idle", "running", "interpretation_pending", "blocked", "no_results", "stale", "error"]
    memories: list[MemoryView]
    cards: list[CardView]
    reviews: list[ReviewView]
    questions: list[QuestionView]
    error: PublicError | None


class ConsumerResult(TypedDict):
    outcome: Literal["accepted", "applied", "unchanged", "rejected"]
    state: ConsumerState
    error: PublicError | None


class QuestionDraft(TypedDict):
    text: str
    target_id: str | None
    subject_refs: list[ObjectRef]
    options: list[str]


class CandidatePlan(TypedDict):
    cards: list[CandidateCard]
    compared_features: list[FeaturePath]
    questions: list[QuestionDraft]
    basis: Basis


class CatalogFreshness(Protocol):
    """D supplies current catalog versions; A injects this into B's write boundary."""

    def current_versions(self, product_ids: list[str], image_ids: list[str]) -> CatalogVersions: ...


class RegistryPort(Protocol):
    """A1 / registry.py: read the canonical resource, never copy enums here."""

    version: str

    def describe(self) -> dict[str, JSONValue]: ...

    def validate_binding(self, binding: BindingSpec, garment_type: str | None) -> None: ...

    def validate_observation(self, observation: PIObservation | FEAObservation, garment_type: str | None) -> None: ...


class MemoryStorePort(Protocol):
    """B / store.py. None keeps legacy behavior; v1 must be explicit.

    Existing legacy keyword arguments remain supported by the implementation.
    Snapshot may include unconfirmed items; context owns eligibility filtering.
    """

    def start_request(
        self, user_id: str, *, input_id: str, text: str | None, timezone: str,
        contract_version: str | None = None, registry_version: str | None = None,
        mode: str = "shopping", targets: list[TargetSpec] | None = None,
    ) -> RequestRecord: ...

    def snapshot(
        self, user_id: str, request_id: str, *, contract_version: str | None = None,
        include_closed: bool = False,
    ) -> MemorySnapshot: ...

    def apply_batch(
        self, user_id: str, request_id: str, *, batch_id: str, actions: list[StoreAction],
        contract_version: str | None = None, expected: Expected | None = None,
        expected_request_revision: int | None = None, expected_profile_revision: int | None = None,
        catalog_freshness: CatalogFreshness | None = None,
    ) -> BatchReceipt: ...

    def issue_display(
        self, user_id: str, request_id: str, *, purpose: ReviewPurpose,
        snapshot: ReviewSnapshot, basis: Basis,
    ) -> ReviewDisplay: ...

    def record_user_event(
        self, user_id: str, request_id: str, *, command_id: str,
        display_ref: ObjectRef, purpose: ReviewPurpose, expected: Expected,
    ) -> ObjectRef: ...

    def interpretation_status(self, user_id: str, request_id: str, feedback_ref: ObjectRef) -> InterpretationState: ...

    def publish_candidates(
        self, user_id: str, request_id: str, *, batch_id: str,
        plan: CandidatePlan, catalog_freshness: CatalogFreshness,
    ) -> ComparisonRound: ...


class ModelGateway(Protocol):
    """C1 / llm.py, codex_llm.py. No IDs, versions, authority or writes."""

    def complete(
        self, instructions: str, payload: dict[str, JSONValue], schema: dict[str, JSONValue],
    ) -> dict[str, JSONValue]: ...

    def extract(self, inputs: ExtractionInput) -> ExtractionResult: ...

    def propose(self, inputs: ProposalInput) -> Proposal: ...


class SemanticSearch(Protocol):
    """C2: only source references; eligibility must be checked against SQLite."""

    def search(self, query: str, eligible_refs: list[ObjectRef], *, index_version: str) -> list[ObjectRef]: ...


class ContextBuilder(Protocol):
    """C2 / context.build_context_v1 (function matching __call__)."""

    def __call__(
        self, snapshot: MemorySnapshot, targets: list[TargetSpec], *, registry: RegistryPort,
        semantic: SemanticSearch | None = None, char_budget: int = 6000,
    ) -> MemoryContext: ...


class TargetBuilder(Protocol):
    """C3 / inference.infer_v1 (function matching __call__)."""

    def __call__(self, context: MemoryContext, adapter: ModelGateway, *, registry: RegistryPort) -> TargetMap: ...


class CatalogPort(CatalogFreshness, Protocol):
    """D1-D3 / catalog.py and product/search modules. No user-memory writes."""

    def import_records(self, records: list[CatalogRecord]) -> CatalogVersions: ...

    def export_records(self) -> list[CatalogRecord]: ...

    def get_product_map(self, product_id: str) -> ProductMap: ...

    def save_product_map(self, product_map: ProductMap, *, expected_raw_version: int, expected_map_version: int | None) -> ProductMap: ...

    def resolve_image(self, image_id: str, *, version: int) -> ImageSource: ...


class ProductMapBuilder(Protocol):
    """D2 / catalog_mapping.build_product_map; code validates model interpretations."""

    def __call__(self, record: CatalogRecord, *, raw_version: int, registry: RegistryPort, gateway: ModelGateway) -> ProductMap: ...


class ProductSearcher(Protocol):
    """D3 / product_search.search_products."""

    def __call__(self, target_map: TargetMap, target_id: str, catalog: CatalogPort) -> SearchResult: ...


class CandidateBuilder(Protocol):
    """D3 / comparison.build_candidate_cards; B assigns set/round IDs."""

    def __call__(self, results: list[SearchResult], target_map: TargetMap, catalog: CatalogPort) -> CandidatePlan: ...


class ConsumerService(Protocol):
    """A2 service; E1 fixture and E2 HTTP adapter implement the same boundary.

    The service is constructed with a single trusted user_id. HTTP never accepts
    it, a DB/catalog path, a raw StoreAction or a TrustedUserEvent from the UI.
    """

    def state(self, request_id: str | None = None) -> ConsumerState: ...

    def command(self, command: ConsumerCommand) -> ConsumerResult: ...


def validate_ref(value: object) -> ObjectRef:
    """Small shape check only; ownership/existence/latest version belong to B."""
    if (
        not isinstance(value, dict) or set(value) != {"type", "id", "version"}
        or value.get("type") not in get_args(RefType)
        or not isinstance(value.get("id"), str) or not value["id"].strip()
        or len(value["id"]) > 128
        or type(value.get("version")) is not int or value["version"] < 1
    ):
        raise StyleMateError("invalid_input", "객체 참조 형식이 유효하지 않습니다.")
    return ObjectRef(type=value["type"], id=value["id"], version=value["version"])


def _json_only(value: object) -> None:
    # json.dumps would silently coerce tuples and non-string object keys.
    if isinstance(value, dict) and all(type(k) is str for k in value):
        for item in value.values():
            _json_only(item)
    elif isinstance(value, list):
        for item in value:
            _json_only(item)
    elif value is not None and type(value) not in (str, bool, int, float):
        raise ValueError("not JSON")


def batch_fingerprint(contract_version: str, request_id: str, actions: list[StoreAction]) -> str:
    """Owner-scoped receipt key is (user_id,batch_id); expected is excluded.

    Do not persist this general payload hash after deletion. Existing content-free
    deletion nonce/tombstone rules still apply. This is not command authorization.
    """
    if contract_version != CONTRACT_VERSION:
        raise StyleMateError("unsupported_contract", "지원하지 않는 저장 계약입니다.")
    if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128:
        raise StyleMateError("invalid_input", "요청 ID가 유효하지 않습니다.")
    if not isinstance(actions, list) or not 1 <= len(actions) <= 32 or any(not isinstance(a, dict) for a in actions):
        raise StyleMateError("invalid_input", "batch action 목록이 유효하지 않습니다.")
    try:
        _json_only(actions)
        body = json.dumps(
            {"contract_version": contract_version, "request_id": request_id, "actions": actions},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise StyleMateError("invalid_input", "유효한 UTF-8 JSON이 필요합니다.") from None
    if len(body) > 256 * 1024:
        raise StyleMateError("invalid_input", "batch 입력 크기를 초과했습니다.")
    return hashlib.sha256(body).hexdigest()
