"""Unit tests for the newline-delimited JSON framing helpers (M3-T2)."""
from __future__ import annotations

import unittest

from companion_app.net.framing import encode_line, read_line


class EncodeLineTests(unittest.TestCase):
    def test_compact_json_with_newline(self) -> None:
        result = encode_line({"type": "hello"})
        self.assertEqual(result, b'{"type":"hello"}\n')

    def test_spaced_keys_are_compact(self) -> None:
        result = encode_line({"auth": "pw", "type": "hello"})
        self.assertIn(b'"auth":"pw"', result)
        self.assertIn(b'"type":"hello"', result)

    def test_returns_bytes(self) -> None:
        result = encode_line({"a": 1})
        self.assertIsInstance(result, bytes)

    def test_ends_with_newline(self) -> None:
        result = encode_line({"a": 1})
        self.assertTrue(result.endswith(b"\n"))


class ReadLineTests(unittest.TestCase):
    def test_single_object_roundtrip(self) -> None:
        buf = bytearray(b'{"type":"hello"}\n')
        obj, rem = read_line(buf)
        self.assertEqual(obj, {"type": "hello"})
        self.assertEqual(rem, bytearray())

    def test_partial_line_returns_none(self) -> None:
        buf = bytearray(b'{"type":')
        obj, rem = read_line(buf)
        self.assertIsNone(obj)
        self.assertEqual(rem, bytearray(b'{"type":'))

    def test_multiple_lines_returns_first(self) -> None:
        buf = bytearray(b'{"a":1}\n{"b":2}\n')
        obj, rem = read_line(buf)
        self.assertEqual(obj, {"a": 1})
        self.assertEqual(rem, bytearray(b'{"b":2}\n'))

    def test_malformed_json_returns_none_and_advances(self) -> None:
        buf = bytearray(b"not-json\n")
        obj, rem = read_line(buf)
        self.assertIsNone(obj)
        self.assertEqual(rem, bytearray())

    def test_empty_line_returns_none(self) -> None:
        buf = bytearray(b"\n")
        obj, rem = read_line(buf)
        self.assertIsNone(obj)
        self.assertEqual(rem, bytearray())

    def test_non_dict_json_returns_none(self) -> None:
        buf = bytearray(b'[1,2,3]\n')
        obj, rem = read_line(buf)
        self.assertIsNone(obj)
        self.assertEqual(rem, bytearray())

    def test_string_json_returns_none(self) -> None:
        buf = bytearray(b'"hello"\n')
        obj, rem = read_line(buf)
        self.assertIsNone(obj)
        self.assertEqual(rem, bytearray())

    def test_preserves_buffer_on_no_newline(self) -> None:
        buf = bytearray(b'incomplete')
        obj, rem = read_line(buf)
        self.assertIsNone(obj)
        self.assertEqual(rem, bytearray(b'incomplete'))


if __name__ == "__main__":
    unittest.main()
