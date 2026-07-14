"""Push space-vars.env to the HF Space's Variables so the deployed config always
matches what's in git — see space-vars.env's header comment for why this exists.

Usage:
    uv run scripts/sync_space_vars.py            # push every key in space-vars.env
    uv run scripts/sync_space_vars.py --dry-run   # show what would change, push nothing
"""
import os
import sys
from pathlib import Path

# httpx crashes on socks:// proxy scheme — same workaround as run_evaluation.py.
_PROXY_VARS = ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
_saved_proxy = {k: os.environ.pop(k) for k in _PROXY_VARS if k in os.environ}

import httpx

SPACE_ID = "Leminds/biassemble-engine"
VARS_URL = f"https://huggingface.co/api/spaces/{SPACE_ID}/variables"
ENV_FILE = Path(__file__).parent.parent / "space-vars.env"


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def hf_token() -> str:
    token_path = Path.home() / ".cache" / "huggingface" / "token"
    token = os.environ.get("HF_TOKEN") or token_path.read_text().strip()
    if not token:
        raise RuntimeError(f"No HF token found (checked $HF_TOKEN and {token_path})")
    return token


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    desired = load_env_file(ENV_FILE)
    headers = {"Authorization": f"Bearer {hf_token()}"}

    current = httpx.get(VARS_URL, headers=headers).json()
    changed = {k: v for k, v in desired.items() if current.get(k, {}).get("value") != v}

    if not changed:
        print("Space Variables already match space-vars.env — nothing to do.")
        return

    for key, value in changed.items():
        old = current.get(key, {}).get("value", "<unset>")
        print(f"{key}: {old!r} -> {value!r}")

    if dry_run:
        print(f"\n--dry-run: {len(changed)} variable(s) would be pushed, none applied.")
        return

    for key, value in changed.items():
        resp = httpx.post(VARS_URL, headers=headers, json={"key": key, "value": value})
        resp.raise_for_status()
    print(f"\nPushed {len(changed)} variable(s). HF will restart the Space automatically.")


if __name__ == "__main__":
    main()
    os.environ.update(_saved_proxy)
