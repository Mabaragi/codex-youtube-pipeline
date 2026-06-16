from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATE_ERD_PATH = REPO_ROOT / "scripts" / "generate_erd.py"


def _load_generate_erd() -> ModuleType:
    spec = importlib.util.spec_from_file_location("generate_erd", GENERATE_ERD_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load generate_erd.py.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_generate_erd = _load_generate_erd()
_build_graph = _generate_erd.__dict__["_build_graph"]
_foreign_key_relations = _generate_erd.__dict__["_foreign_key_relations"]


def test_foreign_keys_are_rendered_as_layout_nodes() -> None:
    metadata = MetaData()
    parent = Table("parents", metadata, Column("id", Integer, primary_key=True))
    child = Table(
        "children",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("parent_id", ForeignKey(parent.c.id), nullable=False),
    )

    relations = _foreign_key_relations([parent, child])
    graph = _build_graph([parent, child])

    assert relations == [
        _foreign_key_relations([parent, child])[0],
    ]
    assert relations[0].node_name == "rel_parents_id_children_parent_id"
    assert relations[0].label == "id -> parent_id"
    assert "rel_parents_id_children_parent_id" in graph.source
    assert "xlabel=" not in graph.source
    assert "splines=polyline" in graph.source
