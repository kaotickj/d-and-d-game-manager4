"""Offline rules retrieval, provenance, safe imports and explicit downloads."""
from contextlib import closing
from dataclasses import replace
from email.message import Message
import hashlib
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from dndgm4.rules_reference import (
    MAX_DOCUMENT_BYTES, MAX_PASSAGE_CHARS, SRD_SOURCES, RulesRepository,
    _SRDRedirects, build_rules_context, html_to_text,
)


class RulesReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / "rules.sqlite3"
        self.repo = RulesRepository(self.path, seed=False)

    def tearDown(self):
        self.tmp.cleanup()

    def import_rule(self, **kwargs):
        values = dict(title="Cover rules", text="Cover protects a defender. Check the attack geometry.",
                      source_url="https://www.d20srd.org/srd/combat/combatModifiers.htm",
                      source_document_id="combat-modifiers", section="Cover", source_version="Fixture v1")
        values.update(kwargs)
        return self.repo.import_document(**values)

    def test_first_run_is_offline_and_has_labelled_searchable_summaries(self):
        with patch("dndgm4.rules_reference.build_opener") as network:
            repo = RulesRepository(self.path)
            self.assertGreaterEqual(len(repo.list_documents()), 10)
            hits = repo.search("critical hits")
        network.assert_not_called()
        self.assertTrue(hits)
        self.assertEqual(hits[0].edition, "3.5")
        self.assertEqual(hits[0].origin, "authored-summary")
        self.assertIn("Authored reference summary", hits[0].source_version)
        self.assertTrue(hits[0].source_url.startswith("https://www.d20srd.org/srd/"))
        count = len(repo.list_documents())
        self.assertEqual(len(RulesRepository(self.path).list_documents()), count)

    def test_import_retains_exact_provenance_and_content_digest_across_reopen(self):
        text = "Cover protects Élara.\n\nCheck the attack geometry."
        document_id = self.import_rule(text=text, source_title="SRD Combat Modifiers")
        doc = RulesRepository(self.path, seed=False).get_document(document_id)
        self.assertEqual(doc.text, text)
        self.assertEqual(doc.digest, hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(doc.source_document_id, "combat-modifiers")
        self.assertEqual(doc.section, "Cover")
        self.assertEqual(doc.source_title, "SRD Combat Modifiers")
        self.assertEqual(doc.source_version, "Fixture v1")
        self.assertTrue(doc.imported_at.endswith("+00:00"))
        self.assertIsNone(self.repo.get_document("missing-id"))

    def test_reimport_is_idempotent_and_changed_document_replaces_old_index(self):
        document_id = self.import_rule(text="A unique oldrule passage.")
        before = self.repo.get_document(document_id)
        self.assertEqual(self.import_rule(text=before.text), document_id)
        self.assertEqual(self.repo.get_document(document_id), before)
        self.assertEqual(self.import_rule(text="A unique newrule passage."), document_id)
        self.assertEqual(len(self.repo.list_documents()), 1)
        self.assertFalse(self.repo.search("oldrule"))
        self.assertEqual(self.repo.search("newrule")[0].document_id, document_id)

    def test_failed_replacement_rolls_back_document_passages_and_index(self):
        document_id = self.import_rule(text="Existing originalrule remains.")
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("""CREATE TRIGGER fail_passage BEFORE INSERT ON rules_passages
                BEGIN SELECT RAISE(ABORT, 'simulated disk error'); END""")
            db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.import_rule(text="replacementrule should not survive")
        self.assertIn("originalrule", self.repo.get_document(document_id).text)
        self.assertTrue(self.repo.search("originalrule"))
        self.assertFalse(self.repo.search("replacementrule"))

    def test_search_returns_ranked_bounded_literal_results(self):
        self.import_rule(title="A miscellaneous note", text="Cover may apply.", source_document_id="other")
        preferred = self.import_rule(title="Cover", text="Cover protects a defender.")
        hits = self.repo.search("cover", limit=1)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].document_id, preferred)
        self.assertIn("Cover", hits[0].snippet)
        self.assertEqual(hits[0].passage, hits[0].text)
        self.assertTrue(hits[0].digest)
        self.assertIn("passage 1", hits[0].section)
        self.assertFalse(self.repo.search("cover OR nonexistent"))
        self.assertFalse(self.repo.search("cover'); DROP TABLE rules_documents; --"))
        self.assertEqual(len(self.repo.list_documents()), 2)
        self.assertTrue(self.repo.search('"cover"'))
        self.assertFalse(self.repo.search("* - : \""))
        for query, limit in (("x" * 241, 20), ("cover", 0), ("cover", 51), ("cover", True)):
            with self.subTest(query=query, limit=limit), self.assertRaises(ValueError):
                self.repo.search(query, limit)

    def test_plain_sqlite_fallback_is_persistent_ranked_and_unicode_aware(self):
        repo = RulesRepository(self.path, seed=False, enable_fts=False)
        repo.import_document("A note", "ÉLARA sees cover nearby.")
        preferred = repo.import_document("Cover", "Élara tests cover.")
        hits = repo.search("élara cover")
        self.assertEqual(hits[0].document_id, preferred)
        self.assertEqual(len(hits), 2)
        self.assertEqual(len(RulesRepository(self.path, seed=False).search("élara cover")), 2)

    def test_long_documents_have_bounded_passages_and_full_original_available(self):
        text = "\n\n".join(f"Heading {index}\n" + ("sword " * 180) for index in range(8))
        document_id = self.import_rule(text=text)
        hits = self.repo.search("sword")
        self.assertGreater(len(hits), 1)
        self.assertTrue(all(len(hit.text) <= MAX_PASSAGE_CHARS for hit in hits))
        self.assertEqual(self.repo.get_document(document_id).text,
                         "\n".join(line.rstrip() for line in text.splitlines()).strip())
        original = [(hit.passage_id, hit.text) for hit in hits]
        self.repo.rebuild_index()
        self.assertEqual([(hit.passage_id, hit.text) for hit in self.repo.search("sword")], original)

    def test_invalid_imports_preserve_existing_documents(self):
        document_id = self.import_rule()
        for values in (
            {"edition": "5e"}, {"edition": "Pathfinder"}, {"text": "\n\n"},
            {"title": ""}, {"source_url": "javascript:alert(1)"},
            {"source_url": "https://5e.d20srd.org/srd/combat.htm"},
            {"source_url": "https://www.d20pfsrd.com/combat"},
            {"source_url": "https://username:password@example.com/rules"},
            {"source_digest": "not-a-digest"}, {"text": "x" * (MAX_DOCUMENT_BYTES + 1)},
        ):
            with self.subTest(values=list(values)), self.assertRaises(ValueError):
                self.import_rule(**values)
        self.assertEqual(len(self.repo.list_documents()), 1)
        self.assertIsNotNone(self.repo.get_document(document_id))

    def test_html_parser_removes_active_content_navigation_and_preserves_tables(self):
        html = """<html><head><meta charset='UTF-8'><script>head_bad()</script></head>
            <body><nav>navigation_bad</nav><div>preamble_bad</div><h1>Cover</h1>
            <p>Use <strong>geometry</strong> &amp; positioning.</p>
            <script>body_bad()</script><style>.bad {}</style>
            <table><tr><th>Type</th><th>Value</th></tr><tr><td>Cover</td><td>+4</td></tr></table>
            <footer>footer_bad</footer></body></html>"""
        text = html_to_text(html)
        self.assertIn("Use geometry & positioning.", text)
        self.assertIn("Cover | +4", text)
        self.assertNotIn("_bad", text)
        self.assertNotIn("<script>", text)

    def test_file_import_hashes_original_bytes_and_rejects_unsupported_or_invalid_files(self):
        path = Path(self.tmp.name) / "notes.html"
        raw = b"\xef\xbb\xbf<h1>Cover</h1><p>Local geometry rules.</p>"
        path.write_bytes(raw)
        document_id = self.repo.import_file(path)
        doc = self.repo.get_document(document_id)
        self.assertEqual(doc.source_digest, hashlib.sha256(raw).hexdigest())
        self.assertEqual(doc.source_document_id, "notes.html")
        self.assertEqual(doc.origin, "local-import")
        self.assertNotIn("<h1>", doc.text)
        for suffix, content in ((".pdf", b"text"), (".txt", b"\xff\xfeinvalid")):
            invalid = Path(self.tmp.name) / f"invalid{suffix}"
            invalid.write_bytes(content)
            with self.assertRaises(ValueError):
                self.repo.import_file(invalid)

    def fake_source(self, *, final_url=None, kind="text/html", content=None):
        source = SRD_SOURCES[0]
        response = MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = final_url or source.url
        response.headers = Message()
        response.headers["Content-Type"] = kind + "; charset=utf-8"
        response.read.return_value = content or ("<h1>The Basics</h1><p>" + "Synthetic fixture rule. " * 20 + "</p>").encode()
        opener = MagicMock()
        opener.open.return_value = response
        return opener, response

    def test_explicit_curated_fetch_stores_page_and_raw_digest(self):
        opener, response = self.fake_source()
        with patch("dndgm4.rules_reference.build_opener", return_value=opener):
            document_id = self.repo.fetch_source("basics")
        doc = self.repo.get_document(document_id)
        self.assertEqual(doc.origin, "srd-download")
        self.assertEqual(doc.edition, "3.5")
        self.assertEqual(doc.source_url, SRD_SOURCES[0].url)
        self.assertEqual(doc.source_digest, hashlib.sha256(response.read.return_value).hexdigest())
        self.assertIn("ogl.html", doc.license_url)
        self.assertIn("no revision identifier", doc.source_version)
        self.assertNotIn("<p>", doc.text)
        response.read.assert_called_once_with(MAX_DOCUMENT_BYTES + 1)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 12)

    def test_fetch_rejects_unknown_sources_redirects_and_bad_responses_without_writes(self):
        with patch("dndgm4.rules_reference.build_opener") as network:
            with self.assertRaises(ValueError):
                self.repo.fetch_source("https://example.com/anything")
            network.assert_not_called()
        for kwargs in (
            {"final_url": "https://5e.d20srd.org/rules"}, {"kind": "application/pdf"},
            {"content": b"x" * (MAX_DOCUMENT_BYTES + 1)}, {"content": b"<h1>Denied</h1>"},
        ):
            opener, _ = self.fake_source(**kwargs)
            with self.subTest(kwargs=list(kwargs)), patch(
                    "dndgm4.rules_reference.build_opener", return_value=opener), self.assertRaises(ValueError):
                self.repo.fetch_source("basics")
        self.assertFalse(self.repo.list_documents())
        with self.assertRaises(ValueError):
            _SRDRedirects().redirect_request(None, None, 302, "Found", {}, "http://127.0.0.1/private")

    def test_context_contains_only_selected_evidence_and_precise_citations(self):
        self.import_rule()
        self.import_rule(title="Other unrelated rule", text="Do not include this secret rule.", source_document_id="other")
        hit = self.repo.search("geometry")[0]
        context = build_rules_context([hit, hit], "Does cover apply?")
        for expected in ("[R1]", hit.text, hit.source_url, hit.digest, hit.source_document_id,
                         hit.section, hit.source_version, "Do not invent", "untrusted reference data"):
            self.assertIn(expected, context)
        self.assertNotIn("\n\n[R2]", context)
        self.assertNotIn("secret rule", context)
        self.assertLessEqual(len(context), 6000)
        for hits, kwargs in (([], {}), ([replace(hit, edition="5e")], {}),
                             ([replace(hit, text="x" * 6000)], {}), ([hit], {"max_chars": 500})):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_rules_context(hits, **kwargs)


if __name__ == "__main__":
    unittest.main()
