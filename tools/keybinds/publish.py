"""Publish a controls-only update using the existing verified pack-latest assets."""
from datetime import datetime, timezone
import argparse
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.request import Request, urlopen
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[2]
REPO = "MarkZamore/Fear-Nightfall"
TAG = "pack-latest"
PRESET = "launcher/controls-preset.txt"
SOURCE_BASE = "e8c298ae7d6c446e6105078a091fb87cf4cf6e94"
MANIFEST = "pack-manifest.json"


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True).strip()


def read_asset(name, maximum):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise ValueError("Invalid asset name")
    url = f"https://github.com/{REPO}/releases/download/{TAG}/{name}?fresh={uuid4().hex}"
    with urlopen(Request(url, headers={"Cache-Control": "no-cache"}), timeout=45) as response:
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError(f"Oversized asset: {name}")
    return data


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pin(data):
    return {"sha256": sha(data), "sizeBytes": len(data)}


def encode(document):
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def zip_bytes(entries):
    out = BytesIO()
    with ZipFile(out, "w", compression=ZIP_DEFLATED) as z:
        for name, data in sorted(entries.items()):
            info = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            z.writestr(info, data, compress_type=ZIP_DEFLATED)
    return out.getvalue()


def candidate(previous, library_bytes, preset, revision):
    if (previous["schemaVersion"], previous["packId"], previous["minecraftVersion"], previous["loader"]) != (
        2, "minecraft-23", "1.20.1", {"type": "forge", "version": "47.4.8"}
    ):
        raise ValueError("Unexpected publication identity or platform")
    library = previous["library"]
    if library["name"] != f"library-{sha(library_bytes)}.zip" or any(
        library.get(k) != v for k, v in pin(library_bytes).items()
    ):
        raise ValueError("Published library archive does not match its pin")
    if library["revision"] != previous["revision"]:
        raise ValueError("Published library revision differs from the manifest")
    with ZipFile(BytesIO(library_bytes)) as z:
        names = z.namelist()
        if sorted(names) != ["library.json", "preview.jpg"] or any(x.file_size > 8 * 1024 * 1024 for x in z.infolist()):
            raise ValueError("Unexpected library members")
        card = json.loads(z.read("library.json"))
        if (card["revision"], card["id"], card["relativePath"]) != (previous["revision"], "minecraft-23", "Fear Nightfall"):
            raise ValueError("Unexpected library card")
        preview = z.read("preview.jpg")
    card["revision"] = revision
    library_data = zip_bytes({"library.json": encode(card), "preview.jpg": preview})
    library_name = f"library-{sha(library_data)}.zip"
    preset_data = zip_bytes({PRESET: preset})
    preset_name = f"r-{sha(preset_data)[:12]}-controls-preset.zip"
    previous_preset = [a for a in previous["assets"] if PRESET in a["covers"]]
    if any(a["covers"] != [PRESET] for a in previous_preset):
        raise ValueError("Preset must have its own archive")
    manifest = {
        **previous,
        "revision": revision,
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "files": sorted(
            [f for f in previous["files"] if f["path"] != PRESET] + [{"path": PRESET, **pin(preset)}],
            key=lambda f: f["path"],
        ),
        "assets": sorted(
            [a for a in previous["assets"] if PRESET not in a["covers"]]
            + [{"kind": "zipRoot", "name": preset_name, "covers": [PRESET], **pin(preset_data)}],
            key=lambda a: a["name"],
        ),
        "library": {"name": library_name, "revision": revision, **pin(library_data)},
    }
    return manifest, {library_name: library_data, preset_name: preset_data}


def verify_public(manifest, assets, preset):
    actual = json.loads(read_asset(MANIFEST, 2 * 1024 * 1024))
    if actual != manifest:
        raise ValueError("Published manifest does not equal staged manifest")
    entry, = [f for f in actual["files"] if f["path"] == PRESET]
    if entry != {"path": PRESET, **pin(preset)}:
        raise ValueError("Public preset pin differs from source")
    for name, data in assets.items():
        if read_asset(name, 8 * 1024 * 1024) != data:
            raise ValueError(f"Public bytes differ: {name}")
    print(f"Verified {actual['revision']} {PRESET} SHA256={entry['sha256']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    revision = git("rev-parse", "HEAD")
    changed = git("diff", "--name-only", SOURCE_BASE, revision).splitlines()
    allowed = {".gitattributes", "README.md", PRESET, ".github/workflows/publish.yml"}
    if any(rel not in allowed and not rel.startswith("tools/keybinds/") for rel in changed):
        raise ValueError("A controls-only publisher cannot ship unrelated changes")
    preset = subprocess.check_output(["git", "-C", str(ROOT), "show", f"HEAD:{PRESET}"])
    if preset != (ROOT / PRESET).read_bytes():
        raise ValueError("Working preset differs from committed source")
    raw = read_asset(MANIFEST, 2 * 1024 * 1024)
    previous = json.loads(raw)
    public = json.loads(gh("api", f"repos/{REPO}/releases/tags/{TAG}"))
    remote = {a["name"]: a for a in public["assets"]}
    for asset in [*previous["assets"], previous["library"]]:
        row = remote[asset["name"]]
        if row["size"] != asset["sizeBytes"] or row.get("digest") != "sha256:" + asset["sha256"]:
            raise ValueError(f"Existing GitHub asset metadata differs: {asset['name']}")
    library = read_asset(previous["library"]["name"], 8 * 1024 * 1024)
    manifest, assets = candidate(previous, library, preset, revision)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, data in assets.items():
        (args.output / name).write_bytes(data)
    staged = args.output / MANIFEST
    staged.write_bytes(encode(manifest))
    if args.publish:
        if os.environ.get("GITHUB_REPOSITORY") != REPO:
            raise ValueError("Publication runs in the Fear Nightfall GitHub workflow")
        for name, data in assets.items():
            if name not in remote:
                gh("release", "upload", TAG, str(args.output / name), "--repo", REPO)
            if read_asset(name, 8 * 1024 * 1024) != data:
                raise ValueError(f"Changed asset verification failed: {name}")
        if read_asset(MANIFEST, 2 * 1024 * 1024) != raw:
            raise ValueError("Published manifest changed while preparing the update")
        gh("release", "upload", TAG, str(staged), "--clobber", "--repo", REPO)
        verify_public(manifest, assets, preset)
    else:
        print(f"Staged {revision}, {len(manifest['files'])} files, preset SHA256={sha(preset)}")


if __name__ == "__main__":
    main()
