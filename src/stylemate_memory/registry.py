"""The small, consumer-facing feature vocabulary used by StyleMate.

The source feature map contains many attributes that are useful to a product
designer or an extractor.  A shopper-facing memory context only needs a small
set of attributes that can be expressed as a preference.  This module is the
single Python source of truth for that set; callers should not copy the lists
into JSON prompts or database migrations.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .errors import StyleMateError


REGISTRY_VERSION = "consumer-17-v1"

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


def registry_metadata() -> dict[str, Any]:
    """Return the registry in a form safe to put in a model context."""

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
