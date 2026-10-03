#!/usr/bin/env python3
"""
Model-alias shim in front of audio.cpp's TTS server.

Why this exists
---------------
Paseo's OpenAI TTS provider hard-codes its model id to one of exactly two
values — "tts-1" or "tts-1-hd" — and validates it with a Zod enum before the
request is ever sent:

    const DEFAULT_OPENAI_TTS_MODEL = "tts-1";
    const OpenAiTtsModelSchema = z.enum(["tts-1", "tts-1-hd"]);

audio.cpp, meanwhile, serves its own id and rejects anything else:

    $ curl .../v1/audio/speech -d '{"model":"tts-1"}'
    500 unknown model id: tts-1

Neither side can be configured to agree: Paseo's enum is closed, so pointing it
at "kokoro" makes config parsing throw, and audio.cpp's id is fixed at load
time. This shim sits between them and rewrites the model id on the way through,
so Paseo can send whatever it likes and audio.cpp still gets the id it wants.

It also passes the voice through: Paseo's voice enum (alloy/echo/fable/onyx/
nova/shimmer) has no equivalent in Kokoro, which uses voice-id names like
af_heart. The voice is ignored by default so audio.cpp falls back to its
configured default_voice_preset, which is what those OpenAI voice names mean
anyway.

Run it in front of audiocpp_server; point clients at this port.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = os.environ.get("ASR_UPSTREAM", "http://127.0.0.1:8080").rstrip("/")
PORT = int(os.environ.get("PORT", "8081"))

# Voice names Paseo may send that Kokoro has no equivalent for. They are
# dropped so audio.cpp applies its default_voice_preset rather than 500ing on
# an unknown voice.
OPENAI_ONLY_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}

# Upstream id that audio.cpp accepts.
UPSTREAM_MODEL = os.environ.get("UPSTREAM_MODEL", "kokoro")


class Handler(BaseHTTPRequestHandler):
    server_version = "kokoro-alias/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("alias: " + (fmt % args) + "\n")

    def _relay(self, status: int, headers: dict, body: bytes) -> None:
        self.send_response(status)
        for key, value in headers.items():
            if key.lower() in ("content-length", "transfer-encoding", "connection"):
                continue
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _proxy(self, method: str, path: str) -> None:
        req = urllib.request.Request(UPSTREAM + path, method=method)
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                self._relay(
                    resp.status,
                    dict(resp.headers),
                    resp.read(),
                )
        except urllib.error.HTTPError as exc:
            self._relay(exc.code, dict(exc.headers), exc.read())
        except Exception as exc:  # upstream down, bad gateway is correct here
            payload = json.dumps({"error": {"message": str(exc)}}).encode()
            self._relay(502, {"Content-Type": "application/json"}, payload)

    def do_GET(self) -> None:
        self._proxy("GET", self.path)

    def do_POST(self) -> None:
        if not self.path.startswith("/v1/audio/speech"):
            self._proxy("POST", self.path)
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._proxy("POST", self.path)
            return
        raw = self.rfile.read(length)

        try:
            payload = json.loads(raw)
        except ValueError:
            # Not JSON; pass through untouched so ffmpeg/multipart paths still work.
            req = urllib.request.Request(
                UPSTREAM + self.path, data=raw, method="POST",
                headers={"Content-Type": self.headers.get("Content-Type", "application/json")},
            )
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    self._relay(resp.status, dict(resp.headers), resp.read())
            except urllib.error.HTTPError as exc:
                self._relay(exc.code, dict(exc.headers), exc.read())
            except Exception as exc:
                payload = json.dumps({"error": {"message": str(exc)}}).encode()
                self._relay(502, {"Content-Type": "application/json"}, payload)
            return

        if "model" in payload:
            payload["model"] = UPSTREAM_MODEL
        voice = payload.get("voice")
        if isinstance(voice, str) and voice in OPENAI_ONLY_VOICES:
            payload.pop("voice", None)

        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            UPSTREAM + self.path,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json",
                     "Content-Length": str(len(body))},
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                self._relay(resp.status, dict(resp.headers), resp.read())
        except urllib.error.HTTPError as exc:
            self._relay(exc.code, dict(exc.headers), exc.read())
        except Exception as exc:
            err = json.dumps({"error": {"message": str(exc)}}).encode()
            self._relay(502, {"Content-Type": "application/json"}, err)


def main() -> None:
    sys.stderr.write(
        f"kokoro-alias listening on :{PORT} -> {UPSTREAM} "
        f"(rewriting model -> {UPSTREAM_MODEL})\n"
    )
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()