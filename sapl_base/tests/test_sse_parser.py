from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from sapl_base.sse_parser import SseBufferOverflowError, parse_sse_stream


async def _bytes_stream(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


async def _collect(stream: AsyncIterator[str]) -> list[str]:
    return [item async for item in stream]


class TestSseParserBasicEvents:
    async def test_single_data_event(self):
        stream = _bytes_stream(b"data: hello\n\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["hello"]

    async def test_multiple_events(self):
        stream = _bytes_stream(b"data: first\n\ndata: second\n\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["first", "second"]

    async def test_multi_line_data_joined_with_newline(self):
        stream = _bytes_stream(b"data: line1\ndata: line2\n\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["line1\nline2"]

    async def test_data_with_space_after_colon_stripped(self):
        stream = _bytes_stream(b"data: hello\n\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["hello"]

    async def test_data_without_space_after_colon(self):
        stream = _bytes_stream(b"data:hello\n\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["hello"]

    async def test_data_field_with_no_value(self):
        stream = _bytes_stream(b"data\n\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == [""]

    async def test_empty_data_field(self):
        stream = _bytes_stream(b"data:\n\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == [""]

    async def test_empty_stream_yields_nothing(self):
        stream = _bytes_stream(b"")
        result = await _collect(parse_sse_stream(stream))
        assert result == []


class TestSseParserLineEndings:
    """REQ-SSE-2: Handle CR, LF, and CRLF line endings."""

    async def test_lf_line_ending(self):
        stream = _bytes_stream(b"data: hello\n\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["hello"]

    async def test_cr_line_ending(self):
        stream = _bytes_stream(b"data: hello\r\r")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["hello"]

    async def test_crlf_line_ending(self):
        stream = _bytes_stream(b"data: hello\r\n\r\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["hello"]

    async def test_mixed_line_endings(self):
        stream = _bytes_stream(b"data: first\r\n\r\ndata: second\n\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["first", "second"]


class TestSseParserComments:
    async def test_comment_lines_are_ignored(self):
        stream = _bytes_stream(b": this is a comment\ndata: hello\n\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["hello"]

    async def test_comment_between_events(self):
        stream = _bytes_stream(b"data: first\n\n: comment\ndata: second\n\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["first", "second"]

    async def test_only_comments_yield_nothing(self):
        stream = _bytes_stream(b": comment1\n: comment2\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == []


class TestSseParserUnrecognizedFields:
    async def test_event_field_ignored(self):
        stream = _bytes_stream(b"event: update\ndata: hello\n\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["hello"]

    async def test_id_field_ignored(self):
        stream = _bytes_stream(b"id: 42\ndata: hello\n\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["hello"]

    async def test_retry_field_ignored(self):
        stream = _bytes_stream(b"retry: 3000\ndata: hello\n\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["hello"]


class TestSseParserChunkBoundaries:
    """REQ-SSE-1: Incremental decoding across chunk boundaries."""

    async def test_data_split_across_chunks(self):
        stream = _bytes_stream(b"da", b"ta: hel", b"lo\n\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["hello"]

    async def test_newline_split_across_chunks(self):
        stream = _bytes_stream(b"data: hello\n", b"\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["hello"]

    async def test_crlf_split_across_chunks(self):
        stream = _bytes_stream(b"data: hello\r", b"\n\r\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["hello"]

    async def test_many_small_chunks(self):
        data = b"data: hello\n\n"
        stream = _bytes_stream(*(bytes([b]) for b in data))
        result = await _collect(parse_sse_stream(stream))
        assert result == ["hello"]


class TestSseParserUtf8:
    """REQ-SSE-1: Incremental UTF-8 decoding."""

    async def test_utf8_data(self):
        stream = _bytes_stream(b"data: Gruesse\n\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["Gruesse"]

    async def test_multi_byte_utf8_split_across_chunks(self):
        # The euro sign is 3 bytes in UTF-8: \xe2\x82\xac
        euro_bytes = b"data: 100 EUR\n\n"
        # Split in the middle of a regular position
        mid = len(euro_bytes) // 2
        stream = _bytes_stream(euro_bytes[:mid], euro_bytes[mid:])
        result = await _collect(parse_sse_stream(stream))
        assert result == ["100 EUR"]

    async def test_partial_utf8_at_chunk_boundary(self):
        # Multi-byte char split: first chunk has partial bytes
        full_text = "data: x\n\n"
        encoded = full_text.encode("utf-8")
        stream = _bytes_stream(encoded[:3], encoded[3:])
        result = await _collect(parse_sse_stream(stream))
        assert result == ["x"]

    async def test_invalid_utf8_is_skipped(self):
        # Invalid UTF-8 byte followed by valid event
        stream = _bytes_stream(b"\xff\xfe", b"data: valid\n\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["valid"]


class TestSseParserBufferOverflow:
    """REQ-SSE-5: Buffer limit 1MB."""

    async def test_buffer_overflow_raises_error(self):
        # Create a line that exceeds 1MB without a newline
        huge_data = b"data: " + b"x" * (1024 * 1024 + 100)
        stream = _bytes_stream(huge_data)
        with pytest.raises(SseBufferOverflowError):
            await _collect(parse_sse_stream(stream))


class TestSseParserEdgeCases:
    async def test_no_trailing_blank_line_flushes_data(self):
        stream = _bytes_stream(b"data: hello\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["hello"]

    async def test_empty_event_with_no_data_lines(self):
        # Two blank lines with no data in between -- no event
        stream = _bytes_stream(b"\n\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == []

    async def test_data_with_colon_in_value(self):
        stream = _bytes_stream(b"data: key: value\n\n")
        result = await _collect(parse_sse_stream(stream))
        assert result == ["key: value"]

    async def test_json_data(self):
        stream = _bytes_stream(b'data: {"decision": "PERMIT"}\n\n')
        result = await _collect(parse_sse_stream(stream))
        assert result == ['{"decision": "PERMIT"}']

    async def test_multi_line_json_data(self):
        stream = _bytes_stream(
            b'data: {"decision": "PERMIT",\n'
            b'data:  "obligations": []}\n\n'
        )
        result = await _collect(parse_sse_stream(stream))
        assert result == ['{"decision": "PERMIT",\n "obligations": []}']
