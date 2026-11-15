"""Build the bilingual Fear Nightfall quest overlay from checked author bytes."""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
from urllib.parse import quote
from urllib.request import Request, urlopen
from zipfile import ZipFile, ZipInfo

HERE = Path(__file__).resolve().parent
PACK = HERE.parents[1]
QUEST = "config/ftbquests/quests/"
OWNER = "launcher/pack-owned.txt"
RESOURCES = "config/paxi/resourcepacks/lanminecraft-fear-nightfall-quests.zip"
PINS = HERE / "pins.json"
NAMESPACE = "lanminecraft.fear_nightfall.quests"
QUOTED = r'"(?:[^"\\]|\\.)*"'
STRING = re.compile(QUOTED)
FIELDS = re.compile(
    rf"(?m)(?:^[ \t]*|(?<=, ))(?:title|subtitle|description|lock_message):[ \t]*"
    rf"(?P<values>{QUOTED}|\[\s*(?:{QUOTED}\s*,?\s*)*\])"
)
FORMAT = re.compile(r"(?<!\\)[&§][0-9a-fk-or]", re.IGNORECASE)
CONTROL = re.compile(r"\{(?:@|image:)[^}]+\}|https?://[^\s\"<>]+")
DEPENDENCY = re.compile(r"mods/(?:ftb-(?:library|quests)-forge-|Paxi-).+\.jar", re.I)


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Repeated JSON key: {key}")
        result[key] = value
    return result


