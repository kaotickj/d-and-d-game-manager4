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


    def test_original_launch_args_and_one_process_per_generation(self):
        with TemporaryDirectory() as d:
            path = Path(d)
            weights = path / "existing.gguf"
            weights.write_bytes(b"dummy")
            exe = path / "llama-server.exe"
            exe.write_bytes(b"dummy")
            proc = Mock()
            proc.poll.return_value = None
            response = {"choices":[{"message":{"content":"The mists rise."}}]}
            with patch.object(local_ai.subprocess, "Popen", return_value=proc) as start, \
                 patch.object(local_ai, "_free_local_port", return_value=43177), \
                 patch.object(local_ai, "_wait_for_server"), \
                 patch.object(local_ai, "_post_json", return_value=response):
                for task in ("dm", "monster_bio"):
                    self.assertEqual(local_ai.text_generate(
                        task, "The bridge at midnight.", model=str(weights),
                        llama_server=str(exe)), "The mists rise.")
            self.assertEqual(start.call_count, 2)
            self.assertEqual(proc.terminate.call_count, 2)
            args = start.call_args.args[0]
            for retired in ("--threads", "--threads-batch", "--parallel"):
                self.assertNotIn(retired, args)
            self.assertEqual(args[args.index("--host")+1], "127.0.0.1")
            self.assertTrue(weights.exists())

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
