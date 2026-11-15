"""Check the committed preset without launching Minecraft."""
from itertools import combinations

from build_preset import HERE, PRESET, UNBOUND, conflict, load_lines, render


def main():
    registered = load_lines((HERE / "registered-keys.txt").read_text(encoding="utf-8"))
    encoded = PRESET.read_bytes()
    if encoded != render().encode("utf-8"):
        raise ValueError("Rebuild with tools/keybinds/build_preset.py")
    preset = load_lines(encoded.decode("utf-8"))
    if list(preset) != list(registered):
        raise ValueError("Preset must cover the complete observed inventory")
    vanilla = list(registered)[:34]
    if any(preset[name] != registered[name] for name in vanilla):
        raise ValueError("Base game mappings changed")
    if any(value == UNBOUND and registered[name] != UNBOUND for name, value in preset.items()):
        raise ValueError("A previously bound action was unbound")
    conflicts = [
        (left, right) for left, right in combinations(preset, 2)
        if conflict(left, preset[left], right, preset[right])
    ]
    if conflicts:
        raise ValueError(f"Conflicts: {conflicts}")
    print(f"{len(registered)} registered, {len(vanilla)} base mappings preserved, 0 modeled conflicts")


if __name__ == "__main__":
    main()
