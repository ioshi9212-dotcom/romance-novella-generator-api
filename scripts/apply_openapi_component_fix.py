from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def replace_once(path: str, old: str, new: str) -> None:
    file_path = ROOT / path
    text = file_path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Pattern not found in {path}: {old[:120]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app/novella_openapi_actions.py",
    '''def _load_component_schema(filename: str) -> dict[str, Any]:
    schema = json.loads((SCHEMAS_DIR / filename).read_text(encoding="utf-8"))
    schema = deepcopy(schema)
    schema.pop("$schema", None)
    schema.pop("$id", None)
    return schema
''',
    '''def _load_component_schema(filename: str) -> dict[str, Any]:
    schema = json.loads((SCHEMAS_DIR / filename).read_text(encoding="utf-8"))
    schema = deepcopy(schema)
    schema.pop("$schema", None)
    schema.pop("$id", None)
    return schema


def _rewrite_schema_refs(node: Any, replacements: dict[str, str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref in replacements:
            node["$ref"] = replacements[ref]
        for value in node.values():
            _rewrite_schema_refs(value, replacements)
    elif isinstance(node, list):
        for value in node:
            _rewrite_schema_refs(value, replacements)


def _component_name(definition_name: str) -> str:
    if not definition_name:
        raise ValueError("OpenAPI schema definition name cannot be empty")
    return definition_name[:1].upper() + definition_name[1:]


def _load_actions_component_schemas() -> dict[str, Any]:
    loaded = {
        "BootstrapPayload": _load_component_schema("bootstrap_output.schema.json"),
        "SceneResponse": _load_component_schema("scene_response.schema.json"),
    }
    components: dict[str, Any] = {}

    for root_name, root_schema in loaded.items():
        definitions = root_schema.pop("$defs", {})
        if definitions is None:
            definitions = {}
        if not isinstance(definitions, dict):
            raise ValueError(f"{root_name}.$defs must be an object")

        ref_replacements = {
            f"#/$defs/{definition_name}": f"#/components/schemas/{_component_name(definition_name)}"
            for definition_name in definitions
        }
        _rewrite_schema_refs(root_schema, ref_replacements)
        components[root_name] = root_schema

        for definition_name, definition in definitions.items():
            component_name = _component_name(definition_name)
            if not isinstance(definition, dict):
                raise ValueError(f"OpenAPI component {component_name} must be an object schema")
            if component_name in components or component_name in loaded:
                raise ValueError(f"Duplicate OpenAPI component schema: {component_name}")
            definition = deepcopy(definition)
            _rewrite_schema_refs(definition, ref_replacements)
            components[component_name] = definition

    return components
''',
)

replace_once(
    "app/novella_openapi_actions.py",
    '''            "schemas": {
                "BootstrapPayload": _load_component_schema(
                    "bootstrap_output.schema.json"
                ),
                "SceneResponse": _load_component_schema(
                    "scene_response.schema.json"
                ),
''',
    '''            "schemas": {
                **_load_actions_component_schemas(),
''',
)

replace_once(
    "tests/test_openapi_actions_contract.py",
    '''    assert "mode" not in preview_request["properties"]



def test_custom_gpt_instructions_fit_editor_limit_and_keep_critical_flow():
''',
    '''    assert "mode" not in preview_request["properties"]



def test_openapi_actions_hoist_json_schema_defs_into_object_components():
    contract = build_openapi_actions("https://example.invalid")
    schemas = contract["components"]["schemas"]

    assert all(isinstance(component, dict) for component in schemas.values())
    assert schemas["DirectorStatusPatch"]["type"] == "object"

    serialized = json.dumps(schemas, ensure_ascii=False)
    assert '"$defs"' not in serialized
    assert "#/$defs/" not in serialized

    director_patches = schemas["SceneResponse"]["properties"]["proposed_updates"]["properties"]["director_bible_patches"]["properties"]
    for field in ("event_updates", "hook_updates", "reveal_updates", "conflict_updates"):
        assert director_patches[field]["items"] == {
            "$ref": "#/components/schemas/DirectorStatusPatch"
        }



def test_custom_gpt_instructions_fit_editor_limit_and_keep_critical_flow():
''',
)
