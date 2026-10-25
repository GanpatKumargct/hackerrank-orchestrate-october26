import unittest

from audit.evidence.log_parser import parse_line, parse_log
from audit.evidence.text_parser import parse_text
from tests.fixtures import TempDir, manifest_row, write_file

TS = "2026-05-09T10:00:00Z"
SHAPES = {
    "kv": f'{TS} level=INFO service=account_service trace_id=t1 resource_id=account_90001 event=profile_lookup_completed rows=0',
    "kvinfo": f'{TS} INFO service=search_index_service event=record_lookup seq=1 system="account_service" resource_id="account_90002" result="FOUND"',
    "json": f'{TS} {{"severity":"INFO","service":"security_service","trace_id":"t2","resource_id":"audit_record_90001","event":"audit_record_read_completed","rows":"1"}}',
    "syslog": f'{TS} <15>1 node-1 support_platform t3 - - level=DEBUG event="attachment_scan_started" scan_key="s@example.org"',
    "cloud": f'{TS} requestId=t4 level=DEBUG function=profile_service message="resource_id=\\"account_90003\\" event=\\"profile_lookup_completed\\" rows=\\"1\\" correlation_key=\\"c@example.org\\""',
    "pipe": f'{TS} | DEBUG | analytics_platform | t5 | analytics_profile_read | resource_id="analytics_90001" email="null"',
    "bracket": f'{TS} [INFO] [account_service] [t6] profile_lookup_completed: resource_id="account_90004" rows="0"',
}


class TestLineShapes(unittest.TestCase):
    def test_each_shape_parses(self):
        for shape, line in SHAPES.items():
            p = parse_line(line)
            self.assertIsNotNone(p, shape)
            self.assertEqual(p["shape"], shape)
            self.assertEqual(p["ts"], TS)
        self.assertEqual(parse_line(SHAPES["cloud"])["kv"]["correlation_key"], "c@example.org")
        self.assertEqual(parse_line(SHAPES["cloud"])["service"], "profile_service")
        self.assertEqual(parse_line(SHAPES["bracket"])["event"], "profile_lookup_completed")
        self.assertEqual(parse_line(SHAPES["syslog"])["trace"], "t3")

    def test_unrecognised_line(self):
        self.assertIsNone(parse_line("not a log line"))


class TestTraceGrouping(unittest.TestCase):
    def run_log(self, text):
        with TempDir() as d:
            p = write_file(d, "x.log", text)
            return parse_log(manifest_row(p))

    def test_started_key_attached_as_trace_key(self):
        text = ("2026-05-09T10:00:00Z level=DEBUG service=account_service trace_id=rb-1 event=profile_lookup_started "
                "resource_id=account_90010 lookup_key=k@example.org\n"
                "2026-05-09T10:00:01Z level=DEBUG service=account_service trace_id=rb-1 event=connection_acquired\n"
                "2026-05-09T10:00:02Z level=ERROR service=account_service trace_id=rb-1 event=profile_lookup_completed "
                "resource_id=account_90010 rows=0 http_status=404\n")
        obs, rep = self.run_log(text)
        self.assertEqual(len(obs), 1)                       # started line is not an observation
        o = obs[0]
        self.assertEqual(o.observed_raw, "2026-05-09T10:00:02Z")
        self.assertEqual([(h.relationship, h.normalised, h.field) for h in o.keys],
                         [("TRACE_KEY", "k@example.org", "lookup_key")])
        self.assertEqual(o.identifiers, ())                 # the key is not a record field
        self.assertEqual(o.context["level"], "ERROR")       # stored, carries no state
        self.assertEqual(rep.noise_units, 2)

    def test_resource_id_lookup_key_is_not_identifier(self):
        text = ('2026-05-09T10:00:00Z | DEBUG | analytics_platform | t9 | analytics_profile_scan_started | lookup_key="analytics_90020"\n'
                '2026-05-09T10:00:01Z | INFO | analytics_platform | t9 | analytics_profile_read | resource_id="analytics_90020" email="null"\n')
        obs, _ = self.run_log(text)
        self.assertEqual(obs[0].keys, ())

    def test_own_correlation_key_not_duplicated(self):
        obs, _ = self.run_log(SHAPES["cloud"] + "\n")
        self.assertEqual([h.normalised for h in obs[0].keys], ["c@example.org"])

    def test_record_lookup_without_trace_has_explicit_system(self):
        obs, _ = self.run_log(SHAPES["kvinfo"] + "\n")
        self.assertEqual((obs[0].system_id, obs[0].reporter_service), ("account_service", "search_index_service"))

    def test_noise_event_with_resource_is_warned(self):
        text = "2026-05-09T10:00:00Z level=ERROR service=attachment_preview event=thumbnail_failed resource_id=support_90030\n"
        obs, rep = self.run_log(text)
        self.assertEqual(obs, [])
        self.assertTrue(any("thumbnail_failed" in w for w in rep.warnings))

    def test_unparsed_line_makes_partial(self):
        obs, rep = self.run_log(SHAPES["kv"] + "\ngarbage line\n")
        self.assertEqual((len(obs), rep.status, rep.unparsed_units), (1, "PARTIAL", 1))


class TestTextParser(unittest.TestCase):
    def test_handover_rows(self):
        text = ("CUSTOMER PLATFORM - SHIFT HANDOVER\nSnapshot: 2026-05-10T12:00:00Z\n\n"
                "- 2026-05-10T12:00:00Z | account_service | account_90040 | USER_PROFILE | NOT_FOUND | H@Example.org\n"
                "- 2026-05-10T12:00:00Z | analytics_platform | analytics_90040 | ANALYTICS_PROFILE | ANONYMIZED | no direct identifier\n")
        with TempDir() as d:
            obs, rep = parse_text(manifest_row(write_file(d, "h.txt", text)))
        self.assertEqual((rep.status, len(obs), rep.noise_units), ("OK", 2, 2))
        self.assertEqual([h.normalised for h in obs[0].identifiers], ["h@example.org"])
        self.assertEqual(obs[1].identifiers, ())
        self.assertEqual(obs[1].fields["subject"], "no direct identifier")
        self.assertEqual((obs[1].system_id, obs[1].record_type), ("analytics_platform", "ANALYTICS_PROFILE"))


if __name__ == "__main__":
    unittest.main()
