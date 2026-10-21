"""Explicit opt-in live LLM backend smoke test using synthetic content only."""

from __future__ import annotations

import argparse
import json

from pdf2audiobook.config import Settings
from pdf2audiobook.llm import create_provider


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=["ollama", "llama-server", "openai"])
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", help="Local provider endpoint override")
    parser.add_argument("--allow-remote-content", action="store_true")
    parser.add_argument("--execute", action="store_true", help="Explicitly allow real requests")
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error("Live network requests require --execute")
    if args.provider == "openai" and not args.allow_remote_content:
        parser.error("OpenAI requires --allow-remote-content in addition to --execute")
    if args.provider == "openai" and args.base_url:
        parser.error("OpenAI endpoint cannot be overridden")

    settings = Settings()
    settings.llm.provider = args.provider
    settings.llm.allow_remote_content = args.allow_remote_content
    chosen = getattr(settings.llm, args.provider.replace("-", "_"))
    chosen.model = args.model
    if args.base_url:
        chosen.base_url = args.base_url
    with create_provider(settings) as provider:
        # Deliberately avoid sending any PDF data, filenames or user documents.
        result = provider.complete_json(
            instructions='Return only the JSON object {"ok":true}.',
            document_text="Synthetic smoke-test fixture; no user or book content.",
        )
        if not isinstance(result, dict) or result.get("ok") is not True:
            print(
                json.dumps({"ok": False, "provider": args.provider, "error": "unexpected_schema"})
            )
            return 1
        print(
            json.dumps(
                {
                    "ok": True,
                    "provider": args.provider,
                    "model": args.model,
                    "reported_tokens": provider.last_usage,
                }
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(run())
