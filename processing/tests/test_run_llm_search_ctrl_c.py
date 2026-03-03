import io
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, ClassVar, cast
from unittest.mock import patch

from processing import run_llm_search


class FakePopen:
    handler: ClassVar[Callable[[int, Any], None] | None] = None
    handler_lock: ClassVar[threading.Lock] = threading.Lock()
    sigints_sent: ClassVar[bool] = False
    sigints_sent_lock: ClassVar[threading.Lock] = threading.Lock()
    kill_count: ClassVar[int] = 0
    kill_count_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, *args: Any, **kwargs: Any):
        self.returncode: int | None = None
        self.killed = False
        self.stdout = kwargs.get("stdout")
        self.stderr = kwargs.get("stderr")

    @classmethod
    def reset(cls):
        with cls.handler_lock:
            cls.handler = None
        with cls.sigints_sent_lock:
            cls.sigints_sent = False
        with cls.kill_count_lock:
            cls.kill_count = 0

    @classmethod
    def set_handler(cls, handler: Callable[[int, Any], None] | None) -> None:
        with cls.handler_lock:
            cls.handler = handler

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        self._emit_double_sigint_once()
        start = time.time()
        while not self.killed:
            if timeout is not None and (time.time() - start) > timeout:
                raise TimeoutError("fake process timed out")
            time.sleep(0.01)
        return ("", "killed by test")

    def _emit_double_sigint_once(self):
        with FakePopen.sigints_sent_lock:
            if FakePopen.sigints_sent:
                return
            FakePopen.sigints_sent = True
        with FakePopen.handler_lock:
            handler = FakePopen.handler
        if handler is None or not callable(handler):
            return
        # pylint: disable=not-callable
        handler(2, None)
        # pylint: disable=not-callable
        handler(2, None)

    def poll(self):
        return self.returncode

    def kill(self):
        with FakePopen.kill_count_lock:
            FakePopen.kill_count += 1
        self.killed = True
        self.returncode = -9


class ImmediateSuccessPopen:
    spawn_count: ClassVar[int] = 0
    spawn_count_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, *args: Any, **kwargs: Any):
        with self.spawn_count_lock:
            type(self).spawn_count += 1
        self.returncode: int | None = 0
        self.pid = 99999

    @classmethod
    def reset(cls) -> None:
        with cls.spawn_count_lock:
            cls.spawn_count = 0

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        _ = timeout
        return ("ok", "")

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