def read_json(data):
    return json.loads(data, object_pairs_hook=unique)


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def pin(data):
    return {"sizeBytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def row_pin(row):
    return {key: row[key] for key in ("sizeBytes", "sha256")}


def load_lock():
    return read_json((PACK / "tools/upstream-lock.json").read_bytes())


def author_archive(lock):
    client = lock["client"]
    file_id = client["fileId"]
    url = f"https://edge.forgecdn.net/files/{file_id // 1000}/{file_id % 1000}/{quote(client['fileName'])}"
    with urlopen(Request(url, headers={"User-Agent": "LANMinecraft pack publication"}), timeout=90) as response:
        data = response.read(client["sizeBytes"] + 1)
    if pin(data) != row_pin(client):
        raise ValueError("Author archive does not match the lock")
    return data


def quest_sources(archive):
    with ZipFile(BytesIO(archive)) as client:
        sources = {}
        for name in client.namelist():
            path = name.removeprefix("overrides/")
            if name == path or not path.startswith(QUEST) or name.endswith("/"):
                continue
            if path in sources:
                raise ValueError(f"Repeated source file: {path}")
            sources[path] = client.read(name)
    return dict(sorted(sources.items()))


def text_tokens(source):
    for match in FIELDS.finditer(source):
        for quoted in STRING.finditer(source, *match.span("values")):
            value = json.loads(quoted.group())
            if value.strip() and not CONTROL.fullmatch(value):
                yield quoted.start(), quoted.end(), value


def load_table(path):
    table = HERE / "ru" / (Path(path).stem + ".json")
    return read_json(table.read_bytes()) if table.is_file() else {}


def review(sources):
    removed = {table.stem for table in (HERE / "ru").glob("*.json")} - {Path(path).stem for path in sources}
    for name in sorted(removed):
        print(f"Review removed author quest file: {name}")
    missing = len(removed)
    for path, data in sources.items():
        if not re.fullmatch(QUEST + r"(?:chapter_groups|data|chapters/[a-z0-9_.-]+)\.snbt", path):
            print(f"Review new quest file type: {path}")
            missing += 1
            continue
        required = {value for _, _, value in text_tokens(data.decode("utf-8"))}
        table = load_table(path)
        new = sorted(required - table.keys())
        old = sorted(table.keys() - required)
        if new or old:
            print(f"{path}: {len(required & table.keys())} reusable, {len(new)} new, {len(old)} removed")
            for text in new:
                print(f"  New: {text}")
            for text in old:
                print(f"  Removed: {text}")
        missing += len(new) + len(old)
    return missing


def zip_bytes(entries):
    out = BytesIO()
    with ZipFile(out, "w") as z:
        for name, data in sorted(entries.items()):
            info = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            z.writestr(info, data)
    return out.getvalue()


def rewrite(sources):
    en_us, ru_ru, outputs = {}, {}, {}
    occurrences = 0
    for path, data in sources.items():
        source = data.decode("utf-8")
        table = load_table(path)
        pieces = []
        cursor = 0
        for start, end, english in text_tokens(source):
            russian = table[english]
            if not isinstance(russian, str) or not russian.strip() or russian.count("\n") != english.count("\n"):
                raise ValueError(f"Invalid translation in {path}: {english!r}")
            if FORMAT.findall(english) != FORMAT.findall(russian) or CONTROL.findall(english) != CONTROL.findall(russian):
                raise ValueError(f"Changed formatting or control token in {path}: {english!r}")
            if english == russian:
                continue  # The book title is a proper name in either locale.
            if english.startswith(('{"', '["')):
                raise ValueError(f"Review structured text before converting {path}: {english!r}")
            digest = hashlib.sha256(english.encode("utf-8")).hexdigest()[:24]
            key = f"{NAMESPACE}.{Path(path).stem}.{digest}"
            if key in en_us and en_us[key] != english.replace("%", "%%"):
                raise ValueError(f"Duplicate generated key: {key}")
            # FTB Library formats the locale string through I18n, then parses its legacy styles.
            en_us[key] = english.replace("%", "%%")
            ru_ru[key] = russian.replace("%", "%%")
            pieces.extend((source[cursor:start], json.dumps("{" + key + "}")))
            cursor = end
            occurrences += 1
        pieces.append(source[cursor:])
        rewritten = "".join(pieces).encode("utf-8")
        if rewritten != data:
            outputs[path] = rewritten
    if not outputs:
        raise ValueError("No quest files localized")
    lang = "assets/lanminecraft_fear_quests/lang/"
    outputs[RESOURCES] = zip_bytes({
        "pack.mcmeta": encode({"pack": {"pack_format": 15, "description": "Fear Nightfall quest book localization"}}),
        lang + "en_us.json": encode(en_us),
        lang + "ru_ru.json": encode(ru_ru),
    })
    return outputs, {"chapters": sum(path.startswith(QUEST + "chapters/") for path in sources),
                     "occurrences": occurrences, "entries": len(ru_ru)}


def build(archive, *, approve=False):
    lock = load_lock()
    if pin(archive) != row_pin(lock["client"]):
        raise ValueError("Use the exact author archive in tools/upstream-lock.json")
    sources = quest_sources(archive)
    overrides = {row["path"]: row_pin(row) for row in lock["overrides"]}
    actual = {path: pin(data) for path, data in sources.items()}
    expected = {path: row for path, row in overrides.items() if path.startswith(QUEST)}
    if actual != expected or RESOURCES in overrides:
        raise ValueError("Author quest inventory differs from the lock or conflicts with the Paxi resource path")
    dependencies = {
        row["path"]: row_pin(row) for row in lock["files"]
        if row["required"] and DEPENDENCY.fullmatch(row["path"])
    }
    if len(dependencies) != 3:
        raise ValueError("Expected the pinned FTB Library, FTB Quests and Paxi dependencies")
    if review(sources):
        raise ValueError("Review changed, new or removed author text before publication")
    outputs, counts = rewrite(sources)
    owner = (PACK / OWNER).read_bytes()
    outputs[OWNER] = ("\n".join(sorted(set(owner.decode("utf-8").splitlines()) | outputs.keys())) + "\n").encode("utf-8")
    state = {
        "schemaVersion": 1,
        "inputs": actual | dependencies | {OWNER: pin(owner)},
        "outputs": {path: pin(data) for path, data in outputs.items()},
        "counts": counts,
    }
    if approve:
        PINS.write_bytes(encode(state))
    elif read_json(PINS.read_bytes()) != state:
        raise ValueError("Quest overlay pins changed. Review author files, dependencies and Russian text, then explicitly approve.")
    return outputs, state


def apply(game, outputs, state):
    for path, expected in state["inputs"].items():
        if pin((game / path).read_bytes()) != expected:
            raise ValueError(f"Stage is not the verified author input: {path}")
    if (game / RESOURCES).exists():
        raise ValueError(f"Unexpected existing resource pack: {RESOURCES}")
    for path, data in outputs.items():
        file = game / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("review", "verify", "approve", "apply"))
    parser.add_argument("archive", type=Path)
    parser.add_argument("--game", type=Path)
    args = parser.parse_args()
    archive = args.archive.read_bytes()
    if args.operation == "review":
        return bool(review(quest_sources(archive)))
    outputs, state = build(archive, approve=args.operation == "approve")
    if args.operation == "apply":
        if args.game is None:
            parser.error("apply needs --game for a disposable author staging instance")
        apply(args.game, outputs, state)
    print(json.dumps(state["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
