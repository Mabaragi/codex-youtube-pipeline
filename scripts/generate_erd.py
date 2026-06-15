from __future__ import annotations

import sys
from html import escape
from importlib import import_module
from pathlib import Path

from graphviz import Digraph
from sqlalchemy import Column, Table

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
OUTPUT_PATH = REPO_ROOT / "docs" / "erd.svg"


def main() -> None:
    sys.path.insert(0, str(SRC_PATH))
    import_module("codex_sdk_cli.infra.database.models")
    from codex_sdk_cli.infra.database.base import Base

    graph = _build_graph(list(Base.metadata.sorted_tables))
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    graph.render(
        filename=OUTPUT_PATH.stem,
        directory=str(OUTPUT_PATH.parent),
        format="svg",
        cleanup=True,
    )


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

    for table in tables:
        for column in table.columns:
            for foreign_key in column.foreign_keys:
                graph.edge(
                    f"{foreign_key.column.table.name}:{foreign_key.column.name}",
                    f"{table.name}:{column.name}",
                    xlabel=f"{foreign_key.column.name} -> {column.name}",
                    arrowhead="crow",
                    arrowtail="none",
                    dir="forward",
                )

    return graph


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
        "ranksep": "1.15",
        "splines": "ortho",
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
        if getattr(constraint, "unique", False)
        for column in constraint.columns
    }


if __name__ == "__main__":
    main()
