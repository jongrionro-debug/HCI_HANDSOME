"""Legacy runtime vocabulary and opt-in Park PI/FEA registry.

The legacy vocabulary and `pdf` metadata came from the earlier feature-map
design, not from Team4_mid-term_report.pdf. The report defines the system flow
without fixing this complete enum set or the final product catalog schema.
Park values come from the generated copy of the canonical Feature Map JSON.
Callers should read these registries rather than copy enums into other modules.
"""

from __future__ import annotations

from copy import deepcopy
from importlib import resources
import json
from typing import Any, get_args

from .contracts import (
    BindingSpec, FEAObservation, FEAValue, FeaturePath, LEGACY_REGISTRY_VERSION,
    MapStatus, PIObservation, PIValue, Polarity, Strength, Target,
    V1_REGISTRY_VERSION, validate_ref,
)
from .errors import StyleMateError


REGISTRY_VERSION = LEGACY_REGISTRY_VERSION

_PDF_SOURCE_BY_ATTRIBUTE: dict[str, list[str]] = {
    "Garment Type": ["Image", "Metadata"],
    "Primary Color": ["Image", "Metadata"],
    "Visual Fit": ["Image", "Metadata"],
    "Garment-specific Length": ["Image", "Metadata"],
    "Sleeve Length": ["Image", "Metadata"],
    "Neckline Type": ["Image", "Metadata"],
    "Pattern Type": ["Image", "Metadata"],
    "Logo Visibility + Logo Size": ["Image"],
    "Fabric Type": ["Image", "Metadata"],
    "Surface Texture": ["Image"],
    "Item Style Affinity": ["Image", "Metadata", "Inference"],
    "Visual Mood": ["Image", "Inference"],
    "Formality Level": ["Image", "Metadata", "Inference"],
    "Suitable Seasons": ["Metadata", "Inference"],
    "Thickness": ["Metadata", "Inference"],
    "Thermal Insulation": ["Metadata", "Inference"],
    "Functional Properties": ["Metadata"],
}


