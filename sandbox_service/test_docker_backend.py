import io
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SERVICE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVICE_DIR))

try:
    import pexpect  # noqa: F401
except ModuleNotFoundError:
    pexpect_stub = types.ModuleType("pexpect")
    pexpect_stub.TIMEOUT = TimeoutError
    pexpect_stub.EOF = EOFError
    pexpect_stub.spawn = Mock()
    sys.modules["pexpect"] = pexpect_stub

import terminal_registry as registry
from docker_sandbox import DockerTerminal


class DockerBackendSelectionTests(unittest.TestCase):
    def tearDown(self):
        with registry._registry_lock:
            registry._terminals.clear()

    def test_explicit_docker_backend_creates_docker_terminal(self):
        with patch.object(registry, "SANDBOX_BACKEND", "docker"), patch.object(
            registry, "DockerTerminal"
        ) as terminal:
            instance = registry._get_terminal("user-1")

        terminal.assert_called_once_with("user-1")
        self.assertIs(instance, terminal.return_value)

    def test_docker_backend_supports_python_and_private_files(self):
        terminal = Mock(spec=DockerTerminal)
        terminal.run_python.return_value = {"chunks": [{"content": "3"}]}
        terminal.read_file.return_value = b"abc"
        terminal.file_exists.return_value = True

        with patch.object(registry, "_get_terminal", return_value=terminal):
            result = registry.run_python("print(1 + 2)", "user-1", "kernel-1")
            registry.write_file_bytes("/workspace/a.bin", io.BytesIO(b"abc"), "user-1")
            content = registry.read_file_bytes("/workspace/a.bin", "user-1")
            exists = registry.file_exists("/workspace/a.bin", "user-1")

        self.assertEqual(result["chunks"][0]["content"], "3")
        terminal.write_file_bytes.assert_called_once()
        self.assertEqual(content, b"abc")
        self.assertTrue(exists)

    def test_docker_terminal_mounts_shared_data_volume(self):
        with patch("docker_sandbox.SHARED_DATA_DOCKER_VOLUME", "idea_idea_shared_data"), patch.object(
            DockerTerminal,
            "_docker",
            side_effect=[
                Mock(returncode=1, stdout=b"", stderr=b"not found"),
                Mock(returncode=0, stdout=b"container-id", stderr=b""),
            ],
        ) as docker:
            DockerTerminal("user-1", image="research-image")

        create_args = docker.call_args_list[-1].args
        self.assertIn("--mount", create_args)
        self.assertIn(
            "type=volume,source=idea_idea_shared_data,target=/app/data,readonly",
            create_args,
        )


if __name__ == "__main__":
    unittest.main()
