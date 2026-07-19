#!/usr/bin/env python3
"""One-command Phase 1 safety suite.

    python tests/run_regression.py

Starts a temporary static server for the app, runs every characterization/regression
suite grouped by domain, tears the server down, prints a PASS/FAIL summary, writes
tests/reports/latest.{json,md}, and exits non-zero if anything failed.

No production network calls (browser suites mock Supabase). No developer-specific
absolute paths. Works from the repo root on Windows/macOS/Linux.

Requires: Python 3.9+, `playwright` (`pip install playwright` + `playwright install chromium`).
The pure-data suites need only Python; the importer-determinism suite additionally
needs `openpyxl` and will self-skip if absent.
"""
import json, os, socket, subprocess, sys, time, urllib.request, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Suites grouped by domain. Paths are repo-relative.
GROUPS = {
    "Utilities (Phase 2)": [
        "tests/browser/test_util_units.py",
    ],
    "CardRepository (Phase 3)": [
        "tests/browser/test_card_repository.py",
    ],
    "SettingsRepository (Phase 4)": [
        "tests/browser/test_settings_repository.py",
    ],
    "SessionQuery (Phase 5)": [
        "tests/browser/test_session_query.py",
    ],
    "StudySessionEngine (Phase 16)": [
        "tests/browser/test_study_session_engine.py",
    ],
    "StudySessionStateMachine (Phase 19)": [
        "tests/browser/test_study_session_state_machine.py",
    ],
    "AnalyticsQuery (Phase 6)": [
        "tests/browser/test_analytics_query.py",
    ],
    "UserMetadataQuery (Phase 7)": [
        "tests/browser/test_user_metadata_query.py",
    ],
    "ProgressRepository (Phase 8)": [
        "tests/browser/test_progress_repository.py",
    ],
    "ProgressWriter (Phase 12)": [
        "tests/browser/test_progress_writer.py",
    ],
    "AuthContextQuery (Phase 15)": [
        "tests/browser/test_auth_context_query.py",
    ],
    "TestModeQuery (Phase 9)": [
        "tests/browser/test_test_mode_query.py",
    ],
    "ContentPack (Phase 10)": [
        "tests/browser/test_content_pack.py",
    ],
    "Content Pack v1 (Phase 24C)": [
        "tests/browser/test_content_pack_v1.py",
    ],
    "Data & contracts": [
        "tests/data/test_card_stability.py",
        "tests/data/test_baseline_comparison.py",
        "tests/data/test_importer_determinism.py",
        "tests/data/test_adapter_roundtrip.py",
        "tests/data/test_contracts.py",
    ],
    "SRS & Study Mode": [
        "tests/browser/test_srs_scheduler.py",
        "tests/browser/test_srs_characterization.py",
        "tests/regression/p0_test.py",
        "tests/regression/regression.py",
        "tests/regression/completion_loop.py",
        "tests/regression/streak_semantics.py",
        "tests/regression/targeted_continuity.py",
        "tests/regression/back_vocab_visibility.py",
    ],
    "Features (Weak/Smart/Bookmarks/Notes)": [
        "tests/regression/features_test.py",
        "tests/regression/qa2.py",
        "tests/browser/test_metadata_sync.py",
        "tests/regression/daily_goal.py",
    ],
    "Test Mode": [
        "tests/regression/test_mode.py",
    ],
    "Auth, Sync & Isolation": [
        "tests/regression/auth_test.py",
        "tests/regression/offline_test.py",
    ],
    "Native readiness (Phase 24A)": [
        "tests/regression/platform_adapter.py",
    ],
    "Release tooling (Phase 24B)": [
        "tests/tooling/test_release_check.py",
    ],
    "Content pack pipeline (Phase 24D)": [
        "tests/data/test_pack_build_parse.py",
        "tests/data/test_pack_build_identity.py",
        "tests/data/test_pack_build_determinism.py",
        "tests/data/test_pack_build_safety.py",
        "tests/data/test_pack_build_qa.py",
        "tests/data/test_pack_build_transaction.py",
        "tests/data/test_pack_build_concurrency.py",
        "tests/data/test_pack_build_hsk_conformance.py",
    ],
    "Pack foundation (Phase 24E-A)": [
        "tests/data/test_pack_registry.py",
        "tests/data/test_pack_boot_plan.py",
        "tests/data/test_pack_catalog_build.py",
        "tests/data/test_pack_promotion.py",
        "tests/data/test_pack_foundation_isolation.py",
    ],
    "Pack runtime integration (Phase 24E-B)": [
        "tests/data/test_pack_catalog_legacy.py",
        "tests/browser/test_pack_catalog_runtime.py",
        "tests/browser/test_pack_boot_parser_time.py",
        "tests/browser/test_pack_settings_no_write.py",
        "tests/browser/test_pack_switch.py",
    ],
}

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def start_server(port):
    proc = subprocess.Popen([sys.executable, "-m", "http.server", str(port)],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://localhost:{port}/hsk_flashcard_app/"
    for _ in range(60):
        try:
            if urllib.request.urlopen(url, timeout=1).status == 200:
                return proc
        except Exception:
            time.sleep(0.25)
    proc.terminate()
    raise RuntimeError("static server did not come up")

def parse_result(stdout):
    """Return the last JSON object on stdout that has a 'pass' key, else None."""
    res = None
    for line in stdout.splitlines():
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            o = json.loads(line)
            if isinstance(o, dict) and "pass" in o:
                res = o
        except Exception:
            pass
    return res

def run_suite(path, base_url):
    env = dict(os.environ, HSK_BASE_URL=base_url, PYTHONIOENCODING="utf-8")
    try:
        r = subprocess.run([sys.executable, path], cwd=ROOT, env=env,
                           capture_output=True, text=True, encoding="utf-8", timeout=300)
    except subprocess.TimeoutExpired:
        return {"suite": path, "pass": False, "error": "timeout"}
    res = parse_result(r.stdout or "")
    if res is None:
        return {"suite": path, "pass": False,
                "error": "no parseable result", "exit": r.returncode,
                "stderr": (r.stderr or "")[-400:]}
    res.setdefault("suite", path)
    # exit code is a corroborating signal, but 'pass' from output is authoritative
    if r.returncode != 0 and res.get("pass") is True:
        res["pass"] = False
        res["error"] = f"nonzero exit {r.returncode}"
    return res

def main():
    port = free_port()
    proc = start_server(port)
    base = f"http://localhost:{port}"
    results = {}
    try:
        for group, suites in GROUPS.items():
            results[group] = [run_suite(s, base) for s in suites]
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except Exception: proc.kill()

    # summary
    total = passed = 0
    lines = []
    for group, res in results.items():
        lines.append(f"\n== {group} ==")
        for r in res:
            total += 1; ok = bool(r.get("pass")); passed += ok
            tag = "PASS" if ok else "FAIL"
            extra = "" if ok else f"  -> {r.get('fails') or r.get('error') or r.get('errors') or ''}"
            lines.append(f"  [{tag}] {r['suite']}{extra}")
    overall = passed == total
    header = f"Phase 1 safety suite: {passed}/{total} suites passed — {'PASS' if overall else 'FAIL'}"
    print(header)
    print("\n".join(lines))

    # report
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except Exception:
        commit = branch = "unknown"
    report = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "branch": branch, "commit": commit,
        "overall": "PASS" if overall else "FAIL",
        "suitesPassed": passed, "suitesTotal": total, "groups": results,
    }
    rd = os.path.join(ROOT, "tests", "reports"); os.makedirs(rd, exist_ok=True)
    with open(os.path.join(rd, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(os.path.join(rd, "latest.md"), "w", encoding="utf-8") as f:
        f.write(f"# Regression report — {report['overall']}\n\n")
        f.write(f"- time: {report['timestamp']}\n- branch: {branch}\n- commit: {commit}\n")
        f.write(f"- suites: {passed}/{total}\n\n")
        for group, res in results.items():
            f.write(f"## {group}\n")
            for r in res:
                f.write(f"- {'✅' if r.get('pass') else '❌'} `{r['suite']}`\n")
            f.write("\n")
    print(f"\nreport: tests/reports/latest.json  (and latest.md)")
    return 0 if overall else 1

if __name__ == "__main__":
    sys.exit(main())
