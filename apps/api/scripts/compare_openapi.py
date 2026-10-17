"""実装の `/openapi.json` と `contracts/openapi.yaml` の全操作（P0・P1）を照合する（05・06・07）。

  .venv/bin/python scripts/compare_openapi.py            # 差分を表示（差分があっても終了コード0）
  .venv/bin/python scripts/compare_openapi.py --strict   # 差分があれば終了コード1

照合項目：操作（パス・メソッド・operationId）、パス・クエリのパラメーター名、本文の必須項目・項目名、
応答のステータスコード、成功応答の最上位の項目名。外部（DB・Google・Gemini）には接続しない。
"""

import argparse
import sys
from pathlib import Path

import yaml

API_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_DIR))

CONTRACT = API_DIR.parent.parent / "contracts" / "openapi.yaml"
PREFIX = "/api/v1"
METHODS = ("get", "post", "put", "patch", "delete")


def _resolve(spec: dict, node: object) -> object:
    while isinstance(node, dict) and "$ref" in node:
        target: object = spec
        for part in node["$ref"].removeprefix("#/").split("/"):
            target = target[part]  # type: ignore[index]
        node = target
    return node


def _props(spec: dict, schema: object) -> tuple[set[str], set[str]]:
    """スキーマの項目名と必須項目（oneOf・anyOf・allOf は和集合）。"""
    schema = _resolve(spec, schema)
    if not isinstance(schema, dict):
        return set(), set()
    names = set((schema.get("properties") or {}).keys())
    required = set(schema.get("required") or [])
    for key in ("oneOf", "anyOf", "allOf"):
        for sub in schema.get(key) or []:
            sub_names, sub_required = _props(spec, sub)
            names |= sub_names
            required |= sub_required
    return names, required


def _paths(spec: dict, schema: object, prefix: str = "", depth: int = 0, seen: frozenset = frozenset()) -> set[str]:
    """成功応答の項目のパス（例 `dishes[].allergens[].ai.status`）。oneOf・anyOf は和集合。"""
    if depth > 8:
        return set()
    ref = schema.get("$ref") if isinstance(schema, dict) else None
    if ref in seen:
        return set()
    seen = seen | {ref} if ref else seen
    schema = _resolve(spec, schema)
    if not isinstance(schema, dict):
        return set()
    result: set[str] = set()
    for key in ("oneOf", "anyOf", "allOf"):
        for sub in schema.get(key) or []:
            result |= _paths(spec, sub, prefix, depth, seen)
    if "items" in schema:
        result |= _paths(spec, schema["items"], prefix + "[]", depth + 1, seen)
    for name, sub in (schema.get("properties") or {}).items():
        path = f"{prefix}.{name}" if prefix else name
        result.add(path)
        result |= _paths(spec, sub, path, depth + 1, seen)
    return result


def _operations(spec: dict, prefix: str, only_p0: bool) -> dict[tuple[str, str], dict]:
    result = {}
    for path, item in spec.get("paths", {}).items():
        for method in METHODS:
            op = item.get(method)
            if op is None:
                continue
            if only_p0 and op.get("x-priority") != "P0":
                continue
            result[(path.removeprefix(prefix), method)] = op
    return result


def _summary(spec: dict, op: dict) -> dict:
    params = {(p["in"], p["name"]) for p in (_resolve(spec, p) for p in op.get("parameters", []))}
    body_names: set[str] = set()
    body_required: set[str] = set()
    content = (_resolve(spec, op.get("requestBody")) or {}).get("content", {}) if op.get("requestBody") else {}
    for media in content.values():
        names, required = _props(spec, media.get("schema"))
        body_names |= names
        body_required |= required
    statuses = set(op.get("responses", {}).keys())
    success_names: set[str] = set()
    for status, response in op.get("responses", {}).items():
        if status.startswith("2"):
            for media in (_resolve(spec, response).get("content") or {}).values():
                success_names |= _paths(spec, media.get("schema"))
    return {
        "operationId": op.get("operationId"),
        "params": params,
        "body": body_names,
        "body_required": body_required,
        "statuses": statuses,
        "success": success_names,
    }


def compare() -> list[str]:
    from app.config import Settings
    from app.main import create_app

    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    implemented = create_app(Settings(_env_file=None)).openapi()
    expected_ops = _operations(contract, "", only_p0=False)
    actual_ops = _operations(implemented, PREFIX, only_p0=False)

    lines: list[str] = []
    for key in sorted(expected_ops):
        path, method = key
        label = f"{method.upper()} {path}"
        if key not in actual_ops:
            lines.append(f"- {label}: 未実装（{expected_ops[key].get('x-priority')}）")
            continue
        expected = _summary(contract, expected_ops[key])
        actual = _summary(implemented, actual_ops[key])
        for field in ("operationId",):
            if expected[field] != actual[field]:
                lines.append(f"- {label}: {field} {expected[field]} ≠ {actual[field]}")
        for field, name in (
            ("params", "パラメーター"),
            ("body", "本文の項目"),
            ("body_required", "本文の必須項目"),
            ("statuses", "ステータス"),
            ("success", "成功応答の項目（入れ子を含む）"),
        ):
            missing = expected[field] - actual[field]
            extra = actual[field] - expected[field]
            if missing:
                lines.append(f"- {label}: {name}が契約にあり実装にない {sorted(missing)}")
            if extra:
                lines.append(f"- {label}: {name}が実装にあり契約にない {sorted(extra)}")
    for key in sorted(set(actual_ops) - set(expected_ops)):
        lines.append(f"- {key[1].upper()} {key[0]}: 契約にない操作")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    lines = compare()
    print("差分なし" if not lines else "\n".join(lines))
    return 1 if (args.strict and lines) else 0


if __name__ == "__main__":
    raise SystemExit(main())
