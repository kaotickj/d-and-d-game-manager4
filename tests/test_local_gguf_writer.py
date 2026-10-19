"""No-download local GGUF backend tests (mock process, never load weights)."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import unittest

from dndgm4 import local_ai


class LocalWriterTests(unittest.TestCase):
    def test_npc_and_monster_bios_use_distinct_rule_safe_prompts(self):
        for kind, expected in (
            ("bio", "character biography"),
            ("npc_bio", "NPC biographies"),
            ("monster_bio", "monster bestiary lore"),
        ):
            with self.subTest(kind=kind):
                self.assertIn(expected, local_ai.PROMPTS[kind])
                with patch.object(local_ai, "_post_json",
                                  return_value={"response": "A useful draft."}) as request:
                    result = local_ai.text_generate(
                        kind, "An original campaign in a misty valley",
                        backend="ollama", model="qwen3:4b",
                    )
                self.assertEqual(result, "A useful draft.")
                prompt = request.call_args.args[1]["prompt"]
                self.assertIn(local_ai.PROMPTS[kind], prompt)
        self.assertIn("Mindless creatures", local_ai.PROMPTS["monster_bio"])
        self.assertIn("Do not change ability scores", local_ai.PROMPTS["npc_bio"])

    def test_existing_models_are_in_goodneighbor_directory(self):
        qwen = local_ai.GGUF_MODELS["Qwen3 4B Instruct (GGUF)"]
        gemma = local_ai.GGUF_MODELS["Gemma The Writer 9B (GGUF)"]
        self.assertEqual(qwen.parent, local_ai.MODEL_FOLDER)
        self.assertEqual(gemma.parent, local_ai.MODEL_FOLDER)
        self.assertEqual(qwen.name, "Qwen3-4B-Instruct-2507-Q4_K_M.gguf")
        self.assertEqual(gemma.name, "Gemma-The-Writer-Mighty-Sword-9B-D_AU-Q4_k_m.gguf")
        self.assertEqual(local_ai.DEFAULT_MODEL, str(qwen))

    def test_missing_model_and_missing_executable_are_actionable(self):
        with self.assertRaisesRegex(local_ai.LocalAIError, "GGUF model file not found"):
            local_ai.text_generate("bio", "A ranger from the forest.",
                                   model="/no/such/weights.gguf")
        with TemporaryDirectory() as d:
            weights = Path(d) / "test.gguf"
            weights.write_bytes(b"unit test, not real weights")
            with patch.object(local_ai, "discover_llama_server", return_value=""):
                with self.assertRaisesRegex(local_ai.LocalAIError, "llama-server executable"):
                    local_ai.text_generate("bio", "A ranger from the forest.",
                                           model=str(weights))

    def test_gguf_server_uses_file_in_place_and_exits(self):
        with TemporaryDirectory() as d:
            directory = Path(d)
            weights = directory / "test.gguf"
            weights.write_bytes(b"example-only")
            binary = directory / "llama-server.exe"
            binary.write_bytes(b"dummy")
            process = Mock()
            process.poll.return_value = None
            with patch.object(local_ai.subprocess, "Popen", return_value=process) as popen, \
                 patch.object(local_ai, "_free_local_port", return_value=43177), \
                 patch.object(local_ai, "_wait_for_server") as ready, \
                 patch.object(local_ai, "_post_json",
                              return_value={"choices":[{"message":{"content":"The bridge is silent."}}]}) as post:
                response = local_ai.text_generate(
                    "dm", "A misty bridge beside a forest.",
                    model=str(weights), llama_server=str(binary), gpu_layers=12,
                )
            self.assertEqual(response, "The bridge is silent.")
            args = popen.call_args.args[0]
            self.assertIn(str(weights.resolve()), args)
            self.assertIn("--n-gpu-layers", args)
            self.assertEqual(args[args.index("--n-gpu-layers") + 1], "12")
            self.assertEqual(args[args.index("--host") + 1], "127.0.0.1")
            self.assertEqual(args[args.index("--port") + 1], "43177")
            self.assertIn("/v1/chat/completions", post.call_args.args[0])
            self.assertEqual(post.call_args.args[1]["messages"][0]["role"], "system")
            self.assertTrue(ready.called)
            process.terminate.assert_called_once()
            process.wait.assert_called_once()
            self.assertTrue(weights.is_file())

    def test_failed_generation_also_stops_local_engine(self):
        with TemporaryDirectory() as d:
            weights = Path(d) / "test.gguf"
            weights.write_bytes(b"dummy")
            binary = Path(d) / "llama-server.exe"
            binary.write_bytes(b"dummy")
            proc = Mock()
            proc.poll.return_value = None
            with patch.object(local_ai.subprocess, "Popen", return_value=proc), \
                 patch.object(local_ai, "_free_local_port", return_value=43177), \
                 patch.object(local_ai, "_wait_for_server"), \
                 patch.object(local_ai, "_post_json", side_effect=local_ai.LocalAIError("offline")):
                with self.assertRaisesRegex(local_ai.LocalAIError, "offline"):
                    local_ai.generate_gguf("bio", "An unusual knight.", str(weights),
                                           llama_server=str(binary))
            proc.terminate.assert_called_once()


    def test_conservative_default_thread_selection(self):
        self.assertEqual(local_ai.recommended_cpu_threads(12), 6)
        self.assertEqual(local_ai.recommended_cpu_threads(1), 1)
        self.assertEqual(local_ai.recommended_cpu_threads(64), 16)
        self.assertEqual(local_ai._validated_threads(None, None)[0],
                         local_ai.recommended_cpu_threads())
        self.assertEqual(local_ai._validated_threads(6, None), (6, 6))
        self.assertEqual(local_ai._validated_threads(6, 8), (6, 8))
        for invalid in (0, -1, 65, 3.4, True):
            with self.subTest(threads=invalid):
                with self.assertRaises(ValueError):
                    local_ai._validated_threads(invalid, 6)

    def test_native_threads_are_passed_to_llama_server(self):
        with TemporaryDirectory() as d:
            path = Path(d)
            weights = path / "performance.gguf"
            weights.write_bytes(b"dummy")
            exe = path / "llama-server.exe"
            exe.write_bytes(b"dummy")
            proc = Mock()
            proc.poll.return_value = None
            with patch.object(local_ai.subprocess, "Popen", return_value=proc) as popen, \
                 patch.object(local_ai, "_free_local_port", return_value=43177), \
                 patch.object(local_ai, "_wait_for_server"), \
                 patch.object(local_ai, "_post_json", return_value={
                     "choices": [{"message": {"content": "The cavern falls silent."}}]
                 }):
                output = local_ai.text_generate(
                    "dm", "A cavern entryway", model=str(weights),
                    llama_server=str(exe), cpu_threads=6, batch_threads=8)
            self.assertIn("cavern", output)
            cmd = popen.call_args.args[0]
            self.assertEqual(cmd[cmd.index("--threads")+1], "6")
            self.assertEqual(cmd[cmd.index("--threads-batch")+1], "8")
            self.assertEqual(cmd[cmd.index("--parallel")+1], "1")
            proc.terminate.assert_called_once()

    def test_keep_model_loaded_for_consecutive_requests_and_unload(self):
        # Model process must start once, be reused on request #2 and close
        # exactly once when explicitly unloaded. No duplicate model weight copy.
        local_ai.unload_cached_model()
        with TemporaryDirectory() as d:
            path = Path(d)
            weights = path / "existing.gguf"
            weights.write_bytes(b"dummy")
            exe = path / "llama-server.exe"
            exe.write_bytes(b"dummy")
            proc = Mock()
            proc.poll.return_value = None
            response = {"choices": [{"message": {"content": "The fog thickens."}}]}
            try:
                with patch.object(local_ai.subprocess, "Popen", return_value=proc) as popen, \
                     patch.object(local_ai, "_free_local_port", return_value=43177), \
                     patch.object(local_ai, "_wait_for_server") as ready, \
                     patch.object(local_ai, "_post_json", return_value=response) as post:
                    for task in ("dm", "bio"):
                        self.assertEqual(local_ai.text_generate(
                            task, "A fog-bound harbor.", model=str(weights),
                            llama_server=str(exe), keep_loaded=True, cpu_threads=6
                        ), "The fog thickens.")
                    self.assertEqual(popen.call_count, 1)
                    self.assertEqual(ready.call_count, 1)
                    self.assertEqual(post.call_count, 2)
                    proc.terminate.assert_not_called()
                    self.assertTrue(local_ai.unload_cached_model())
                    proc.terminate.assert_called_once()
                self.assertTrue(weights.exists())
            finally:
                local_ai.unload_cached_model()

    def test_switching_threads_restarts_cached_model_safely(self):
        local_ai.unload_cached_model()
        with TemporaryDirectory() as d:
            path = Path(d)
            weights = path / "existing.gguf"
            weights.write_bytes(b"dummy")
            exe = path / "llama-server.exe"
            exe.write_bytes(b"dummy")
            first, second = Mock(), Mock()
            first.poll.return_value = None
            second.poll.return_value = None
            response = {"choices": [{"message": {"content": "The guard nods."}}]}
            try:
                with patch.object(local_ai.subprocess, "Popen",
                                  side_effect=(first, second)) as popen, \
                     patch.object(local_ai, "_free_local_port", return_value=43177), \
                     patch.object(local_ai, "_wait_for_server"), \
                     patch.object(local_ai, "_post_json", return_value=response):
                    for threads in (6, 4):
                        local_ai.text_generate(
                            "dm", "A watchtower.", model=str(weights),
                            llama_server=str(exe), cpu_threads=threads,
                            keep_loaded=True)
                    self.assertEqual(popen.call_count, 2)
                    first.terminate.assert_called_once()
                    second.terminate.assert_not_called()
                    self.assertTrue(local_ai.unload_cached_model())
                    second.terminate.assert_called_once()
            finally:
                local_ai.unload_cached_model()

    def test_unload_during_generation_is_nonblocking(self):
        with local_ai._WARM_MANAGER.lock:
            self.assertFalse(local_ai.unload_cached_model())

    def test_legacy_ollama_still_available(self):
        with patch.object(local_ai, "_post_json",
                          return_value={"response": "<think>private</think>Draft."}) as post:
            content = local_ai.text_generate(
                "bio", "A young elven diplomat.",
                model="qwen3:4b", backend="ollama",
            )
        self.assertEqual(content, "Draft.")
        self.assertEqual(post.call_args.args[0], local_ai.OLLAMA_URL)

    def test_rejects_unknown_backends_and_bad_gpu_layers(self):
        with self.assertRaises(ValueError):
            local_ai.text_generate("bio", "A warrior.", backend="cloud")
        with self.assertRaises(ValueError):
            local_ai.generate_gguf("bio", "A warrior.", "/tmp/test.gguf", gpu_layers=120)


if __name__ == "__main__":
    unittest.main()
