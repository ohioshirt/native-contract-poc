import json
import unittest

from integration.wire import WireError, parse_refresh


def _request(**overrides):
    value = {
        "version": 1,
        "runId": "run-wire-test",
        "requestTag": "attempt-01/APP-02/p1:refresh:3",
        "requestId": "1",
        "account": "A",
        "refreshToken": "demo-A-v0",
    }
    value.update(overrides)
    return value


class RefreshWireTests(unittest.TestCase):
    def test_valid_envelope_preserves_decimal_request_id(self):
        parsed = parse_refresh(json.dumps(_request()).encode())

        self.assertEqual(parsed, _request())
        self.assertIs(type(parsed["version"]), int)
        self.assertIs(type(parsed["requestId"]), str)

    def test_duplicate_json_keys_rejected(self):
        body = (
            b'{"version":1,"runId":"run-wire-test","requestTag":"tag",'
            b'"requestId":"1","account":"A","refreshToken":"demo-A-v0",'
            b'"version":1}'
        )

        with self.assertRaises(WireError) as raised:
            parse_refresh(body)

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(raised.exception.code, "duplicate_key")

    def test_signed64_decimal_id_exact(self):
        maximum = "9223372036854775807"
        parsed = parse_refresh(json.dumps(_request(requestId=maximum)).encode())
        self.assertEqual(parsed["requestId"], maximum)

        for invalid in ("0", "01", "+1", "-1", "9223372036854775808", 1):
            with self.subTest(invalid=invalid):
                with self.assertRaises(WireError) as raised:
                    parse_refresh(json.dumps(_request(requestId=invalid)).encode())
                self.assertEqual(raised.exception.status, 400)

    def test_refresh_envelope_rejects_unknown_fields_and_token_mismatch(self):
        with self.assertRaises(WireError) as unknown:
            parse_refresh(json.dumps(_request(extra="ignored")).encode())
        self.assertEqual(unknown.exception.status, 400)

        with self.assertRaises(WireError) as mismatch:
            parse_refresh(json.dumps(_request(account="B")).encode())
        self.assertEqual(mismatch.exception.status, 400)

    def test_oversized_refresh_envelope_is_413(self):
        body = json.dumps(_request(padding="x" * (16 * 1024))).encode()

        with self.assertRaises(WireError) as raised:
            parse_refresh(body)

        self.assertEqual(raised.exception.status, 413)
        self.assertEqual(raised.exception.code, "body_too_large")


if __name__ == "__main__":
    unittest.main()
