"""L4 smoke: print model names or cited synthetic-input results, never a key."""
import argparse
import json

from app.contracts import PublicScamReportsArgs
from app.integrations.gemini import available_models, grounded_search
from app.tools.public_reports import build_gemini_input


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-models", action="store_true")
    args = parser.parse_args()
    try:
        if args.list_models:
            print(json.dumps(available_models(), indent=2))
            return 0
        query = build_gemini_input(PublicScamReportsArgs(
            claimed_brand="Capital One", scam_category="bank_impersonation", link_domain="capone-verify-alert.com",
        ))
        result = grounded_search(query)
        print(result.model_dump_json(indent=2))
        return 0 if result.reports_found and all(report.url.startswith("https://") for report in result.reports) else 2
    except Exception as exc:
        print(f"Gemini smoke could not complete ({type(exc).__name__}); check key, model and replay mode.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
