"""Bounded local repository retrieval, patch preparation and real validation.

The executable patch grammar deliberately supports one revenue status policy.
The model cannot introduce arbitrary SQL, Jinja, dbt hooks or Python code.
"""
from collections import Counter
import csv
from decimal import Decimal
import difflib
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

import yaml

from .models import CheckResult, Evidence, FileChange, ImpactPlan, Proposal, Ticket, ValidationReport

ALLOWED_CHANGE_PATHS = (
    "models/marts/fct_revenue.sql", "tests/revenue_policy.sql",
    "docs/revenue.md", "bi/revenue_dashboard.yml",
)
SOURCE_PATHS = (
    "README.md", "dbt_project.yml", "profiles.yml", "seeds/orders.csv",
    "models/staging/stg_orders.sql", "models/schema.yml",
    *ALLOWED_CHANGE_PATHS, "metadata/dependencies.json",
)
STATUSES = {"completed", "canceled", "refunded", "pending"}
SECRET_LINE = re.compile(r"(?i)(?:api[_ -]?key|password|access[_ -]?token|secret)\s*[:=]|sk-[A-Za-z0-9_-]{12,}")
STAGING_SQL = """SELECT
    order_id,
    CAST(order_date AS DATE) AS order_date,
    LOWER(status) AS status,
    CAST(amount AS DECIMAL(18, 2)) AS amount
FROM {{ ref('orders') }}
"""
PROJECT_YAML = """name: delivery_demo
version: '1.0.0'
config-version: 2
profile: delivery_demo
model-paths: [models]
seed-paths: [seeds]
test-paths: [tests]
models:
  delivery_demo:
    +materialized: table
seeds:
  delivery_demo:
    orders:
      +column_types:
        order_id: integer
        order_date: date
        status: varchar
        amount: decimal(18,2)
"""
PROFILES_YAML = """delivery_demo:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: validation.duckdb
      threads: 1
      settings:
        enable_external_access: false
        autoinstall_known_extensions: false
        autoload_known_extensions: false
"""
SCHEMA_YAML = """version: 2
models:
  - name: stg_orders
    columns:
      - name: order_id
        data_tests: [not_null, unique]
  - name: fct_revenue
    columns:
      - name: revenue_date
        data_tests: [not_null, unique]
      - name: revenue
        data_tests: [not_null]
      - name: order_count
        data_tests: [not_null]
"""


def _normalized_sql(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().rstrip(";")).lower()


def _tokens(value: str) -> Counter:
    return Counter(re.findall(r"[a-z][a-z0-9_]+", value.lower()))


def _safe_text(value: str) -> str:
    return "\n".join("[REDACTED sensitive line]" if SECRET_LINE.search(line) else line for line in value.splitlines())


