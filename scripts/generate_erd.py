from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from html import escape
from importlib import import_module
from pathlib import Path

from graphviz import Digraph
from sqlalchemy import Column, Table, UniqueConstraint

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
OUTPUT_PATH = REPO_ROOT / "docs" / "erd.svg"
SCHEMA_HASH_PATH = REPO_ROOT / "docs" / "erd.schema.sha256"


def main() -> None:
    args = _parse_args()
    sys.path.insert(0, str(SRC_PATH))
    import_module("codex_sdk_cli.infra.database.models")
    from codex_sdk_cli.infra.database.base import Base

    tables = list(Base.metadata.sorted_tables)
    schema_hash = _schema_hash(tables)

    if args.check:
        _check_schema_hash(schema_hash)
        return

    graph = _build_graph(tables)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    graph.render(
        filename=OUTPUT_PATH.stem,
        directory=str(OUTPUT_PATH.parent),
        format="svg",
        cleanup=True,
    )
    _normalize_svg_newlines()
    _write_schema_hash(schema_hash)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate or verify the database ERD SVG.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the committed ERD schema hash without rewriting the SVG.",
    )
    return parser.parse_args()


def _build_graph(tables: list[Table]) -> Digraph:
    graph = Digraph("codex_sdk_cli_erd", graph_attr=_graph_attrs())
    graph.attr("node", shape="plain", margin="0", fontname="Inter, Arial, sans-serif")
    graph.attr(
        "edge",
        color="#557086",
        fontcolor="#506070",
        fontname="Inter, Arial, sans-serif",
        fontsize="10",
        penwidth="1.6",
        arrowsize="0.8",
    )

    for table in tables:
        graph.node(table.name, label=_table_label(table))

    for relation in _foreign_key_relations(tables):
        graph.node(
            relation.node_name,
            label=relation.label,
            shape="box",
            style="rounded,filled",
            fillcolor="#FFFFFF",
            color="#9FB2C1",
            fontcolor="#425466",
            fontsize="10",
            margin="0.06,0.04",
        )
        graph.edge(
            relation.parent_column_ref,
            relation.node_name,
            arrowhead="none",
            dir="forward",
        )
        graph.edge(
            relation.node_name,
            relation.child_column_ref,
            arrowhead="crow",
            arrowtail="none",
            dir="forward",
        )

    return graph


@dataclass(frozen=True)
class _ForeignKeyRelation:
    node_name: str
    label: str
    parent_column_ref: str
    child_column_ref: str


def _foreign_key_relations(tables: list[Table]) -> list[_ForeignKeyRelation]:
    relations: list[_ForeignKeyRelation] = []
    for table in tables:
        for column in table.columns:
            for foreign_key in column.foreign_keys:
                parent_column = foreign_key.column
                relations.append(
                    _ForeignKeyRelation(
                        node_name=(
                            f"rel_{parent_column.table.name}_{parent_column.name}_"
                            f"{table.name}_{column.name}"
                        ),
                        label=f"{parent_column.name} -> {column.name}",
                        parent_column_ref=f"{parent_column.table.name}:{parent_column.name}",
                        child_column_ref=f"{table.name}:{column.name}",
                    )
                )
    return relations


def _graph_attrs() -> dict[str, str]:
    return {
        "bgcolor": "transparent",
        "concentrate": "false",
        "dpi": "120",
        "fontname": "Inter, Arial, sans-serif",
        "labelloc": "t",
        "margin": "0.16",
        "nodesep": "0.9",
        "outputorder": "edgesfirst",
        "pad": "0.25",
        "rankdir": "LR",
        "ranksep": "1.35",
        "splines": "polyline",
    }


def _table_label(table: Table) -> str:
    rows = [_header_row(table.name)]
    for column in table.columns:
        rows.append(_column_row(table, column))

    return f"""<
<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="8" COLOR="#9FB2C1">
{''.join(rows)}
</TABLE>
>"""


def _header_row(table_name: str) -> str:
    return f"""<TR>
<TD PORT="table" BGCOLOR="#17324D" COLOR="#17324D" COLSPAN="4">
<FONT COLOR="#FFFFFF" POINT-SIZE="17"><B>{escape(table_name)}</B></FONT>
</TD>
</TR>"""


def _column_row(table: Table, column: Column) -> str:
    background = "#F8FBFC" if column.primary_key else "#FFFFFF"
    column_name = escape(column.name)
    column_type = escape(_column_type(column))
    marker = escape(_column_marker(table, column)) or "&#160;"
    nullability = "NOT NULL" if not column.nullable or column.primary_key else "NULL"
    null_color = "#8A4B24" if nullability == "NOT NULL" else "#6B7280"

    return f"""<TR>
<TD PORT="{column_name}" BGCOLOR="{background}" ALIGN="LEFT">
<FONT COLOR="#1E2A35"><B>{column_name}</B></FONT>
</TD>
<TD BGCOLOR="{background}" ALIGN="LEFT"><FONT COLOR="#4E6274">{column_type}</FONT></TD>
<TD BGCOLOR="{background}" ALIGN="CENTER"><FONT COLOR="#2D6F67"><B>{marker}</B></FONT></TD>
<TD BGCOLOR="{background}" ALIGN="CENTER"><FONT COLOR="{null_color}">{nullability}</FONT></TD>
</TR>"""


def _column_marker(table: Table, column: Column) -> str:
    markers: list[str] = []
    if column.primary_key:
        markers.append("PK")
    if column.foreign_keys:
        markers.append("FK")
    if column.unique or column.name in _unique_column_names(table):
        markers.append("UQ")
    if column.index or column.name in _index_column_names(table):
        markers.append("IX")
    return " ".join(markers)


def _column_type(column: Column) -> str:
    return str(column.type).replace("DATETIME", "DateTime")


def _schema_hash(tables: list[Table]) -> str:
    payload = [
        {
            "name": table.name,
            "columns": [
                {
                    "name": column.name,
                    "type": _column_type(column),
                    "nullable": bool(column.nullable),
                    "primary_key": column.primary_key,
                    "unique": column.unique or column.name in _unique_column_names(table),
                    "index": column.index or column.name in _index_column_names(table),
                    "foreign_keys": sorted(
                        f"{foreign_key.column.table.name}.{foreign_key.column.name}"
                        for foreign_key in column.foreign_keys
                    ),
                }
                for column in table.columns
            ],
        }
        for table in tables
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_schema_hash(schema_hash: str) -> None:
    SCHEMA_HASH_PATH.write_text(f"{schema_hash}\n", encoding="utf-8", newline="\n")


def _normalize_svg_newlines() -> None:
    svg = OUTPUT_PATH.read_text(encoding="utf-8")
    OUTPUT_PATH.write_text(svg, encoding="utf-8", newline="\n")


def _check_schema_hash(schema_hash: str) -> None:
    if not SCHEMA_HASH_PATH.is_file():
        raise SystemExit(
            "docs/erd.schema.sha256 is missing. Run `uv run python scripts/generate_erd.py`."
        )
    if SCHEMA_HASH_PATH.read_text(encoding="utf-8").strip() != schema_hash:
        raise SystemExit(
            "docs/erd.schema.sha256 is stale. Run `uv run python scripts/generate_erd.py`."
        )


def _index_column_names(table: Table) -> set[str]:
    return {
        column.name
        for index in table.indexes
        for column in index.columns
    }


def _unique_column_names(table: Table) -> set[str]:
    return {
        column.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
        for column in constraint.columns
    }


if __name__ == "__main__":
    main()
