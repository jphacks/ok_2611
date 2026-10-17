"""AIの根拠4分類。生成結果の正規化と応答検証で同じ対応表を使う。"""

SOURCE_PRIORITY = {"menu_text": 0, "recipe_inference": 1, "dish_name_inference": 2, "unavailable": 3}
ALLERGEN_STATUS_BY_SOURCE = {
    "menu_text": "explicit_present",
    "recipe_inference": "possible",
    "dish_name_inference": "possible",
    "unavailable": "unknown",
}
DIETARY_STATUS_BY_SOURCE = {
    "menu_text": "explicit_conflict",
    "recipe_inference": "possible_conflict",
    "dish_name_inference": "possible_conflict",
    "unavailable": "unknown",
}


def validate_ai_classification(status: str, source: str, evidence: str, status_by_source: dict[str, str]) -> None:
    """正規化後・保存済みデータの最終検証。値や根拠を例外メッセージに含めない。"""
    if source not in status_by_source or status_by_source[source] != status:
        raise ValueError("invalid AI classification")
    if source != "unavailable" and not evidence.strip():
        raise ValueError("AI evidence is required")
