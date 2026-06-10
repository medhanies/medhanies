import json

from aml_engine.__main__ import main


class TestRun:
    def test_end_to_end(self, tmp_path, capsys):
        rc = main(["run", "--seed", "42", "--out", str(tmp_path)])
        assert rc == 0

        out = capsys.readouterr().out
        assert "SAR-CANDIDATE WORKLIST" in out
        assert "Scenario recall: 10/10 (100%)" in out

        alerts = json.loads((tmp_path / "alerts.json").read_text())
        assert alerts, "alerts.json should not be empty"
        assert {"rule_id", "citation", "narrative", "final_score", "tier"} <= set(alerts[0])
        assert (tmp_path / "flagged_transactions.csv").exists()
        assert (tmp_path / "sar_worklist.csv").exists()

    def test_reproducible_across_runs(self, tmp_path, capsys):
        main(["run", "--seed", "9", "--no-eval"])
        first = capsys.readouterr().out
        main(["run", "--seed", "9", "--no-eval"])
        second = capsys.readouterr().out
        assert first == second

    def test_min_severity_filters_console_alerts(self, capsys):
        rc = main(["run", "--seed", "42", "--min-severity", "critical", "--no-eval"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "at CRITICAL+" in out


class TestGenerateAndDetect:
    def test_generate_then_detect(self, tmp_path, capsys):
        csv_path = tmp_path / "txns.csv"
        rc = main(["generate", "--seed", "42", "--out", str(csv_path)])
        assert rc == 0
        assert csv_path.exists()

        rc = main(["detect", "--input", str(csv_path), "--out", str(tmp_path / "det")])
        assert rc == 0
        out = capsys.readouterr().out
        # Transaction-level rules still fire on CSV input (no entity data).
        assert "R-JURIS-001" in out
        assert "R-STRUCT-001" in out

    def test_detect_missing_input_fails_cleanly(self, tmp_path, capsys):
        rc = main(["detect", "--input", str(tmp_path / "nope.csv")])
        assert rc == 2


class TestRulesCatalog:
    def test_prints_all_rules_with_citations(self, capsys):
        rc = main(["rules"])
        assert rc == 0
        out = capsys.readouterr().out
        for rule_id in [
            "R-STRUCT-001", "R-STRUCT-002", "R-STRUCT-003",
            "R-JURIS-001", "R-JURIS-002", "R-JURIS-003",
            "R-BO-001", "R-BO-002", "R-BO-003", "R-BO-004",
        ]:
            assert rule_id in out
        assert "31 CFR 1010.311" in out
        assert "31 CFR 1010.230" in out
