"""API Gateway REST (payload 1.0) response helpers."""

import base64
import json
from typing import Any


class BodyError(ValueError):
    """The request body or query is invalid. Handlers turn this into HTTP 400."""


def response(status: int, body: object) -> dict[str, object]:
    """JSON proxy response. CORS is open because the demo map is a static page."""
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def parse_body(event: dict[str, Any]) -> dict[str, Any]:
    """Decode a JSON object body. Missing body is an empty object."""
    raw = event.get("body")
    if raw is None or raw == "":
        return {}
    if event.get("isBase64Encoded"):
        if not isinstance(raw, str):
            raise BodyError("body is not valid JSON")
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise BodyError("body is not valid JSON") from exc
    if not isinstance(raw, str):
        raise BodyError("body is not valid JSON")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BodyError("body is not valid JSON") from exc
    if not isinstance(data, dict):
        raise BodyError("body must be a JSON object")
    return data


def query_params(event: dict[str, Any]) -> dict[str, str]:
    raw = event.get("queryStringParameters") or {}
    if not isinstance(raw, dict):
        raise BodyError("invalid query string")
    return {str(key): "" if value is None else str(value) for key, value in raw.items()}
