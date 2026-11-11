"""Build the API Gateway proxy events the handlers expect."""

import json


def api_event(method, resource, *, body=None, query=None, path_params=None):
    return {
        "httpMethod": method,
        "resource": resource,
        "path": resource,
        "queryStringParameters": query,
        "pathParameters": path_params,
        "body": None if body is None else json.dumps(body),
    }


def response_body(result):
    return json.loads(result["body"])
