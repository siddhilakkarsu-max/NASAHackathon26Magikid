"""
Publish Marswalk Planner to a Hugging Face Space (Docker SDK).

Once:   pip install huggingface_hub            (only on the machine you publish from, not in the app)
        hf auth login                          (a token with write access, from huggingface.co/settings/tokens)
Then, from the repo root:
        python deploy/huggingface/push_space.py <hf-user>/<space-name> [--private]

What it does: packages the *committed* code (git HEAD, so local experiments aren't published) with this folder's
Dockerfile and Space card (README.md), creates the Space if it doesn't exist, and uploads it; the Space then builds
and starts by itself. If ANTHROPIC_API_KEY is set in your shell it is stored as a Space secret; otherwise add it once
under the Space's Settings -> Variables and secrets. The key is never written into the uploaded files.
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
LEAVE_OUT = ["deploy", "docs", "tests", ".gitattributes"]      # not needed to run the app


def bundle(dest):
    """git HEAD's files + the Space's Dockerfile and card, in dest."""
    archive = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", "HEAD"], check=True,
                             capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive, check=True)
    for name in LEAVE_OUT:
        subprocess.run(["rm", "-rf", str(dest / name)], check=True)
    (dest / "Dockerfile").write_bytes((HERE / "Dockerfile").read_bytes())
    (dest / "README.md").write_bytes((HERE / "README.md").read_bytes())
    # never publish a key by accident
    for path in dest.rglob("*"):
        if path.is_file() and path.stat().st_size < 5_000_000 and b"sk-ant-" in path.read_bytes():
            sys.exit(f"refusing to publish: {path.relative_to(dest)} contains something that looks like an API key")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("space", help="<hf-user>/<space-name>, e.g. alice/marswalk")
    ap.add_argument("--private", action="store_true", help="only you (or your org) can open the Space")
    args = ap.parse_args()
    api = HfApi()
    sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], check=True,
                         capture_output=True, text=True).stdout.strip()
    api.create_repo(args.space, repo_type="space", space_sdk="docker", private=args.private, exist_ok=True)
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        api.add_space_secret(args.space, "ANTHROPIC_API_KEY", key)
        print("ANTHROPIC_API_KEY stored as a Space secret")
    else:
        print("No ANTHROPIC_API_KEY in this shell: add it under the Space's Settings -> Variables and secrets")
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        bundle(dest)
        api.upload_folder(folder_path=str(dest), repo_id=args.space, repo_type="space",
                          commit_message=f"deploy {sha}", delete_patterns=["*"])   # mirror: drop removed files
    user, name = args.space.split("/")
    host = f"{user}-{name}".lower().replace("_", "-").replace(".", "-")
    print(f"Uploaded {sha}. Build log and settings: https://huggingface.co/spaces/{args.space}")
    print(f"The app, once built (a few minutes): https://{host}.hf.space")


if __name__ == "__main__":
    main()
