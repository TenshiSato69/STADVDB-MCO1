import argparse
import importlib
import importlib.util
import json
import os
import re
import statistics
import time
from datetime import datetime
import pandas as pd
from sqlalchemy import text

# Benchmarks the OLAP queries of each Streamlit app module
# Usage: python benchmark.py [module ...] [--runs N]

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
DEFAULT_MODULES = ["app_baseline", "app_optimized"]
COST_PATTERN = r"cost=(?:\S+?\.\.)?(\d+(?:\.\d+)?(?:e[+-]?\d+)?)"
ACTUAL_TIME_PATTERN = r"actual time=[\d.]+\.\.([\d.]+)"


def get_first_number(pattern, plan_text):
    match = re.search(pattern, plan_text)
    return float(match.group(1)) if match else None


def capture_queries(module, engine):
    captured_queries = []
    current_query_name = None

    def record_query(eng, query, params=None):
        if current_query_name:
            captured_queries.append((current_query_name, query, params))
        return pd.DataFrame()

    original_get_data = module.get_data

    # Fetch dynamic target country for drill-down benchmark
    target_country = "United States"
    if hasattr(module, "get_available_countries"):
        try:
            countries_df = module.get_available_countries(engine)
            if isinstance(countries_df, pd.DataFrame) and not countries_df.empty and "country" in countries_df.columns:
                target_country = countries_df["country"].iloc[0]
        except Exception:
            pass

    module.get_data = record_query
    try:
        builders = [
            ("available_months", lambda: module.get_available_months(engine)),
            ("available_categories", lambda: module.get_available_categories(engine)),
            ("rollup", lambda: module.get_rollup_data(engine)),
        ]

        # Dynamically append drilldown if implemented in the app module
        if hasattr(module, "get_drilldown_data"):
            builders.append((
                "drilldown",
                lambda: module.get_drilldown_data(engine, selected_country=target_country)
            ))

        builders.append(("pivot", lambda: module.get_pivot_data(engine)))

        for q_name, builder in builders:
            current_query_name = q_name
            try:
                builder()
            except Exception as err:
                print(f"Warning: Could not capture query '{q_name}': {err}", flush=True)

    finally:
        module.get_data = original_get_data

    return captured_queries


def benchmark_query(engine, query, params, runs):
    params = params or {}

    with engine.connect() as connection:
        explain_tree = connection.execute(
            text("EXPLAIN FORMAT=TREE " + query), params
        ).scalar()
        explain_analyze = connection.execute(
            text("EXPLAIN ANALYZE " + query), params
        ).scalar()

        run_times = []
        for run in range(runs):
            start = time.perf_counter()
            connection.execute(text(query), params).fetchall()
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            run_times.append(elapsed_ms)
            print(f"    timed run {run + 1}/{runs}: {elapsed_ms} ms", flush=True)

    return {
        "sql": query,
        "params": params,
        "estimated_cost": get_first_number(COST_PATTERN, explain_tree),
        "mysql_ms": get_first_number(ACTUAL_TIME_PATTERN, explain_analyze),
        "wall_ms_runs": run_times,
        "wall_ms_median": round(statistics.median(run_times), 1),
        "explain_tree": explain_tree,
        "explain_analyze": explain_analyze,
    }


def benchmark_module(module_name, runs):
    module = importlib.import_module(module_name)
    engine = module.init_connection()
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")

    captured_queries = capture_queries(module, engine)
    print(f"  captured {len(captured_queries)} queries", flush=True)

    results = {}
    for query_name, query, params in captured_queries:
        print(f"benchmarking {query_name} ...", flush=True)
        results[query_name] = benchmark_query(engine, query, params, runs)

    with engine.connect() as connection:
        mysql_version = connection.execute(text("SELECT VERSION()")).scalar()

    results = {
        "_meta": {
            "runs": runs,
            "timestamp": started_at,
            "mysql_version": mysql_version,
        },
        **results,
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)
    results_path = os.path.join(RESULTS_DIR, f"benchmark_{module_name}.json")
    with open(results_path, "w", encoding="utf-8") as results_file:
        json.dump(results, results_file, indent=2, default=str)

    for query_name, _, _ in captured_queries:
        if query_name in results:
            result = results[query_name]
            print(
                f"  {query_name}: cost={result['estimated_cost']} "
                f"mysql={result['mysql_ms']}ms "
                f"wall_median={result['wall_ms_median']}ms",
                flush=True,
            )
    print(f"  wrote {results_path}", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark OLAP query builders per module.",
    )
    parser.add_argument("modules", nargs="*", default=DEFAULT_MODULES)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    if args.runs < 1:
        parser.error("--runs must be >= 1")

    for module_name in args.modules:
        if importlib.util.find_spec(module_name) is None:
            print(f"skipping {module_name}: module not found", flush=True)
            continue
        print(f"== {module_name} (runs={args.runs}) ==", flush=True)
        benchmark_module(module_name, args.runs)


if __name__ == "__main__":
    main()