"""Rebuild and compare the pack's client helper against its committed JAR."""
import argparse
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import subprocess
from zipfile import ZipFile, ZipInfo

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("javac", type=Path)
    parser.add_argument("libraries", type=Path)
    parser.add_argument("classes", type=Path)
    args = parser.parse_args()
    if subprocess.check_output([str(args.javac), "-version"], text=True).strip() != "javac 21.0.12.1":
        raise ValueError("Use the reviewed javac 21.0.12.1")
    classpath = []
    for row in (HERE / "compiler-inputs.txt").read_text().splitlines():
        digest, relative = row.split()
        path = (args.libraries / relative).resolve()
        if sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Unexpected compiler input: {relative}")
        classpath.append(str(path))
    args.classes.mkdir(parents=True)
    subprocess.run([str(args.javac), "--release", "17", "-encoding", "UTF-8", "-cp", os.pathsep.join(classpath),
                    "-d", str(args.classes), str(HERE / "MultiplayerWarning.java")], check=True)
    entries = {p.relative_to(args.classes).as_posix(): p.read_bytes() for p in args.classes.rglob("*.class")}
    for name in ("META-INF/mods.toml", "pack.mcmeta"):
        entries[name] = (HERE / name).read_bytes().replace(b"\r\n", b"\n")
    out = BytesIO()
    with ZipFile(out, "w") as jar:
        for name, data in sorted(entries.items()):
            info = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            jar.writestr(info, data)
    result = out.getvalue()
    if (HERE / "fear-nightfall-multiplayer-warning-1.0.0.jar").read_bytes() != result:
        raise ValueError("Rebuild differs from the checked JAR")
    print(sha256(result).hexdigest())


if __name__ == "__main__":
    main()
