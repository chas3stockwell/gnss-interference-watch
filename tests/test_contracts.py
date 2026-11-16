"""The template, the OpenAPI spec, the map boxes, and the seed script stay in sync."""

import json
import subprocess
import sys
from pathlib import Path

import yaml

from gnssiw.regions import SEED_REGIONS

ROOT = Path(__file__).resolve().parents[1]


class CfnLoader(yaml.SafeLoader):
    """Load a CloudFormation/SAM template without resolving intrinsics."""


def _construct_cfn(loader, suffix, node):
    del suffix
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_mapping(node, deep=True)


CfnLoader.add_multi_constructor("!", _construct_cfn)


def template():
    path = ROOT / "infra" / "template.yaml"
    return yaml.load(path.read_text(encoding="utf-8"), Loader=CfnLoader)


def openapi():
    path = ROOT / "docs" / "openapi.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_api_routes_match_the_openapi_spec():
    resources = template()["Resources"]
    sam_routes = set()
    for resource in resources.values():
        if resource.get("Type") != "AWS::Serverless::Function":
            continue
        events = resource.get("Properties", {}).get("Events") or {}
        for event in events.values():
            if event.get("Type") != "Api":
                continue
            props = event["Properties"]
            sam_routes.add((props["Method"].upper(), props["Path"]))

    spec_routes = set()
    for path, methods in openapi()["paths"].items():
        for method in methods:
            if method in {"get", "post", "put", "delete", "patch"}:
                spec_routes.add((method.upper(), path))

    assert sam_routes == spec_routes


def test_tables_keys_queue_and_state_machine():
    resources = template()["Resources"]
    expected = {
        "RegionsTable": [("regionId", "HASH")],
        "DailyCountsTable": [("pk", "HASH"), ("date", "RANGE")],
        "AnomaliesTable": [("date", "HASH"), ("sk", "RANGE")],
        "JobsTable": [("jobId", "HASH")],
        "SubscriptionsTable": [("subscriptionId", "HASH")],
    }
    for name, key_schema in expected.items():
        schema = resources[name]["Properties"]["KeySchema"]
        actual = [(item["AttributeName"], item["KeyType"]) for item in schema]
        assert actual == key_schema
        assert resources[name]["Properties"]["BillingMode"] == "PAY_PER_REQUEST"

    queue = resources["IngestQueue"]["Properties"]["RedrivePolicy"]
    assert queue["maxReceiveCount"] == 3

    definition = resources["AnalysisStateMachine"]["Properties"]["Definition"]
    assert definition["StartAt"] == "Detect"
    assert definition["States"]["Detect"]["Next"] == "CrossCheck"
    assert definition["States"]["CrossCheck"]["End"] is True
    assert "DetectorFunction.Arn" in definition["States"]["Detect"]["Resource"]
    assert "CrossCheckerFunction.Arn" in definition["States"]["CrossCheck"]["Resource"]


def test_each_function_makefile_copies_the_shared_library():
    resources = template()["Resources"]
    for logical_id, resource in resources.items():
        if resource.get("Type") != "AWS::Serverless::Function":
            continue
        assert resource["Metadata"]["BuildMethod"] == "makefile"
        code_uri = (ROOT / "infra" / resource["Properties"]["CodeUri"]).resolve()
        makefile = (code_uri / "Makefile").read_text(encoding="utf-8")
        assert f"build-{logical_id}:" in makefile
        assert "shared/python/gnssiw" in makefile
        assert (code_uri / "handler.py").is_file()


def test_map_regions_match_the_seed_boxes():
    documented = json.loads(
        (ROOT / "alert-show" / "web" / "regions.json").read_text(encoding="utf-8")
    )
    assert documented == [region.to_api() for region in SEED_REGIONS]


def test_seed_script_prints_regions_and_refuses_to_write():
    script = ROOT / "scripts" / "seed_regions.py"
    printed = subprocess.run(
        [sys.executable, str(script)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(printed.stdout)
    assert [region["id"] for region in payload["regions"]] == [
        "baltic",
        "black-sea",
        "north-atlantic",
        "north-pacific",
    ]
    refused = subprocess.run(
        [sys.executable, str(script), "--write"],
        capture_output=True,
        text=True,
    )
    assert refused.returncode != 0
    assert "TODO" in refused.stderr