class CtrlCPipelineIntegrationTest(unittest.TestCase):
    def test_second_ctrl_c_aborts_and_kills_running_agents(self):
        FakePopen.reset()
        jobs = [
            {"symbol": "GENE1", "mode": "new"},
            {"symbol": "GENE2", "mode": "new"},
        ]

        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_settings = tmp / "settings.json"
            fake_settings.write_text("{}")
            fake_db = tmp / "sspsygene.db"
            fake_db.write_text("")
            logs_dir = tmp / "logs"
            results_dir = tmp / "results"

            old_signal = object()

            def fake_signal(_sig: int, handler: Any):
                if callable(handler):
                    FakePopen.set_handler(cast(Callable[[int, Any], None], handler))
                else:
                    FakePopen.set_handler(None)
                return old_signal

            def fake_build_prompt_for_job(
                _job: dict[str, Any], _symbol_to_id: dict[str, int] | None = None
            ) -> tuple[str, None]:
                return ("fake prompt", None)

            stdout_buffer = io.StringIO()
            with (
                patch.object(run_llm_search, "SETTINGS_FILE", fake_settings),
                patch.object(run_llm_search, "LOGS_DIR", logs_dir),
                patch.object(run_llm_search, "GENE_RESULTS_DIR", results_dir),
                patch.object(run_llm_search, "load_jobs", return_value=jobs),
                patch.object(
                    run_llm_search,
                    "get_sspsygene_config",
                    return_value=type("Cfg", (), {"out_db": fake_db})(),
                ),
                patch.object(
                    run_llm_search,
                    "_load_symbol_to_central_gene_id",
                    return_value={"GENE1": 1, "GENE2": 2},
                ),
                patch.object(
                    run_llm_search,
                    "build_prompt_for_job",
                    side_effect=fake_build_prompt_for_job,
                ),
                patch.object(run_llm_search.subprocess, "Popen", FakePopen),
                patch.object(
                    run_llm_search.signal, "getsignal", return_value=old_signal
                ),
                patch.object(run_llm_search.signal, "signal", side_effect=fake_signal),
                redirect_stdout(stdout_buffer),
            ):
                rc = run_llm_search.run_pipeline(
                    yaml_file="unused.yaml",
                    max_workers=2,
                    timeout=5,
                )

            output = stdout_buffer.getvalue()
            self.assertEqual(rc, 130)
            self.assertIn("Ctrl-C received. Press Ctrl-C again", output)
            self.assertIn("Second Ctrl-C received. Aborting run", output)
            self.assertGreaterEqual(FakePopen.kill_count, 1)

    def test_generate_config_uses_symbol_only_jobs(self):
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_db = tmp / "sspsygene.db"
            fake_db.write_text("")
            output_yaml = tmp / "llm_jobs.yaml"

            fake_config = type("Cfg", (), {"out_db": fake_db})()
            fake_genes = [
                {"central_gene_id": 123, "human_symbol": "GENE1"},
                {"central_gene_id": 456, "human_symbol": "GENE2"},
            ]

            with (
                patch.object(
                    run_llm_search, "get_sspsygene_config", return_value=fake_config
                ),
                patch.object(run_llm_search, "get_top_genes", return_value=fake_genes),
                patch.object(run_llm_search, "GENE_RESULTS_DIR", tmp / "results"),
            ):
                rc = run_llm_search.generate_config(top_n=2, output=str(output_yaml))

            self.assertEqual(rc, 0)
            contents = output_yaml.read_text()
            self.assertIn("symbol: GENE1", contents)
            self.assertIn("symbol: GENE2", contents)
            self.assertNotIn("central_gene_id:", contents)

    def test_run_pipeline_resolves_ids_from_symbol_and_skips_unknown(self):
        ImmediateSuccessPopen.reset()
        jobs = [
            {"symbol": "GENE1", "mode": "new"},
            {"symbol": "MISSING", "mode": "new"},
        ]

        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_settings = tmp / "settings.json"
            fake_settings.write_text("{}")
            fake_db = tmp / "sspsygene.db"
            fake_db.write_text("")
            logs_dir = tmp / "logs"
            results_dir = tmp / "results"
            fake_config = type("Cfg", (), {"out_db": fake_db})()

            stdout_buffer = io.StringIO()
            with (
                patch.object(run_llm_search, "SETTINGS_FILE", fake_settings),
                patch.object(run_llm_search, "LOGS_DIR", logs_dir),
                patch.object(run_llm_search, "GENE_RESULTS_DIR", results_dir),
                patch.object(run_llm_search, "load_jobs", return_value=jobs),
                patch.object(
                    run_llm_search,
                    "get_sspsygene_config",
                    return_value=fake_config,
                ),
                patch.object(
                    run_llm_search,
                    "_load_symbol_to_central_gene_id",
                    return_value={"GENE1": 42},
                ),
                patch.object(run_llm_search.signal, "getsignal", return_value=object()),
                patch.object(run_llm_search.signal, "signal", return_value=object()),
                patch.object(run_llm_search.subprocess, "Popen", ImmediateSuccessPopen),
                redirect_stdout(stdout_buffer),
            ):
                rc = run_llm_search.run_pipeline(
                    yaml_file="unused.yaml",
                    max_workers=1,
                    timeout=5,
                )

            output = stdout_buffer.getvalue()
            self.assertEqual(rc, 0)
            self.assertIn("[QUEUE] GENE1", output)
            self.assertIn("[SKIP] MISSING", output)
            self.assertIn("symbol not found in central_gene table", output)
            self.assertEqual(ImmediateSuccessPopen.spawn_count, 1)


if __name__ == "__main__":
    unittest.main()
