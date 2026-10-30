import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class MakeRunTests(unittest.TestCase):
    def test_run_forwards_optional_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            uv = Path(directory) / "uv"
            uv.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "print(json.dumps(sys.argv[1:]))\n"
            )
            uv.chmod(0o755)
            for prompt in [
                None,
                "what is the weather in california?",
                "What's the weather?",
                'Keep "$HOME", `pwd`, and $(pwd) literal; & | < >',
            ]:
                with self.subTest(prompt=prompt):
                    result = subprocess.run(
                        ["make", "--silent", "run", *([prompt] if prompt else [])],
                        cwd=Path(__file__).resolve().parents[1],
                        env={**os.environ, "PATH": f"{directory}:{os.environ['PATH']}"},
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(
                        json.loads(result.stdout),
                        ["run", "reels-ripper-agent", *([prompt] if prompt else [])],
                    )
