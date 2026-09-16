"""独立新进程与全新 scratch，真实 PG，禁止本地权威读写和 SQLite。"""

import asyncio
import json
import os
from pathlib import Path
import sys

from deeptutor_enterprise.migrations.runner import MigrationRunner
from test_preflight import deployment as deployment


async def test_full_process_file_guard_and_explicit_crash_rebuild(pg_dsn, deployment, tmp_path):
    await MigrationRunner(pg_dsn).apply()
    config = deployment.model_copy(
        update={
            "resource": "process-probe",
            "models": (
                deployment.models[0].model_copy(update={"context_window": 4096, "max_tokens": 300}),
            ),
        }
    )
    root = Path(__file__).resolve().parents[3]
    paths = [
        str(root),
        str(root / "extensions/enterprise/src"),
        str(root / "extensions/enterprise/tests"),
        str(root / ".venv/lib/python3.14/site-packages"),
    ]
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(paths),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PROBE_ROOT": str(root),
        "PROBE_CONFIG": config.model_dump_json(),
        "PROBE_DB": pg_dsn.replace("user=postgres", "user=dt_enterprise_app"),
        "PROBE_BOOT": "b" * 48,
    }
    outputs = []
    for phase in ("first", "second"):
        scratch = tmp_path / phase
        scratch.mkdir()
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(Path(__file__).with_name("_process_probe.py")),
            phase,
            cwd=scratch,
            env={**env, "DEEPTUTOR_HOME": str(scratch)},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), 90)
        except TimeoutError:
            process.kill()
            await process.communicate()
            raise
        assert process.returncode == (42 if phase == "first" else 0), (
            stdout.decode(),
            stderr.decode(),
        )
        result = json.loads(stdout.decode().strip().splitlines()[-1])
        assert result["local_authority_io"] == 0
        outputs.append(result)
        if phase == "first":
            env["PROBE_STATE"] = json.dumps(result)
        assert not (scratch / "data").exists()
    assert outputs[1]["recovered_turns"] == 2