class RepoTools:
    ALLOWED_CHANGE_PATHS = ALLOWED_CHANGE_PATHS

    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root).resolve()
        if not self.repo_root.is_dir():
            raise ValueError("Sample repository folder was not found.")

    def _read(self, relative: str) -> str:
        if relative not in SOURCE_PATHS:
            raise ValueError("Repository read denied by the file allowlist.")
        file_path = self.repo_root / relative
        if file_path.is_symlink() or any(parent.is_symlink() for parent in file_path.parents if parent != self.repo_root.parent):
            raise ValueError("Symbolic links are not supported in the sample repository.")
        if not file_path.resolve().is_relative_to(self.repo_root):
            raise ValueError("Repository path escapes the sample repository.")
        if not file_path.is_file() or file_path.stat().st_size > 100_000:
            raise ValueError("Repository file is missing or exceeds the bounded read size.")
        return file_path.read_text(encoding="utf-8-sig")

    def snapshot_hash(self) -> str:
        digest = hashlib.sha256()
        for relative in SOURCE_PATHS:
            digest.update(relative.encode())
            digest.update(self._read(relative).encode())
        return digest.hexdigest()

    def retrieve(self, query: str, limit: int = 8) -> list[Evidence]:
        """Rank allowlisted files using a local TF-IDF cosine vector index."""
        limit = max(1, min(int(limit), 10))
        documents = {path: _safe_text(self._read(path)) for path in SOURCE_PATHS if path not in {"profiles.yml", "dbt_project.yml"}}
        counts = {path: _tokens(path + " " + content) for path, content in documents.items()}
        query_counts = _tokens(query)
        document_frequency = Counter(token for tokens in counts.values() for token in tokens)
        idf = {token: math.log((1 + len(counts)) / (1 + frequency)) + 1 for token, frequency in document_frequency.items()}
        query_vector = {token: frequency * idf.get(token, 1) for token, frequency in query_counts.items()}
        query_norm = math.sqrt(sum(weight * weight for weight in query_vector.values())) or 1
        scores = {}
        for path, tokens in counts.items():
            vector = {token: frequency * idf[token] for token, frequency in tokens.items()}
            norm = math.sqrt(sum(weight * weight for weight in vector.values())) or 1
            scores[path] = sum(weight * query_vector.get(token, 0) for token, weight in vector.items()) / (norm * query_norm)
        ranked = sorted(documents, key=lambda path: (-scores[path], path))
        # Resolve known downstream dependencies, including low-lexical-overlap BI assets.
        dependency_paths = list(ALLOWED_CHANGE_PATHS) + ["metadata/dependencies.json"] if "revenue" in query.lower() else []
        selected = list(dict.fromkeys(dependency_paths + ranked))[:limit]
        return [Evidence(path=path, content=documents[path][:12_000], score=round(scores[path], 5),
                         reason="Revenue dependency graph and local TF-IDF retrieval" if path in dependency_paths else "Local TF-IDF cosine retrieval") for path in selected]

    def canonical_templates(self, ticket: Ticket) -> dict[str, str]:
        statuses = sorted(set(ticket.excluded_statuses))
        if any(status not in STATUSES for status in statuses):
            raise ValueError("Unsupported order status.")
        predicate = "status NOT IN (" + ", ".join("'" + status + "'" for status in statuses) + ")" if statuses else "1 = 1"
        model = """SELECT
    order_date AS revenue_date,
    SUM(amount) AS revenue,
    COUNT(*) AS order_count
FROM {{ ref('stg_orders') }}
WHERE """ + predicate + "\nGROUP BY order_date\n"
        test = """SELECT 1 AS failed
WHERE
    (SELECT COALESCE(SUM(revenue), 0) FROM {{ ref('fct_revenue') }})
    <>
    (SELECT COALESCE(SUM(amount), 0) FROM {{ ref('stg_orders') }} WHERE """ + predicate + ")\n"
        label = ", ".join(statuses) or "none"
        doc = f"# Revenue metric\n\nExcluded statuses: {label}\n\nRevenue is the sum of order amounts by order date after excluding the reviewed statuses. The SQL model, policy test and dashboard definition use the same policy. Human approval is required before exporting the reviewed patch.\n"
        dashboard = yaml.safe_dump({"dashboard": {"id": "revenue_overview", "title": "Revenue overview", "source_model": "fct_revenue", "metric": "revenue", "group_by": "revenue_date", "excluded_statuses": statuses, "chart": "daily_revenue"}}, sort_keys=False)
        return dict(zip(ALLOWED_CHANGE_PATHS, [model, test, doc, dashboard]))

    def sample_proposal(self, ticket: Ticket, evidence: list[Evidence]) -> Proposal:
        templates = self.canonical_templates(ticket)
        reasons = ["Apply the requested status exclusion to the daily revenue aggregation.",
                   "Keep a dbt policy regression test aligned with the requested revenue definition.",
                   "Document the reviewed metric policy for analysts.",
                   "Version the same policy in the existing BI dashboard definition."]
        label = ", ".join(sorted(set(ticket.excluded_statuses))) or "none"
        return Proposal(plan=ImpactPlan(summary=f"Exclude {label} from daily revenue and align downstream assets.",
            affected_files=list(ALLOWED_CHANGE_PATHS),
            steps=["Confirm the structured ticket and its acceptance criteria.", "Inspect cited repository evidence and dependency metadata.", "Prepare SQL, test, documentation and dashboard replacements.", "Validate in an isolated workspace and request human approval."],
            risks=["The metric definition changes downstream reported revenue.", "Passing synthetic tests does not establish production correctness."],
            evidence_paths=[item.path for item in evidence]),
            changes=[FileChange(path=path, content=templates[path], reason=reason) for path, reason in zip(ALLOWED_CHANGE_PATHS, reasons)])

    def diff(self, changes: list[FileChange]) -> str:
        chunks = []
        for change in changes:
            if change.path not in ALLOWED_CHANGE_PATHS:
                raise ValueError("Patch path denied by the file allowlist.")
            chunks.extend(difflib.unified_diff(self._read(change.path).splitlines(keepends=True), change.content.splitlines(keepends=True), fromfile="a/"+change.path, tofile="b/"+change.path))
        return "".join(chunks)

    def validate(self, ticket: Ticket, changes: list[FileChange], run_dir: Path) -> ValidationReport:
        checks = []
        commands = []
        baseline = expected = proposed = None

        def check(name, passed, details):
            checks.append(CheckResult(name=name, passed=bool(passed), details=str(details)[:6000]))

        try:
            if not ticket.supported or ticket.metric != "revenue" or ticket.clarification_questions:
                raise ValueError("Only a clarified, supported revenue ticket can enter validation.")
            paths = [change.path for change in changes]
            if len(paths) != len(set(paths)) or set(paths) != set(ALLOWED_CHANGE_PATHS):
                raise ValueError("Exactly the four allowlisted patch files are required; traversal, extra and duplicate paths are denied.")
            templates = self.canonical_templates(ticket)
            by_path = {change.path: change.content for change in changes}
            for path, content in by_path.items():
                if len(content) > 30_000 or "\x00" in content or SECRET_LINE.search(content):
                    raise ValueError("Patch content is oversized, invalid or appears to contain a secret.")
                if path.endswith(".sql") and _normalized_sql(content) != _normalized_sql(templates[path]):
                    raise ValueError("SQL patch is outside the supported revenue-policy grammar. Arbitrary SQL, Jinja, hooks and tool calls are denied.")
            if yaml.safe_load(by_path["bi/revenue_dashboard.yml"]) != yaml.safe_load(templates["bi/revenue_dashboard.yml"]):
                raise ValueError("The dashboard definition must use the supported schema and ticket policy.")
            label = ", ".join(sorted(set(ticket.excluded_statuses))) or "none"
            if f"Excluded statuses: {label}" not in by_path["docs/revenue.md"]:
                raise ValueError("Documentation must state the same excluded-status policy as the ticket.")
            check("Patch safety and scope", True, "Four allowlisted files; bounded SQL/test grammar; matching BI and documentation policy.")
            rows = list(csv.DictReader(io.StringIO(self._read("seeds/orders.csv"))))
            if len(rows) > 1000 or not rows:
                raise ValueError("Synthetic seed data must contain between 1 and 1000 orders.")
            for row in rows:
                if row["status"] not in STATUSES or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["order_date"]) or not row["order_id"].isdigit():
                    raise ValueError("Seed data is outside the synthetic order schema.")
                if not re.fullmatch(r"\d+(?:\.\d{1,2})?", row["amount"]):
                    raise ValueError("Synthetic amounts must be non-negative decimal numbers.")
            baseline = float(sum((Decimal(row["amount"]) for row in rows), Decimal(0)))
            expected = float(sum((Decimal(row["amount"]) for row in rows if row["status"] not in ticket.excluded_statuses), Decimal(0)))
            workspace = Path(run_dir).resolve() / "workspace"
            if workspace.is_relative_to(self.repo_root) or Path(run_dir).is_symlink():
                raise ValueError("Validation workspace must be separate from the source repository.")
            workspace.mkdir(parents=True, exist_ok=False)
            # Copy only known data/docs; executable project config is supplied by trusted code below.
            for path in SOURCE_PATHS:
                target = workspace / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(self._read(path), encoding="utf-8")
            for path, value in {"dbt_project.yml": PROJECT_YAML, "profiles.yml": PROFILES_YAML,
                                "models/staging/stg_orders.sql": STAGING_SQL, "models/schema.yml": SCHEMA_YAML}.items():
                (workspace / path).write_text(value, encoding="utf-8")
            for path, content in by_path.items():
                (workspace / path).write_text(content, encoding="utf-8")
            (workspace / "acceptance_policy.json").write_text(json.dumps({"excluded_statuses": ticket.excluded_statuses}), encoding="utf-8")
            (workspace / "pytest.ini").write_text("[pytest]\naddopts =\n", encoding="utf-8")
            check("Isolated workspace", True, "Proposed changes applied only to the per-run workspace; source repository remains read-only.")
            # dbt seed uses a file-reading SQL function. Instead, trusted code parses the
            # bounded CSV and inserts parameters before any generated SQL is executed.
            import duckdb
            with duckdb.connect(str(workspace / "validation.duckdb"), config={"enable_external_access": "false"}) as connection:
                connection.execute("CREATE TABLE orders (order_id INTEGER, order_date DATE, status VARCHAR, amount DECIMAL(18,2))")
                connection.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)",
                    [(int(row["order_id"]), row["order_date"], row["status"], Decimal(row["amount"])) for row in rows])
            check("Trusted synthetic seed ingestion", True, "Python CSV parsing and parameterized inserts load the local synthetic seed; DuckDB external access remains disabled.")
            environment = {key:value for key,value in os.environ.items() if not re.search(r"(?i)(key|token|secret|password|credential|proxy)", key)}
            environment.update({"DBT_SEND_ANONYMOUS_USAGE_STATS": "false", "DBT_USE_COLORS": "false", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "DADS_VALIDATION_WORKSPACE": str(workspace)})
            dbt_executable = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")
            if not dbt_executable.is_file():
                raise ValueError("dbt is not installed in the active Python environment. Install requirements.txt and retry.")
            args = [str(dbt_executable), "build", "--exclude", "resource_type:seed", "--project-dir", str(workspace), "--profiles-dir", str(workspace), "--target", "dev", "--no-use-colors", "--no-partial-parse"]
            commands.append("dbt build --exclude resource_type:seed --project-dir <workspace> --profiles-dir <workspace> --target dev --no-use-colors --no-partial-parse")
            result = subprocess.run(args,cwd=workspace,env=environment,capture_output=True,text=True,timeout=90,encoding="utf-8",errors="replace")
            (workspace / "dbt_validation.log").write_text(_safe_text(result.stdout+result.stderr),encoding="utf-8")
            check("dbt build and data tests", result.returncode == 0, _safe_text((result.stdout+result.stderr)[-5500:]))
            if result.returncode == 0:
                import duckdb
                with duckdb.connect(str(workspace / "validation.duckdb"),read_only=True,config={"enable_external_access":"false"}) as connection:
                    total_row = connection.execute("SELECT COALESCE(SUM(revenue), 0) FROM fct_revenue").fetchone()
                    if total_row is None:
                        raise ValueError("The revenue query did not return a total.")
                    proposed = float(total_row[0])
                check("Independent revenue total", abs(proposed-expected)<0.005, f"Baseline={baseline:.2f}; proposed={proposed:.2f}; CSV oracle={expected:.2f}.")
                test_file = Path(__file__).with_name("acceptance_tests.py")
                args = [sys.executable,"-m","pytest",str(test_file),"-q","--noconftest","-c",str(workspace/"pytest.ini")]
                commands.append("python -m pytest <trusted acceptance_tests.py> -q --noconftest -c <workspace>/pytest.ini")
                result = subprocess.run(args,cwd=workspace,env=environment,capture_output=True,text=True,timeout=45,encoding="utf-8",errors="replace")
                (workspace/"acceptance_validation.log").write_text(_safe_text(result.stdout+result.stderr),encoding="utf-8")
                check("Trusted pytest acceptance tests",result.returncode==0,_safe_text((result.stdout+result.stderr)[-5500:]))
        except subprocess.TimeoutExpired:
            check("Validation timeout",False,"A predefined validation command exceeded its time limit; approval is blocked.")
        except Exception as exc:
            check("Validation blocked",False,_safe_text(str(exc)))
        return ValidationReport(passed=bool(checks) and all(item.passed for item in checks),checks=checks,
                                baseline_total=baseline,proposed_total=proposed,expected_total=expected,executed_commands=commands)