def _meta(
    label_ko: str,
    group: str,
    attribute: str,
    values: list[str | int],
    *,
    value_type: str = "enum",
    categories: list[str] | None = None,
    source: list[str] | None = None,
    notes: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Create JSON-safe metadata while keeping the registry readable."""

    source_names = list(source or _PDF_SOURCE_BY_ATTRIBUTE.get(attribute, []))
    result: dict[str, Any] = {
        "label_ko": label_ko,
        "pdf": {
            "feature_group": group,
            "attribute": attribute,
            "allowed_values": list(values),
            "applicable_categories": list(categories or ["All"]),
            "extraction_source": source_names,
        },
        "value_type": value_type,
        "applicable_categories": categories or ["All"],
        "source": source_names,
    }
    if notes:
        result["notes"] = notes
    result.update(extra)
    return result


_ALL_CATEGORIES = ["Tops", "Bottoms", "Outerwear", "Dresses"]
_TOPS = ["Tops"]
_BOTTOMS = ["Bottoms"]
_OUTERWEAR = ["Outerwear"]
_DRESSES = ["Dresses"]


# The canonical strings intentionally retain the strings from the supplied
# Feature Map.  They are values a model may return, not translated display
# strings.
FEATURES: dict[str, dict[str, Any]] = {
    "garment_type": {
        "values": [
            "T-shirt",
            "Shirt",
            "Blouse",
            "Knit/Sweater",
            "Sweatshirt",
            "Hoodie",
            "Polo",
            "Sleeveless",
            "Pants",
            "Skirt",
            "Jacket",
            "Coat",
            "Cardigan",
            "Vest",
            "Dress",
        ],
        **_meta(
            "아이템 종류",
            "01. Category",
            "Garment Type",
            [
                "T-shirt",
                "Shirt",
                "Blouse",
                "Knit/Sweater",
                "Sweatshirt",
                "Hoodie",
                "Polo",
                "Sleeveless",
                "Pants",
                "Skirt",
                "Jacket",
                "Coat",
                "Cardigan",
                "Vest",
                "Dress",
            ],
            categories=_ALL_CATEGORIES,
        ),
    },
    "color": {
        "values": [
            "Black",
            "White",
            "Ivory",
            "Cream",
            "Gray",
            "Charcoal",
            "Beige",
            "Brown",
            "Navy",
            "Blue",
            "Green",
            "Khaki",
            "Red",
            "Pink",
            "Yellow",
            "Purple",
            "Multi-color",
        ],
        **_meta(
            "기본 색상",
            "02. Color",
            "Primary Color",
            [
                "Black",
                "White",
                "Ivory",
                "Cream",
                "Gray",
                "Charcoal",
                "Beige",
                "Brown",
                "Navy",
                "Blue",
                "Green",
                "Khaki",
                "Red",
                "Pink",
                "Yellow",
                "Purple",
                "Multi-color",
            ],
            categories=_ALL_CATEGORIES,
        ),
    },
    "fit": {
        "values": ["Slim", "Regular", "Relaxed", "Oversized"],
        **_meta(
            "전체 핏",
            "03. Fit & Silhouette",
            "Visual Fit",
            ["Slim", "Regular", "Relaxed", "Oversized"],
            categories=_ALL_CATEGORIES,
        ),
    },
    "length": {
        # Length is the only reduced feature whose allowed values depend on
        # the target garment type.  The per-type map is part of the metadata.
        "values": [
            "Cropped",
            "Waist-length",
            "Hip-length",
            "Below-hip",
            "Short",
            "Knee-length",
            "Ankle-length",
            "Full-length",
            "Mini",
            "Above-knee",
            "Midi",
            "Maxi",
            "Thigh-length",
            "Long",
        ],
        **_meta(
            "기장",
            "04. Length",
            "Garment-specific Length",
            [
                "Cropped",
                "Waist-length",
                "Hip-length",
                "Below-hip",
                "Short",
                "Knee-length",
                "Ankle-length",
                "Full-length",
                "Mini",
                "Above-knee",
                "Midi",
                "Maxi",
                "Thigh-length",
                "Long",
            ],
            categories=_ALL_CATEGORIES,
            notes="PDF의 상의·바지·스커트·아우터·드레스별 허용 길이를 그대로 적용한다.",
            by_garment_type={
                "T-shirt": ["Cropped", "Waist-length", "Hip-length", "Below-hip"],
                "Shirt": ["Cropped", "Waist-length", "Hip-length", "Below-hip"],
                "Blouse": ["Cropped", "Waist-length", "Hip-length", "Below-hip"],
                "Knit/Sweater": ["Cropped", "Waist-length", "Hip-length", "Below-hip"],
                "Sweatshirt": ["Cropped", "Waist-length", "Hip-length", "Below-hip"],
                "Hoodie": ["Cropped", "Waist-length", "Hip-length", "Below-hip"],
                "Polo": ["Cropped", "Waist-length", "Hip-length", "Below-hip"],
                "Sleeveless": ["Cropped", "Waist-length", "Hip-length", "Below-hip"],
                "Pants": ["Short", "Knee-length", "Cropped", "Ankle-length", "Full-length"],
                "Skirt": ["Mini", "Above-knee", "Knee-length", "Midi", "Maxi"],
                "Jacket": ["Cropped", "Waist-length", "Hip-length", "Thigh-length", "Knee-length", "Long"],
                "Coat": ["Cropped", "Waist-length", "Hip-length", "Thigh-length", "Knee-length", "Long"],
                "Cardigan": ["Cropped", "Waist-length", "Hip-length", "Thigh-length", "Knee-length", "Long"],
                "Vest": ["Cropped", "Waist-length", "Hip-length", "Thigh-length", "Knee-length", "Long"],
                "Dress": ["Mini", "Above-knee", "Knee-length", "Midi", "Ankle-length", "Maxi"],
            },
        ),
    },
    "sleeve_length": {
        "values": ["Sleeveless", "Cap", "Short", "Elbow-length", "Three-quarter", "Long"],
        **_meta(
            "소매 길이",
            "05. Sleeve",
            "Sleeve Length",
            ["Sleeveless", "Cap", "Short", "Elbow-length", "Three-quarter", "Long"],
            categories=["Tops", "Outerwear", "Dresses"],
        ),
    },
    "neckline": {
        "values": [
            "Crew",
            "V-neck",
            "U-neck",
            "Square",
            "Boat",
            "Sweetheart",
            "Halter",
            "Off-shoulder",
            "One-shoulder",
            "Mock Neck",
            "Turtleneck",
            "Strapless",
        ],
        **_meta(
            "넥라인",
            "06. Neckline & Collar",
            "Neckline Type",
            [
                "Crew",
                "V-neck",
                "U-neck",
                "Square",
                "Boat",
                "Sweetheart",
                "Halter",
                "Off-shoulder",
                "One-shoulder",
                "Mock Neck",
                "Turtleneck",
                "Strapless",
            ],
            categories=["Tops", "Outerwear", "Dresses"],
        ),
    },
    "pattern": {
        "values": [
            "Solid",
            "Stripe",
            "Check",
            "Plaid",
            "Dot",
            "Floral",
            "Animal",
            "Camouflage",
            "Geometric",
            "Abstract",
            "Other",
        ],
        **_meta(
            "무늬",
            "07. Pattern",
            "Pattern Type",
            [
                "Solid",
                "Stripe",
                "Check",
                "Plaid",
                "Dot",
                "Floral",
                "Animal",
                "Camouflage",
                "Geometric",
                "Abstract",
                "Other",
            ],
            categories=_ALL_CATEGORIES,
        ),
    },
    "logo": {
        "values": ["None", "Small", "Medium", "Large"],
        **_meta(
            "로고 크기",
            "08. Graphic & Logo",
            "Logo Visibility + Logo Size",
            ["None", "Small", "Medium", "Large"],
            categories=_ALL_CATEGORIES,
            notes="소비자용 단일 feature로 축약한 값. PDF의 Logo Visibility와 Logo Size를 None/Small/Medium/Large로 표현한다.",
            source=["Image"],
        ),
    },
    "fabric": {
        "values": [
            "Denim",
            "Jersey",
            "Knit",
            "Twill",
            "Fleece",
            "Corduroy",
            "Satin",
            "Chiffon",
            "Tweed",
            "Canvas",
            "Lace",
            "Mesh",
            "Leather",
            "Faux Leather",
        ],
        **_meta(
            "원단",
            "09. Material",
            "Fabric Type",
            [
                "Denim",
                "Jersey",
                "Knit",
                "Twill",
                "Fleece",
                "Corduroy",
                "Satin",
                "Chiffon",
                "Tweed",
                "Canvas",
                "Lace",
                "Mesh",
                "Leather",
                "Faux Leather",
            ],
            categories=_ALL_CATEGORIES,
            notes="Fiber Composition과 혼용률은 소비자용 목표 feature에서 제외했다.",
        ),
    },
    "texture": {
        "values": [
            "Smooth",
            "Ribbed",
            "Cable-knit",
            "Waffle",
            "Fuzzy",
            "Bouclé",
            "Quilted",
            "Corded",
            "Lace-textured",
        ],
        **_meta(
            "표면 질감",
            "10. Texture & Finish",
            "Surface Texture",
            [
                "Smooth",
                "Ribbed",
                "Cable-knit",
                "Waffle",
                "Fuzzy",
                "Bouclé",
                "Quilted",
                "Corded",
                "Lace-textured",
            ],
            categories=_ALL_CATEGORIES,
        ),
    },
    "style": {
        "values": [
            "Casual",
            "Minimal",
            "Street",
            "Classic",
            "Formal",
            "Sporty",
            "Workwear",
            "Vintage",
            "Preppy",
            "Outdoor",
            "Romantic",
            "Chic",
        ],
        **_meta(
            "스타일",
            "14. Style & Mood",
            "Item Style Affinity",
            [
                "Casual",
                "Minimal",
                "Street",
                "Classic",
                "Formal",
                "Sporty",
                "Workwear",
                "Vintage",
                "Preppy",
                "Outdoor",
                "Romantic",
                "Chic",
            ],
            categories=_ALL_CATEGORIES,
            value_type="multi-label",
        ),
    },
    "mood": {
        "values": ["Clean", "Soft", "Rugged", "Edgy", "Relaxed", "Refined", "Bold", "Understated"],
        **_meta(
            "분위기",
            "14. Style & Mood",
            "Visual Mood",
            ["Clean", "Soft", "Rugged", "Edgy", "Relaxed", "Refined", "Bold", "Understated"],
            categories=_ALL_CATEGORIES,
            value_type="multi-label",
        ),
    },
    "formality": {
        "values": [1, 2, 3, 4, 5],
        **_meta(
            "격식 정도",
            "15. Formality",
            "Formality Level",
            [1, 2, 3, 4, 5],
            categories=_ALL_CATEGORIES,
            notes="1=Very Casual, 2=Casual, 3=Smart Casual, 4=Business Casual, 5=Formal.",
            labels={
                "1": "Very Casual",
                "2": "Casual",
                "3": "Smart Casual",
                "4": "Business Casual",
                "5": "Formal",
            },
            value_type="ordinal",
        ),
    },
    "season": {
        "values": ["Spring", "Summer", "Autumn", "Winter"],
        **_meta(
            "계절",
            "16. Seasonality",
            "Suitable Seasons",
            ["Spring", "Summer", "Autumn", "Winter"],
            categories=_ALL_CATEGORIES,
            value_type="multi-label",
        ),
    },
    "thickness": {
        "values": ["Thin", "Medium", "Thick"],
        **_meta(
            "두께",
            "13. Thickness & Function",
            "Thickness",
            ["Thin", "Medium", "Thick"],
            categories=_ALL_CATEGORIES,
        ),
    },
    "warmth": {
        "values": ["Low", "Medium", "High"],
        **_meta(
            "보온성",
            "13. Thickness & Function",
            "Thermal Insulation",
            ["Low", "Medium", "High"],
            categories=_ALL_CATEGORIES,
        ),
    },
    "functions": {
        "values": ["Water-resistant", "Waterproof", "Wind-resistant", "Breathable", "Stretch", "Quick-drying"],
        **_meta(
            "기능",
            "13. Thickness & Function",
            "Functional Properties",
            ["Water-resistant", "Waterproof", "Wind-resistant", "Breathable", "Stretch", "Quick-drying"],
            categories=_ALL_CATEGORIES,
            value_type="multi-label",
        ),
    },
}


_CATEGORY_BY_GARMENT_TYPE: dict[str, str] = {
    "T-shirt": "Tops",
    "Shirt": "Tops",
    "Blouse": "Tops",
    "Knit/Sweater": "Tops",
    "Sweatshirt": "Tops",
    "Hoodie": "Tops",
    "Polo": "Tops",
    "Sleeveless": "Tops",
    "Pants": "Bottoms",
    "Skirt": "Bottoms",
    "Jacket": "Outerwear",
    "Coat": "Outerwear",
    "Cardigan": "Outerwear",
    "Vest": "Outerwear",
    "Dress": "Dresses",
}

# Small aliases make the registry convenient for prompt builders while the
# nested ``pdf`` object remains the source mapping for review/debugging.
for _feature_id, _entry in FEATURES.items():
    _entry.setdefault("feature_id", _feature_id)
    _entry.setdefault("allowed_values", deepcopy(_entry["values"]))
    _entry.setdefault("applicable_to", deepcopy(_entry["applicable_categories"]))
if "length" in FEATURES:
    FEATURES["length"]["allowed_values_by_garment_type"] = deepcopy(FEATURES["length"]["by_garment_type"])


def feature_metadata(feature: str) -> dict[str, Any]:
    """Return a defensive, JSON-serializable copy of one feature's metadata."""

    if feature not in FEATURES:
        raise StyleMateError("unknown_feature", f"지원하지 않는 feature입니다: {feature}")
    return deepcopy(FEATURES[feature])


def registry_metadata(version: str = REGISTRY_VERSION) -> dict[str, Any]:
    """Default to the legacy registry; the new vocabulary requires opt-in."""

    if version != REGISTRY_VERSION:
        return load_registry(version).describe()
    return {"version": REGISTRY_VERSION, "features": deepcopy(FEATURES)}


def category_for_garment_type(garment_type: str) -> str | None:
    return _CATEGORY_BY_GARMENT_TYPE.get(garment_type)


def _error(message: str, *, code: str = "invalid_feature_value") -> None:
    raise StyleMateError(code, message)


def validate_values(
    feature: str,
    values: list[str | int],
    match: str = "any",
    garment_type: str | None = None,
) -> bool:
    """Validate a feature value list.

    ``match`` is part of the preference contract rather than the vocabulary:
    ``any`` and ``all`` are valid for lists, and ``range`` is reserved for
    ordinal ``formality`` values.  A successful call returns ``True``; invalid
    input raises the public ``StyleMateError`` so callers can attach a stable
    code to a rejected model response.
    """

    if feature not in FEATURES:
        _error(f"지원하지 않는 feature입니다: {feature}", code="unknown_feature")
    if match not in {"any", "all", "range"}:
        _error(f"지원하지 않는 match입니다: {match}", code="invalid_match")
    if not isinstance(values, list) or not values:
        _error(f"{feature}의 values는 비어 있지 않은 list여야 합니다")
    if len(values) != len(set((type(v).__name__, repr(v)) for v in values)):
        _error(f"{feature}의 values에는 중복이 있을 수 없습니다")

    allowed = FEATURES[feature]["values"]
    if match == "range":
        if feature != "formality" or len(values) != 2 or not all(isinstance(v, int) and not isinstance(v, bool) for v in values):
            _error("range match는 formality의 두 정수 경계에만 사용할 수 있습니다", code="invalid_match")
        if values[0] > values[1] or values[0] not in allowed or values[1] not in allowed:
            _error("formality range가 허용 범위를 벗어났습니다")
        return True

    for value in values:
        # bool is an int subclass but must never be accepted as formality.
        if feature == "formality":
            type_ok = isinstance(value, int) and not isinstance(value, bool)
        else:
            type_ok = isinstance(value, str)
        if not type_ok or value not in allowed:
            _error(f"{feature}에 허용되지 않는 값입니다: {value!r}")

    if feature == "length" and garment_type is not None:
        if garment_type not in FEATURES["length"]["by_garment_type"]:
            _error(f"알 수 없는 garment_type입니다: {garment_type}", code="unknown_garment_type")
        allowed_for_target = FEATURES["length"]["by_garment_type"][garment_type]
        if any(value not in allowed_for_target for value in values):
            _error(f"{garment_type}에 적용할 수 없는 length 값입니다", code="not_applicable_value")
    elif feature == "length" and garment_type is None:
        _error("length 검증에는 garment_type이 필요합니다", code="missing_garment_type")

    category = category_for_garment_type(garment_type) if garment_type else None
    if category and category not in FEATURES[feature]["applicable_categories"] and "All" not in FEATURES[feature]["applicable_categories"]:
        _error(f"{feature}은 {garment_type}에 적용되지 않습니다", code="not_applicable_value")

    return True


def _string_list(value: object) -> bool:
    return (
        isinstance(value, list) and bool(value)
        and all(isinstance(v, str) and bool(v.strip()) and len(v) <= 128 for v in value)
        and len(set(value)) == len(value)
    )


def _validate_resource(document: Any) -> None:
    """Check the fixed resource's structure/counts without duplicating enums."""
    if not isinstance(document, dict) or document.get("version") != V1_REGISTRY_VERSION:
        raise ValueError("registry version")
    pi = document["product_information"]
    taxonomy = document["consumer_needs_taxonomy"]
    counts = document["counts"]
    if not isinstance(pi, dict) or len(pi) != 7 or counts["product_information_categories"] != len(pi):
        raise ValueError("PI count")
    value_count = 0
    for entry in pi.values():
        if not isinstance(entry["label_ko"], str) or type(entry["enumeration_complete"]) is not bool:
            raise ValueError("PI metadata")
        if entry["enumeration_complete"]:
            if not _string_list(entry["values"]) or entry["reported_count"] != len(entry["values"]):
                raise ValueError("PI enumeration")
            value_count += len(entry["values"])
        elif entry["values"] is not None or not _string_list(entry["published_examples"]):
            raise ValueError("incomplete enumeration")
    if value_count != 45 or counts["non_brand_product_values"] != value_count:
        raise ValueError("PI value count")
    if not isinstance(taxonomy, dict) or len(taxonomy) != 3:
        raise ValueError("FEA categories")
    tags = []
    for category, subcategories in taxonomy.items():
        if not isinstance(subcategories, dict) or not subcategories:
            raise ValueError("FEA subcategories")
        category_tags = []
        for subcategory, entries in subcategories.items():
            if not isinstance(subcategory, str) or not isinstance(entries, list) or not entries:
                raise ValueError("FEA entries")
            for entry in entries:
                if not isinstance(entry["label_ko"], str):
                    raise ValueError("FEA label")
                category_tags.append(entry["attribute"])
        if not _string_list(category_tags) or counts[f"{category.lower()}_attributes"] != len(category_tags):
            raise ValueError("FEA category count")
        tags.extend(category_tags)
    if not _string_list(tags) or len(tags) != 30 or counts["consumer_needs_attributes"] != len(tags):
        raise ValueError("FEA count")


class ParkRegistry:
    """A1 RegistryPort. Checks vocabulary/shape, never evidence or authority.

    Bindings are BindingSpec projections, not stored FeatureBinding objects.
    Null product observations make no claim and may retain unsupported fields.
    Provenance, confirmation, hard constraints and target status justification
    remain the responsibility of the store/inference/catalog modules.
    """

    def __init__(self) -> None:
        try:
            raw = resources.files(__package__).joinpath("resources/park-2025-feature-map.json").read_text(encoding="utf-8")
            self._document = json.loads(raw)
            _validate_resource(self._document)
        except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError):
            raise StyleMateError("registry_unavailable", "고정 사전 자원을 읽거나 검증할 수 없습니다.") from None
        self._pi = self._document["product_information"]
        self._taxonomy = self._document["consumer_needs_taxonomy"]
        self._fea_paths = {
            (category, subcategory, entry["attribute"])
            for category, subcategories in self._taxonomy.items()
            for subcategory, entries in subcategories.items() for entry in entries
        }

    @property
    def version(self) -> str:
        return self._document["version"]

    def describe(self) -> dict[str, Any]:
        """Preserve the source document and separate local execution limits."""
        result = deepcopy(self._document)
        result["execution"] = {
            "supported_garment_types": ["Pants"],
            "pi_matches": ["any", "all"],
            "range_supported": False,
            "brand_enumeration_supported": False,
            "price_mapping": "canonical_labels_only",
            "price_numeric_mapping_supported": False,
            "price_currency": None,
            "price_boundary_inclusion": None,
            "target_statuses": list(get_args(MapStatus)),
            "runtime_integration": True,
        }
        return result

    def _path(self, path: dict[str, Any]) -> tuple[str, ...]:
        if path.get("domain") == "PI":
            feature = path.get("feature")
            if not isinstance(feature, str) or feature not in self._pi:
                _error("PI 사전에 없는 항목입니다.", code="unsupported_mapping")
            return (feature,)
        if path.get("domain") == "FEA":
            keys = tuple(path.get(k) for k in ("category", "subcategory", "tag"))
            if not all(isinstance(k, str) for k in keys) or keys not in self._fea_paths:
                _error("FEA 사전에 없는 경로입니다.", code="unsupported_mapping")
            return keys
        _error("domain은 PI 또는 FEA여야 합니다.", code="invalid_input")

    @staticmethod
    def _supported_target(garment_type: str | None) -> None:
        # Selector classification is NOT the PI Type (e.g. Jeans/Slacks).
        if garment_type != "Pants":
            _error("이 품목의 실행 매핑은 아직 제공하지 않습니다.", code="unsupported_mapping")

    def _pi_values(self, feature: str, values: Any) -> None:
        if not _string_list(values):
            _error("PI values는 중복 없는 canonical 문자열 배열이어야 합니다.", code="invalid_input")
        allowed = self._pi[feature]["values"]
        if allowed is None:
            _error("전체 허용값이 공개되지 않은 PI 항목입니다.", code="unsupported_mapping")
        if any(v not in allowed for v in values):
            _error("사전에 없는 PI 값입니다. 자동 치환하지 않습니다.", code="unsupported_mapping")

    def validate_binding(self, binding: BindingSpec, garment_type: str | None) -> None:
        if not isinstance(binding, dict):
            _error("binding 형식이 유효하지 않습니다.", code="invalid_input")
        keys = self._path(binding)
        fields = {"domain", "polarity", "strength"} | (
            {"feature", "values", "match"} if len(keys) == 1 else {"category", "subcategory", "tag"}
        )
        if set(binding) != fields or binding["polarity"] not in get_args(Polarity) or binding["strength"] not in get_args(Strength):
            _error("binding 필드·방향·강도가 유효하지 않습니다.", code="invalid_input")
        self._supported_target(garment_type)
        if binding["polarity"] == "indifferent" and binding["strength"] != "soft":
            _error("indifferent는 soft 선호에만 사용합니다.", code="invalid_input")
        if len(keys) == 1:
            if binding["polarity"] == "indifferent":
                if binding["values"] is not None or binding["match"] is not None:
                    _error("indifferent의 values/match는 null이어야 합니다.", code="invalid_input")
            else:
                if binding["match"] not in ("any", "all"):
                    _error("이 사전은 any/all만 지원하며 range는 실행하지 않습니다.", code="unsupported_mapping")
                self._pi_values(keys[0], binding["values"])

    def validate_observation(self, observation: PIObservation | FEAObservation, garment_type: str | None) -> None:
        if not isinstance(observation, dict):
            _error("상품 관찰 형식이 유효하지 않습니다.", code="invalid_input")
        keys = self._path(observation)
        pi = len(keys) == 1
        fields = {"domain", "feature", "values"} if pi else {"domain", "category", "subcategory", "tag", "present"}
        if set(observation) != fields:
            _error("상품 관찰과 사용자 binding 필드를 섞을 수 없습니다.", code="invalid_input")
        value = observation["values" if pi else "present"]
        if value is None:
            return
        self._supported_target(garment_type)
        if pi:
            self._pi_values(keys[0], value)
        elif type(value) is not bool:
            _error("상품 태그의 present는 bool 또는 null이어야 합니다.", code="invalid_input")

    def empty_target(self, target_id: str, garment_type: str) -> Target:
        """All seven PI fields and all 30 FEA tags, with explicit null states."""
        if not all(isinstance(v, str) and bool(v.strip()) and len(v) <= 128 for v in (target_id, garment_type)):
            _error("target ID와 garment_type이 필요합니다.", code="invalid_input")
        supported = garment_type == "Pants"
        return {
            "target_id": target_id,
            "garment_type": garment_type,
            "product_information": {
                feature: {
                    "status": "unspecified" if supported and meta["values"] is not None else "unsupported",
                    "values": None, "constraint_ids": [], "source_refs": [],
                } for feature, meta in self._pi.items()
            },
            "consumer_needs": {
                category: {
                    subcategory: {
                        entry["attribute"]: {
                            "status": "unspecified" if supported else "unsupported",
                            "preference": None, "constraint_ids": [], "source_refs": [],
                        } for entry in entries
                    } for subcategory, entries in subcategories.items()
                } for category, subcategories in self._taxonomy.items()
            },
        }

    def validate_target_value(self, path: FeaturePath, value: PIValue | FEAValue, garment_type: str | None) -> None:
        """Check status/value shape only; source authority is checked by C/B."""
        if not isinstance(path, dict) or not isinstance(value, dict):
            _error("목표 항목 형식이 유효하지 않습니다.", code="invalid_input")
        keys = self._path(path)
        pi = len(keys) == 1
        path_fields = {"domain", "feature"} if pi else {"domain", "category", "subcategory", "tag"}
        field = "values" if pi else "preference"
        if set(path) != path_fields or set(value) != {"status", field, "constraint_ids", "source_refs"}:
            _error("목표 항목 필드가 유효하지 않습니다.", code="invalid_input")
        if value["status"] not in get_args(MapStatus):
            _error("알 수 없는 목표 상태입니다.", code="invalid_input")
        ids = value["constraint_ids"]
        if not isinstance(ids, list) or (ids and not _string_list(ids)) or not isinstance(value["source_refs"], list):
            _error("목표 근거 참조 형식이 유효하지 않습니다.", code="invalid_input")
        for ref in value["source_refs"]:
            validate_ref(ref)
        if value["status"] in ("specified", "inferred"):
            self._supported_target(garment_type)
            if pi:
                self._pi_values(keys[0], value[field])
            elif value[field] not in ("prefer", "avoid", "require"):
                _error("FEA 요구 방향이 유효하지 않습니다.", code="invalid_input")
        elif value[field] is not None:
            _error("이 목표 상태의 값은 null이어야 합니다.", code="invalid_input")


def load_registry(version: str) -> ParkRegistry:
    """Load an explicit v1 registry; legacy APIs retain their original default."""
    if version != V1_REGISTRY_VERSION:
        raise StyleMateError("unsupported_contract", "지원하지 않는 v1 사전 버전입니다.")
    return ParkRegistry()
