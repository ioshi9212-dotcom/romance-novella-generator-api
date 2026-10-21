"""Safe verbatim TXT transfer from GPT Actions and recovery of placeholder RAW entries."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException

MAX_RAW_BYTES = 5 * 1024 * 1024
_RAW_HEADER = re.compile(r"(?m)^===== RAW ([A-Za-z0-9_-]+) ([0-9a-f]{64}) =====\n")


def reject_placeholder(text: str) -> None:
    if text.strip().upper() == "PLACEHOLDER":
        raise HTTPException(422, "RAW_PLACEHOLDER_FORBIDDEN: supply the original file, not a stand-in")


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPException(422, "OpenAI file URL redirect refused; provide a direct file reference")


def fetch_openai_file(refs: list[object]) -> tuple[str, str, int, str]:
    """Return exact UTF-8 text + file name, byte count and SHA-256. Never trust arbitrary URLs."""
    if len(refs) != 1 or not isinstance(refs[0], dict):
        raise HTTPException(422, "Exactly one attached TXT file is required")
    ref = refs[0]
    url = ref.get("download_link")
    if not isinstance(url, str):
        raise HTTPException(422, "GPT Actions did not supply the file download_link")
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != "files.oaiusercontent.com" or parts.username or parts.password or parts.port not in (None, 443):
        raise HTTPException(422, "Unsupported file download host")
    name = ref.get("name", "source.txt")
    if not isinstance(name, str) or not name.lower().endswith(".txt"):
        raise HTTPException(422, "Upload a UTF-8 .txt source, not a converted summary")
    try:
        opener = urllib.request.build_opener(_NoRedirects())
        with opener.open(urllib.request.Request(url, headers={"User-Agent": "Novella-RAW-Intake/1"}), timeout=12) as response:
            payload = response.read(MAX_RAW_BYTES + 1)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "Unable to fetch attached file before the download URL expired") from exc
    if not payload or len(payload) > MAX_RAW_BYTES:
        raise HTTPException(422, "Attached source is empty or larger than 5 MiB")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "Source must be UTF-8; original bytes were not altered") from exc
    reject_placeholder(text)
    return text, name, len(payload), hashlib.sha256(payload).hexdigest()


def _atomic_bytes(path: Path, payload: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".raw_repair_", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _source_sections(raw: str):
    """Parse envelope only; retain untouched non-target sources byte-for-byte."""
    matches = list(_RAW_HEADER.finditer(raw))
    result = []
    for match in matches:
        event_id, old_digest = match.groups()
        tail = "\n===== END RAW " + event_id + " =====\n"
        end_start = raw.find(tail, match.end())
        if end_start < 0:
            raise HTTPException(409, "Malformed RAW source boundary; manual recovery required")
        middle = raw[match.end():end_start]
        prefix = ""
        while middle.startswith(("Файл: ", "Вопрос: ")):
            head, sep, remainder = middle.partition("\n")
            if not sep:
                raise HTTPException(409, "Malformed RAW source metadata")
            prefix += head + "\n"
            middle = remainder
        result.append((event_id, old_digest, match.start(), end_start + len(tail), prefix, middle))
    return result


def placeholder_events(raw: str) -> list[str]:
    return [event for event, _digest, _start, _end, _prefix, body in _source_sections(raw) if body.strip().upper() == "PLACEHOLDER"]


def repair_placeholder(folder: Path, meta: dict, *, event_id: str | None, text: str,
                       byte_count: int, sha256: str, atomic_json, source_digest, RawPart) -> dict:
    """Only change an actual PLACEHOLDER, never any valid RAW entry or played story."""
    if meta.get("этап") not in ("сбор", "вопросы", "готово_к_записи", "запись_и_сверка") or int(meta.get("последний_ход", 0)):
        raise HTTPException(409, "RAW repair is only allowed before verification and gameplay")
    path = folder / "raw.txt"
    if not path.is_file():
        raise HTTPException(409, "No RAW to repair")
    raw = path.read_bytes().decode("utf-8")
    sections = _source_sections(raw)
    if event_id is None:
        candidates = [e for e, _d, _a, _b, _p, body in sections if body.strip().upper() == "PLACEHOLDER"]
        if len(candidates) == 1:
            event_id = candidates[0]
        elif not candidates:
            # An interrupted client may repeat the identical successful upload.
            # It is safe only if exactly one stored source matches every byte.
            matching = [e for e, _d, _a, _b, _p, body in sections
                        if hashlib.sha256(body.encode("utf-8")).hexdigest() == sha256]
            if len(matching) == 1:
                event_id = matching[0]
            else:
                raise HTTPException(409, {"code": "SELECT_PLACEHOLDER_EVENT", "event_ids": []})
        else:
            raise HTTPException(409, {"code": "SELECT_PLACEHOLDER_EVENT", "event_ids": candidates})
    selected = [row for row in sections if row[0] == event_id]
    if len(selected) != 1:
        raise HTTPException(409, "Unknown or duplicate RAW event; refusing repair")
    event, original_digest, start, end, prefix, body = selected[0]
    question, filename = None, None
    for line in prefix.splitlines():
        if line.startswith("Вопрос: "):
            question = json.loads(line.removeprefix("Вопрос: "))
        if line.startswith("Файл: "):
            filename = json.loads(line.removeprefix("Файл: "))
    new_digest = source_digest(RawPart(event_id=event, text=text, question=question, file_name=filename))
    receipts = meta.setdefault("_raw_receipts", {})
    if body.strip().upper() != "PLACEHOLDER":
        if original_digest == new_digest and hashlib.sha256(body.encode("utf-8")).hexdigest() == sha256:
            # Complete a previously interrupted two-file repair, if necessary.
            if receipts.get(event) != new_digest:
                receipts[event] = new_digest
                if event == "initial":
                    meta["_initial_text_digest"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
                atomic_json(folder / "сессия.json", meta)
            return {"status": "already_restored", "event_id": event, "bytes": byte_count, "sha256": sha256}
        raise HTTPException(409, "RAW source is not a placeholder; valid sources cannot be overwritten")
    if receipts.get(event) != original_digest:
        raise HTTPException(409, "RAW source receipt differs from disk; manual recovery required")
    marker = f"===== RAW {event} {new_digest} =====\n"
    block = "\n" + marker + prefix + text + f"\n===== END RAW {event} =====\n"
    # The prior append_source format has a leading newline; preserve every other source.
    leading = start - 1 if start > 0 and raw[start - 1] == "\n" else start
    updated = raw[:leading] + block + raw[end:]
    _atomic_bytes(path, updated.encode("utf-8"))
    receipts[event] = new_digest
    if event == "initial":
        meta["_initial_text_digest"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    meta["_raw_repair_requires_review"] = True
    atomic_json(folder / "сессия.json", meta)
    return {"status": "restored_review_required", "event_id": event, "bytes": byte_count, "sha256": sha256}
