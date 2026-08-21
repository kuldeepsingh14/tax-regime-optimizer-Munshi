"""Graph B — Multi-Document Reconciliation.

Real users have Form 16 AND AIS AND 26AS, and the numbers disagree. The
employer reports one TDS figure; the department's records show another.
Interest income appears in AIS but never in Form 16.

    align -> detect_conflicts -> classify_conflicts -> merge -> END

Most competing tools take Form 16 alone and silently miss income the user is
legally required to declare. This graph is the differentiator.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, StateGraph

# Tolerance below which a difference is rounding, not disagreement.
ROUNDING_TOLERANCE = Decimal("10")

# Which source wins for which field, most authoritative first.
# 26AS is the department's own record of tax actually credited, so it beats
# the employer's certificate. AIS is the only source for third-party income.
PRECEDENCE: dict[str, tuple[str, ...]] = {
    "tds_deducted": ("26as", "form16", "ais"),
    "gross_salary": ("form16", "ais", "26as"),
    "savings_interest": ("ais", "form16", "26as"),
    "fd_interest": ("ais", "26as", "form16"),
    "dividend_income": ("ais", "26as", "form16"),
}
DEFAULT_PRECEDENCE = ("form16", "26as", "ais")

Resolution = Literal["rounding", "precedence", "user"]


@dataclass(frozen=True)
class Conflict:
    field: str
    values: dict[str, str]          # doc_type -> stringified value
    resolution: Resolution
    chosen: str | None
    chosen_source: str | None
    note: str

    def to_dict(self) -> dict:
        return asdict(self)


class ReconciliationState(TypedDict, total=False):
    documents: dict[str, dict]      # doc_type -> extracted fields
    aligned: dict[str, dict]        # field -> {doc_type: value}
    conflicts: Annotated[list[Conflict], lambda a, b: b]
    merged: dict
    needs_user_confirmation: Annotated[list[str], lambda a, b: b]
    trace: Annotated[list[str], lambda a, b: a + b]


# --------------------------------------------------------------------------
# nodes
# --------------------------------------------------------------------------

def node_align(state: ReconciliationState) -> dict:
    """Invert doc -> fields into field -> {doc: value}.

    Field names already share canonical keys because every extractor emits the
    same vocabulary. Aligning here rather than at extraction keeps extractors
    independent of each other.
    """
    aligned: dict[str, dict] = {}
    for doc_type, fields in state.get("documents", {}).items():
        for field, value in fields.items():
            aligned.setdefault(field, {})[doc_type] = value

    return {
        "aligned": aligned,
        "trace": [
            f"align: {len(state.get('documents', {}))} docs -> {len(aligned)} fields"
        ],
    }


def _differs(values: dict) -> bool:
    distinct = list(values.values())
    if len(distinct) < 2:
        return False

    if all(isinstance(v, Decimal) for v in distinct):
        return max(distinct) - min(distinct) > ROUNDING_TOLERANCE

    return len({str(v).strip().upper() for v in distinct}) > 1


def node_detect_conflicts(state: ReconciliationState) -> dict:
    disputed = [
        field for field, values in state.get("aligned", {}).items() if _differs(values)
    ]
    return {
        "needs_user_confirmation": disputed,
        "trace": [f"detect: {len(disputed)} field(s) disagree"],
    }


def node_classify_conflicts(state: ReconciliationState) -> dict:
    """Decide, per conflict, whether it can be auto-resolved or needs the user."""
    aligned = state.get("aligned", {})
    conflicts: list[Conflict] = []
    unresolved: list[str] = []

    for field in state.get("needs_user_confirmation", []):
        values = aligned[field]
        as_strings = {k: str(v) for k, v in values.items()}

        # Numeric fields with a known authoritative source resolve themselves.
        order = PRECEDENCE.get(field, DEFAULT_PRECEDENCE)
        winner = next((doc for doc in order if doc in values), None)

        if field in PRECEDENCE and winner:
            conflicts.append(
                Conflict(
                    field=field,
                    values=as_strings,
                    resolution="precedence",
                    chosen=str(values[winner]),
                    chosen_source=winner,
                    note=f"{winner} is authoritative for {field}",
                )
            )
            continue

        # No precedence rule: the user decides. We never silently pick.
        unresolved.append(field)
        conflicts.append(
            Conflict(
                field=field,
                values=as_strings,
                resolution="user",
                chosen=None,
                chosen_source=None,
                note="sources disagree and no precedence rule applies",
            )
        )

    return {
        "conflicts": conflicts,
        "needs_user_confirmation": unresolved,
        "trace": [
            f"classify: {len(conflicts) - len(unresolved)} auto-resolved, "
            f"{len(unresolved)} for user"
        ],
    }


def node_merge(state: ReconciliationState) -> dict:
    """Build the merged record.

    Uncontested fields are taken directly. Contested fields take the
    precedence winner where one exists, and are left absent where the user
    must decide — absent, not guessed.
    """
    aligned = state.get("aligned", {})
    resolutions = {
        c.field: c for c in state.get("conflicts", []) if c.resolution == "precedence"
    }
    pending = set(state.get("needs_user_confirmation", []))

    merged: dict = {}
    for field, values in aligned.items():
        if field in pending:
            continue
        if field in resolutions:
            source = resolutions[field].chosen_source
            merged[field] = values[source]
            continue
        order = PRECEDENCE.get(field, DEFAULT_PRECEDENCE)
        winner = next((doc for doc in order if doc in values), None)
        if winner:
            merged[field] = values[winner]

    return {"merged": merged, "trace": [f"merge: {len(merged)} field(s) resolved"]}


# --------------------------------------------------------------------------
# graph
# --------------------------------------------------------------------------

def build_reconciliation_graph():
    g = StateGraph(ReconciliationState)

    g.add_node("align", node_align)
    g.add_node("detect_conflicts", node_detect_conflicts)
    g.add_node("classify_conflicts", node_classify_conflicts)
    g.add_node("merge", node_merge)

    g.set_entry_point("align")
    g.add_edge("align", "detect_conflicts")
    g.add_edge("detect_conflicts", "classify_conflicts")
    g.add_edge("classify_conflicts", "merge")
    g.add_edge("merge", END)

    return g.compile()


def run_reconciliation(documents: dict[str, dict]) -> ReconciliationState:
    graph = build_reconciliation_graph()
    return graph.invoke(
        {
            "documents": documents,
            "aligned": {},
            "conflicts": [],
            "merged": {},
            "needs_user_confirmation": [],
            "trace": [],
        }
    )
