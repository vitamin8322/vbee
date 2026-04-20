#!/usr/bin/env python3
import argparse
import json
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

VBEE_BASE = "https://vbee.vn"
SYNTHESIS_URL = f"{VBEE_BASE}/api/v1/synthesis"
REQUESTS_URL = (
    f"{VBEE_BASE}/api/v2/requests?limit=5"
    "&fields=id,title,characters,credits,createdAt,progress,status,voice,audioType,audioLink,retentionPeriod,processingAt,endedAt"
    "&sort=createdAt_desc"
)
COLLECT_URL = "https://www.google-analytics.com/g/collect?v=2&tid=G-YJ04B3CMSP&en=generate_audio"
AUDIO_URL_TEMPLATE = f"{VBEE_BASE}/api/v1/requests/{{request_id}}/audio"
UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
)


def http_request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    data: Optional[bytes] = None,
    timeout: int = 30,
) -> Tuple[int, bytes]:
    req = Request(url=url, method=method, headers=headers or {}, data=data)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read()
    except HTTPError as err:
        body = err.read() if hasattr(err, "read") else b""
        return err.code, body
    except URLError as err:
        raise RuntimeError(f"Network error: {err}") from err


def parse_json(raw: bytes) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}


def load_tokens(path: Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"Token file not found: {path}")

    tokens: List[str] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        token = line.strip()
        if not token or token.startswith("#"):
            continue
        if token.lower().startswith("authorization:"):
            token = token.split(":", 1)[1].strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        tokens.append(token)
    return tokens


def split_sentences(text: str) -> List[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?…])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def extract_uuid(obj: Any) -> Optional[str]:
    if isinstance(obj, str):
        m = UUID_RE.search(obj)
        return m.group(0) if m else None
    if isinstance(obj, dict):
        for key in ("id", "requestId", "request_id", "_id"):
            v = obj.get(key)
            if isinstance(v, str):
                try:
                    return str(uuid.UUID(v))
                except ValueError:
                    pass
        for v in obj.values():
            maybe = extract_uuid(v)
            if maybe:
                return maybe
        return None
    if isinstance(obj, list):
        for item in obj:
            maybe = extract_uuid(item)
            if maybe:
                return maybe
        return None
    return None


