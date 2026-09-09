"""Benchmark the promoted offline SIF + LSR application path."""
from __future__ import annotations

import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import joblib
import numpy as np
import psutil


PROJECT = Path(__file__).resolve().parents[4]
BACKEND = PROJECT / "01-app" / "backend"
REPORT = PROJECT / "03-training" / "ml" / "sif_v0_1" / "reports" / "domain_adaptation_v0_2" / "runtime_benchmark.json"
ARTIFACT_ROOT = PROJECT / "03-training" / "ml" / "sif_v0_1" / "artifacts"

SHORT = "Routine housekeeping removed paper from an office floor with no equipment exposure."
MEDIUM = "A hopper being lifted by a forklift fell on the employee while the employee stood beside the load, causing a back injury."
LONG = " ".join([
    "During planned maintenance, a technician prepared to disconnect a pressurized hose from a process vessel.",
    "The permit was available, but residual pressure remained and isolation was not verified at the flange.",
    "When the connection loosened, the hose whipped into the release path and struck a nearby worker.",
    "The crew stopped work, isolated the equipment, and requested medical assessment.",
] * 8)
SAMPLES = [SHORT, MEDIUM, LONG]


def stats(values: list[float]) -> dict[str, float]:
    return {"median_ms": round(statistics.median(values), 4), "p95_ms": round(float(np.percentile(values, 95)), 4), "min_ms": round(min(values), 4), "max_ms": round(max(values), 4)}


def main() -> None:
    process = psutil.Process()
    rss_before = process.memory_info().rss
    sys.path.insert(0, str(BACKEND))
    os.environ.setdefault("SIF_TEST_AUTH_BYPASS", "1")
    os.environ.setdefault("SIF_ENVIRONMENT", "test")
    temporary = Path(tempfile.gettempdir()) / f"sif_domain_benchmark_{os.getpid()}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{temporary.as_posix()}"

    cold: list[float] = []
    cold_code = (
        "import sys,time;sys.path.insert(0,r'" + str(BACKEND) + "');"
        "s=time.perf_counter();from app.services.domain_model import get_domain_model;"
        "get_domain_model().load();print((time.perf_counter()-s)*1000)"
    )
    for _ in range(5):
        result = subprocess.run([sys.executable, "-c", cold_code], capture_output=True, text=True, check=True)
        cold.append(float(result.stdout.strip().splitlines()[-1]))

    from app.services.domain_model import get_domain_model
    from app.services.retrieval import get_retrieval_service

    service = get_domain_model().load()
    retrieval = get_retrieval_service()
    for text in SAMPLES:
        service.classifier.screen(text); service.map_rules(text); retrieval.reference_evidence(text)

    sif_times: list[float] = []
    lsr_times: list[float] = []
    preprocessing_times: list[float] = []
    normalization_times: list[float] = []
    evidence_times: list[float] = []
    retrieval_times: list[float] = []
    for index in range(120):
        text = SAMPLES[index % len(SAMPLES)]
        start = time.perf_counter(); " ".join(text.split()); normalization_times.append((time.perf_counter() - start) * 1000)
        start = time.perf_counter(); service.classifier.screen(text); sif_times.append((time.perf_counter() - start) * 1000)
        start = time.perf_counter(); mapping = service.map_rules(text); lsr_times.append((time.perf_counter() - start) * 1000)
        preprocessing_times.append(mapping["timings_ms"]["preprocessing_and_scoring"])
        evidence_times.append(mapping["timings_ms"]["evidence_and_templates"])
        start = time.perf_counter(); retrieval.reference_evidence(text); retrieval_times.append((time.perf_counter() - start) * 1000)

    from fastapi.testclient import TestClient
    from app.main import app

    api_times: list[float] = []
    cache_times: list[float] = []
    with TestClient(app) as client:
        for index in range(60):
            payload = {"narrative": f"{SAMPLES[index % 3]} Benchmark uncached request {index}.", "site": f"Benchmark-{index}", "report_type": "Near Miss"}
            start = time.perf_counter(); response = client.post("/analyze", json=payload); api_times.append((time.perf_counter() - start) * 1000)
            response.raise_for_status()
        cached_payload = {"narrative": "Cached benchmark narrative with a pressurized hose in a release path.", "site": "Benchmark-cache", "report_type": "Near Miss"}
        client.post("/analyze", json=cached_payload).raise_for_status()
        for _ in range(30):
            start = time.perf_counter(); response = client.post("/analyze", json=cached_payload); cache_times.append((time.perf_counter() - start) * 1000)
            response.raise_for_status()
        batch_payload = {"reports": [{"narrative": f"{SAMPLES[index % 3]} Batch throughput record {index}.", "site": f"Batch-{index}"} for index in range(50)]}
        start = time.perf_counter(); batch_response = client.post("/analyze/batch", json=batch_payload); batch_seconds = time.perf_counter() - start
        batch_response.raise_for_status()

    artifact_files = [path for path in ARTIFACT_ROOT.rglob("*") if path.is_file() and ("supervised" in path.parts or "domain_adapted_v0_2" in path.parts)]
    deployed_files = [ARTIFACT_ROOT / "supervised" / "tfidf_logreg.joblib", ARTIFACT_ROOT / "supervised" / "threshold.json", ARTIFACT_ROOT / "domain_adapted_v0_2" / "lsr_model.joblib"]
    comparison_files = [path for path in (ARTIFACT_ROOT / "domain_adapted_v0_2").rglob("*") if path.is_file()]
    output = {
        "benchmark_version": "sif-domain-runtime-benchmark-v0.2", "measured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": {"platform": platform.platform(), "processor": platform.processor(), "logical_cpu_count": psutil.cpu_count(), "physical_cpu_count": psutil.cpu_count(logical=False), "ram_bytes": psutil.virtual_memory().total, "python": sys.version, "numpy": np.__version__, "joblib": joblib.__version__, "concurrency": 1},
        "workload": {"warm_component_requests": 120, "uncached_full_api_requests": 60, "cached_duplicate_requests": 30, "batch_size": 50, "report_character_lengths": [len(text) for text in SAMPLES]},
        "cold_start": stats(cold), "warm_sif_inference": stats(sif_times), "warm_lsr_total": stats(lsr_times),
        "text_normalization": stats(normalization_times), "lsr_vectorization_and_scoring": stats(preprocessing_times), "evidence_and_template": stats(evidence_times), "retrieval": stats(retrieval_times),
        "full_analysis_api_uncached": stats(api_times), "duplicate_cached_api": stats(cache_times),
        "batch": {"seconds": round(batch_seconds, 4), "reports": 50, "reports_per_second": round(50 / batch_seconds, 3)},
        "artifact_storage": {"all_baseline_and_v0_2_bytes": sum(path.stat().st_size for path in artifact_files), "all_files": len(artifact_files),
                             "deployed_sif_and_lsr_bytes": sum(path.stat().st_size for path in deployed_files),
                             "v0_2_comparison_package_bytes": sum(path.stat().st_size for path in comparison_files)},
        "process_memory": {"rss_before_load_bytes": rss_before, "rss_after_benchmark_bytes": process.memory_info().rss},
        "runtime_generative_llm_calls": 0, "llm_token_charges": 0,
        "llm_comparison": {"status": "not_measured", "reason": "No equivalent authorized measured LLM benchmark was available; no incident data was transmitted."},
        "cost_scope": "No runtime LLM token charges; hosting, offline annotation, training, and maintenance costs are excluded.",
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    temporary.unlink(missing_ok=True)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
