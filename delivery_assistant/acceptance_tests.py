"""Trusted, explicitly invoked acceptance tests; never supplied by the model."""
import csv
from collections import defaultdict
from decimal import Decimal
import json
import os
from pathlib import Path

import duckdb
import yaml


def _inputs():
    workspace = Path(os.environ["DADS_VALIDATION_WORKSPACE"])
    policy = json.loads((workspace / "acceptance_policy.json").read_text(encoding="utf-8"))
    with (workspace / "seeds" / "orders.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return workspace, policy, rows


def test_daily_revenue_matches_independent_csv_oracle():
    workspace, policy, rows = _inputs()
    expected = defaultdict(lambda: [Decimal("0"), 0])
    for row in rows:
        if row["status"] not in policy["excluded_statuses"]:
            expected[row["order_date"]][0] += Decimal(row["amount"])
            expected[row["order_date"]][1] += 1
    with duckdb.connect(str(workspace / "validation.duckdb"), read_only=True,
                        config={"enable_external_access": "false"}) as connection:
        actual = connection.execute("SELECT revenue_date, revenue, order_count FROM fct_revenue ORDER BY revenue_date").fetchall()
    actual_map = {str(date): [Decimal(str(revenue)), count] for date, revenue, count in actual}
    assert actual_map == dict(expected)


def test_dashboard_uses_same_metric_policy():
    workspace, policy, _ = _inputs()
    dashboard = yaml.safe_load((workspace / "bi" / "revenue_dashboard.yml").read_text(encoding="utf-8"))["dashboard"]
    assert dashboard["source_model"] == "fct_revenue"
    assert dashboard["metric"] == "revenue"
    assert set(dashboard["excluded_statuses"]) == set(policy["excluded_statuses"])


def test_documentation_states_reviewed_status_policy():
    workspace, policy, _ = _inputs()
    content = (workspace / "docs" / "revenue.md").read_text(encoding="utf-8")
    label = ", ".join(sorted(policy["excluded_statuses"])) or "none"
    assert f"Excluded statuses: {label}" in content
