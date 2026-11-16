"""Publish pack-owned controls and quest book data over verified release assets."""
from datetime import datetime, timezone
import argparse
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.request import Request, urlopen
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/questbook"))
import localize as questbook

REPO = "MarkZamore/Fear-Nightfall"
TAG = "pack-latest"
PRESET = "launcher/controls-preset.txt"
MANIFEST = "pack-manifest.json"
WARNING_ID = "fear_nightfall_multiplayer_warning"
WARNING_JAR = "fear-nightfall-multiplayer-warning-1.0.0.jar"
WARNING = "mods/" + WARNING_JAR
WARNING_SHA = "9a44c173b3f8e7c75e6ecb7aef29162b08959b6e48e3087c1c92ac54c366454f"


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
    descriptor = json.loads((ROOT / "portable-pack.json").read_bytes())
    if (previous["schemaVersion"], previous["packId"], previous["minecraftVersion"], previous["loader"]) != (
        2, "minecraft-23", descriptor["minecraftVersion"], descriptor["loader"]
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
    prior_helper = any(row["id"] == WARNING_ID for row in card["mods"])
    if prior_helper != any(row["path"] == WARNING for row in previous["files"]):
        raise ValueError("Multiplayer helper and library card disagree")
    if not prior_helper:
        card["mods"].append({
            "id": WARNING_ID, "isLibrary": True, "isLoadedMod": True,
            "name": "Fear Nightfall Multiplayer Warning Preference", "parentId": None,
            "version": "1.0.0", "websiteAvailable": True,
            "websiteUrl": "https://github.com/MarkZamore/Fear-Nightfall#предупреждение-сетевой-игры",
        })
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
        "modCount": previous["modCount"] + (not prior_helper),
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


def merge_questbook(manifest, new_assets, outputs, state, read, previous_outputs):
    files = {row["path"]: row for row in manifest["files"]}
    owners = {path: asset for asset in manifest["assets"] for path in asset["covers"]}
    for path, expected in state["inputs"].items():
        row = files.get(path)
        if row is None or questbook.row_pin(row) not in (expected, previous_outputs.get(path)):
            raise ValueError(f"Release input differs from the checked quest source: {path}")

    affected = {}
    for path in outputs:
        if path in owners:
            original = owners[path]
        elif path == questbook.RESOURCES and path not in files:
            original = owners[next(p for p in outputs if p.startswith(questbook.QUEST))]
        else:
            raise ValueError(f"Missing payload for {path}")
        if original["kind"] != "zipRoot":
            raise ValueError(f"Expected a root ZIP for {path}")
        affected.setdefault(original["name"], (original, {}))[1][path] = outputs[path]

    replaced = set(affected)
    for name, (original, changes) in affected.items():
        if all(path in files and questbook.row_pin(files[path]) == pin(data) for path, data in changes.items()):
            replaced.remove(name)
            continue
        body = read(name, original["sizeBytes"])
        if pin(body) != questbook.row_pin(original):
            raise ValueError(f"Base archive does not match its pin: {name}")
        with ZipFile(BytesIO(body)) as archive:
            if sorted(archive.namelist()) != sorted(original["covers"]):
                raise ValueError(f"Unexpected ZIP members: {name}")
            entries = {}
            for member in archive.infolist():
                row = files[member.filename]
                if member.file_size != row["sizeBytes"]:
                    raise ValueError(f"Unexpected ZIP member size: {member.filename}")
                data = archive.read(member)
                if pin(data) != questbook.row_pin(row):
                    raise ValueError(f"Unexpected ZIP member hash: {member.filename}")
                entries[member.filename] = data
        entries.update(changes)
        payload = zip_bytes(entries)
        label = "config" if any(rel.startswith("config/") for rel in changes) else "launcher"
        new_name = f"r-{sha(payload)[:12]}-{label}.zip"
        manifest["assets"].append({"kind": "zipRoot", "name": new_name, "covers": sorted(entries), **pin(payload)})
        new_assets[new_name] = payload
    for path, data in outputs.items():
        files[path] = {"path": path, **pin(data)}
    manifest["files"] = sorted(files.values(), key=lambda row: row["path"])
    manifest["assets"] = sorted(
        (asset for asset in manifest["assets"] if asset["name"] not in replaced),
        key=lambda row: row["name"],
    )


def merge_warning(manifest, assets):
    if (manifest["minecraftVersion"], manifest["loader"]) != (
        "1.20.1", {"type": "forge", "version": "47.4.8"}
    ):
        raise ValueError("Review the multiplayer preference hook for the new author runtime")
    warning = (ROOT / "tools/multiplayer-warning" / WARNING_JAR).read_bytes()
    if sha(warning) != WARNING_SHA:
        raise ValueError("Multiplayer preference helper differs from its pin")
    existing = [row for row in manifest["files"] if row["path"] == WARNING]
    if existing:
        if existing != [{"path": WARNING, **pin(warning)}]:
            raise ValueError("Conflicting multiplayer helper in the base release")
    else:
        name = f"c-{WARNING_SHA[:12]}-{WARNING_JAR}"
        assets[name] = warning
        manifest["assets"].append({"kind": "jar", "name": name, "covers": [WARNING], **pin(warning)})
        manifest["files"].append({"path": WARNING, **pin(warning)})
        manifest["assets"].sort(key=lambda row: row["name"])
        manifest["files"].sort(key=lambda row: row["path"])
    verify_warning(manifest, warning)


def verify_warning(manifest, warning):
    files = [row for row in manifest["files"] if row["path"] == WARNING]
    owners = [row for row in manifest["assets"] if WARNING in row["covers"]]
    if files != [{"path": WARNING, **pin(warning)}] or len(owners) != 1:
        raise ValueError("Multiplayer preference helper is missing or unpinned")
    owner = owners[0]
    if owner["kind"] != "jar" or owner["covers"] != [WARNING] or questbook.row_pin(owner) != pin(warning):
        raise ValueError("Multiplayer preference helper payload differs from its checked JAR")


def verify_public(manifest, assets, preset):
    actual = json.loads(read_asset(MANIFEST, 2 * 1024 * 1024))
    if actual != manifest:
        raise ValueError("Published manifest does not equal staged manifest")
    entry, = [f for f in actual["files"] if f["path"] == PRESET]
    if entry != {"path": PRESET, **pin(preset)}:
        raise ValueError("Public preset pin differs from source")
    for name, data in assets.items():
        if read_asset(name, len(data)) != data:
            raise ValueError(f"Public bytes differ: {name}")
    print(f"Verified {actual['revision']} {PRESET} SHA256={entry['sha256']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--author-archive", type=Path)
    parser.add_argument("--base-release", type=Path)
    args = parser.parse_args()
    revision = git("rev-parse", "HEAD")
    if args.publish and args.base_release:
        parser.error("Upload new full base assets first, then publish the composed manifest last")
    preset = subprocess.check_output(["git", "-C", str(ROOT), "show", f"HEAD:{PRESET}"])
    if preset != (ROOT / PRESET).read_bytes():
        raise ValueError("Working preset differs from committed source")
    if args.base_release:
        def read(name, maximum):
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                raise ValueError("Invalid staged asset name")
            path = args.base_release / ("." if name == MANIFEST else "assets") / name
            if path.stat().st_size > maximum:
                raise ValueError(f"Oversized staged asset: {name}")
            return path.read_bytes()
        remote = {}
    else:
        read = read_asset
        public = json.loads(gh("api", f"repos/{REPO}/releases/tags/{TAG}"))
        remote = {a["name"]: a for a in public["assets"]}

    raw = read(MANIFEST, 2 * 1024 * 1024)
    previous = json.loads(raw)
    if args.base_release and previous["revision"] != revision:
        raise ValueError("Stage the author base release from the same source commit")
    if not args.base_release:
        base_revision = previous["revision"]
        if not re.fullmatch(r"[a-f0-9]{40}", base_revision):
            raise ValueError("Invalid public revision")
        git("merge-base", "--is-ancestor", base_revision, revision)
        changed = git("diff", "--name-only", base_revision, revision).splitlines()
        allowed = {".gitattributes", "README.md", PRESET, ".github/workflows/publish.yml"}
        if any(rel not in allowed and not rel.startswith(("tools/keybinds/", "tools/questbook/", "tools/multiplayer-warning/")) for rel in changed):
            raise ValueError("A data-only delta requires a verified full --base-release for unrelated changes")
        for asset in [*previous["assets"], previous["library"]]:
            row = remote[asset["name"]]
            if row["size"] != asset["sizeBytes"] or row.get("digest") != "sha256:" + asset["sha256"]:
                raise ValueError(f"Existing GitHub asset metadata differs: {asset['name']}")
    library = read(previous["library"]["name"], 8 * 1024 * 1024)
    manifest, assets = candidate(previous, library, preset, revision)

    archive = args.author_archive.read_bytes() if args.author_archive else questbook.author_archive(questbook.load_lock())
    outputs, state = questbook.build(archive)
    previous_pins = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{previous['revision']}:tools/questbook/pins.json"],
        capture_output=True, check=False,
    )
    previous_outputs = questbook.read_json(previous_pins.stdout)["outputs"] if previous_pins.returncode == 0 else {}
    merge_questbook(manifest, assets, outputs, state, read, previous_outputs)
    merge_warning(manifest, assets)
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
            if read_asset(name, len(data)) != data:
                raise ValueError(f"Changed asset verification failed: {name}")
        if read_asset(MANIFEST, 2 * 1024 * 1024) != raw:
            raise ValueError("Published manifest changed while preparing the update")
        gh("release", "upload", TAG, str(staged), "--clobber", "--repo", REPO)
        verify_public(manifest, assets, preset)
    else:
        print(f"Staged {revision}, {len(manifest['files'])} files, preset SHA256={sha(preset)}")

    print(f"Quest book: {state['counts']}, Paxi ZIP SHA256={sha(outputs[questbook.RESOURCES])}")


if __name__ == "__main__":
    main()