def extract_first_request_id(requests_data: Any) -> Optional[str]:
    if isinstance(requests_data, dict):
        candidates = []
        for key in ("data", "items", "results", "requests"):
            val = requests_data.get(key)
            if isinstance(val, list):
                candidates.extend(val)
        if not candidates and isinstance(requests_data.get("id"), str):
            candidates = [requests_data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            rid = item.get("id")
            if isinstance(rid, str):
                try:
                    return str(uuid.UUID(rid))
                except ValueError:
                    continue
    return extract_uuid(requests_data)


def extract_request_ids_from_requests(requests_data: Any) -> List[str]:
    ids: List[str] = []
    if isinstance(requests_data, dict):
        candidates = []
        for key in ("data", "items", "results", "requests"):
            val = requests_data.get(key)
            if isinstance(val, list):
                candidates.extend(val)
        if not candidates and isinstance(requests_data.get("id"), str):
            candidates = [requests_data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            rid = item.get("id")
            if isinstance(rid, str):
                try:
                    ids.append(str(uuid.UUID(rid)))
                except ValueError:
                    continue
    return ids


def extract_audio_link(audio_data: Any) -> Optional[str]:
    if isinstance(audio_data, str):
        if audio_data.startswith("http"):
            return audio_data
        return None
    if isinstance(audio_data, dict):
        for key in ("audioLink", "audioUrl", "url", "signedUrl", "link", "data"):
            val = audio_data.get(key)
            if isinstance(val, str) and val.startswith("http"):
                return val
            if isinstance(val, dict):
                nested = extract_audio_link(val)
                if nested:
                    return nested
        for val in audio_data.values():
            nested = extract_audio_link(val)
            if nested:
                return nested
        return None
    if isinstance(audio_data, list):
        for item in audio_data:
            nested = extract_audio_link(item)
            if nested:
                return nested
        return None
    return None


def build_headers(token: str, content_type_json: bool = False) -> Dict[str, str]:
    headers = {
        "accept": "application/json, text/plain, */*",
        "authorization": f"Bearer {token}",
        "origin": "https://studio.vbee.vn",
        "referer": "https://studio.vbee.vn/",
        "user-agent": "Mozilla/5.0",
    }
    if content_type_json:
        headers["content-type"] = "application/json"
    return headers


def generate_one(
    sentence: str,
    token: str,
    voice_code: str,
    speed: float,
    audio_type: str,
    bitrate: int,
    poll_attempts: int,
    poll_interval: float,
) -> Tuple[bool, Optional[bytes], str]:
    payload = {
        "audioType": audio_type,
        "bitrate": bitrate,
        "backgroundMusic": {"volume": 80},
        "text": sentence,
        "voiceCode": voice_code,
        "speed": speed,
        "clientPause": {
            "majorBreak": 0.3,
            "mediumBreak": 0.25,
            "paragraphBreak": 0.6,
            "sentenceBreak": 0.45,
        },
    }

    # 1) requests snapshot before synthesis
    before_ids = set()
    code, raw = http_request("GET", REQUESTS_URL, headers=build_headers(token))
    if 200 <= code < 300:
        before_data = parse_json(raw)
        before_ids = set(extract_request_ids_from_requests(before_data))

    # 2) synthesis
    code, raw = http_request(
        "POST",
        SYNTHESIS_URL,
        headers=build_headers(token, content_type_json=True),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    if code < 200 or code >= 300:
        return False, None, f"synthesis failed ({code})"

    synthesis_data = parse_json(raw)
    req_id = extract_uuid(synthesis_data)

    # 3) requests: if synthesis body has no request id, find newly created id
    if not req_id:
        for _ in range(max(3, poll_attempts // 2)):
            code, raw = http_request("GET", REQUESTS_URL, headers=build_headers(token))
            if 200 <= code < 300:
                requests_data = parse_json(raw)
                current_ids = extract_request_ids_from_requests(requests_data)
                new_ids = [rid for rid in current_ids if rid not in before_ids]
                if new_ids:
                    req_id = new_ids[0]
                    break
            time.sleep(poll_interval)

    if not req_id:
        return False, None, "cannot find new request id (avoid reusing old audio)"

    # 4) collect (best effort)
    try:
        http_request("POST", COLLECT_URL, headers={"accept": "*/*"}, data=b"")
    except Exception:
        pass

    # 5) audio polling
    audio_link: Optional[str] = None
    audio_api_url = AUDIO_URL_TEMPLATE.format(request_id=quote(req_id))

    for _ in range(poll_attempts):
        code, raw = http_request("GET", audio_api_url, headers=build_headers(token))
        if code >= 200 and code < 300:
            audio_data = parse_json(raw)
            audio_link = extract_audio_link(audio_data)
            if audio_link:
                break
        time.sleep(poll_interval)

    if not audio_link:
        return False, None, "audio link not ready"

    # download audio
    code, audio_bytes = http_request("GET", audio_link, headers={"user-agent": "Mozilla/5.0"}, timeout=60)
    if code < 200 or code >= 300 or not audio_bytes:
        return False, None, f"download failed ({code})"

    return True, audio_bytes, "ok"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate mp3 files from truyen.txt sentences via Vbee API using multiple tokens."
    )
    parser.add_argument("--input", default="truyen.txt", help="Input text file")
    parser.add_argument("--tokens", default="token.txt", help="Token file, one token per line")
    parser.add_argument("--outdir", default="audio_output", help="Output directory for mp3 files")
    parser.add_argument("--voice", default="hn_female_ngochuyen_full_48k-fhg", help="Vbee voiceCode")
    parser.add_argument("--speed", type=float, default=1.1, help="Speech speed")
    parser.add_argument("--audio-type", default="mp3", choices=["mp3", "wav"], help="Audio type")
    parser.add_argument("--bitrate", type=int, default=128, help="Bitrate (for mp3)")
    parser.add_argument("--poll-attempts", type=int, default=20, help="Audio polling attempts")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Seconds between polls")
    parser.add_argument("--metadata", default="metadata.csv", help="Metadata filename written inside outdir")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip sentence N if output file N.mp3 already exists in outdir",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    token_path = Path(args.tokens)
    outdir = Path(args.outdir)

    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return 1

    tokens = load_tokens(token_path)
    if not tokens:
        print(f"No token found in {token_path}. Add one token per line.")
        return 1

    raw_text = input_path.read_text(encoding="utf-8", errors="ignore")
    sentences = split_sentences(raw_text)
    if not sentences:
        print("No sentence found in input file.")
        return 1

    outdir.mkdir(parents=True, exist_ok=True)

    print(f"Total sentences: {len(sentences)}")
    print(f"Total tokens: {len(tokens)}")

    metadata_path = outdir / args.metadata
    metadata_lines = [f"{i}.mp3|{re.sub(r'\\s+', ' ', sentence).strip()}" for i, sentence in enumerate(sentences, start=1)]
    metadata_path.write_text("\n".join(metadata_lines) + "\n", encoding="utf-8")
    print(f"Metadata written: {metadata_path}")

    generated = 0
    failed = 0
    skipped = 0

    for i, sentence in enumerate(sentences, start=1):
        output_file = outdir / f"{i}.mp3"
        if args.resume and output_file.exists():
            skipped += 1
            print(f"[{i}/{len(sentences)}] skipped {output_file.name} (exists, --resume)")
            continue

        ok = False
        last_msg = "unknown error"

        start_idx = (i - 1) % len(tokens)
        token_order = list(range(start_idx, len(tokens))) + list(range(0, start_idx))

        for token_idx in token_order:
            token = tokens[token_idx]
            success, audio_bytes, message = generate_one(
                sentence=sentence,
                token=token,
                voice_code=args.voice,
                speed=args.speed,
                audio_type=args.audio_type,
                bitrate=args.bitrate,
                poll_attempts=args.poll_attempts,
                poll_interval=args.poll_interval,
            )
            if success and audio_bytes:
                output_file.write_bytes(audio_bytes)
                print(f"[{i}/{len(sentences)}] saved {output_file.name} (token #{token_idx + 1})")
                generated += 1
                ok = True
                break
            last_msg = f"token #{token_idx + 1}: {message}"

        if not ok:
            failed += 1
            print(f"[{i}/{len(sentences)}] failed: {last_msg}")

    print(f"Done. generated={generated}, skipped={skipped}, failed={failed}, output={outdir}")
    return 0 if generated > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
