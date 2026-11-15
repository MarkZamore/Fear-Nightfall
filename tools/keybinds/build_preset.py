"""Build Fear Nightfall's launcher preset from its observed 1.20.1 bindings."""
from pathlib import Path
import json
import re

HERE = Path(__file__).resolve().parent
PRESET = HERE.parent.parent / "launcher/controls-preset.txt"
UNBOUND = "key.keyboard.unknown"
KEYBOARD = "key.keyboard."
MODIFIER_KEYS = {
    name: {f"{KEYBOARD}{side}.{stem}" for side in ("left", "right")}
    for name, stem in (("ALT", "alt"), ("CONTROL", "control"), ("SHIFT", "shift"))
}
KEYS = {
    *(KEYBOARD + x for x in "abcdefghijklmnopqrstuvwxyz0123456789"),
    *(KEYBOARD + x for x in (
        "space", "tab", "escape", "enter", "backspace", "slash", "apostrophe",
        "up", "down", "left", "right", "home", "end", "page.up", "page.down",
        "insert", "delete", "comma", "period", "minus", "equal", "semicolon",
        "left.bracket", "right.bracket", "backslash", "grave.accent",
        "keypad.add", "keypad.subtract", "keypad.multiply", "keypad.divide",
        "keypad.enter", "keypad.decimal", "keypad.equal", "caps.lock", "scroll.lock", "pause", "num.lock", "menu",
    )),
    *(KEYBOARD + f"f{n}" for n in range(1, 13)),
    *(KEYBOARD + f"keypad.{n}" for n in range(10)),
    *set().union(*MODIFIER_KEYS.values()),
    *("key.mouse." + x for x in ("left", "right", "middle", "4", "5", "6", "7", "8")),
    UNBOUND,
}
VANILLA_GAME = {"key_" + name for name in (
    "key.forward", "key.left", "key.back", "key.right", "key.jump", "key.sneak",
    "key.sprint", "key.attack", "key.chat", "key.playerlist", "key.command",
    "key.togglePerspective", "key.smoothCamera", "key.use", "key.pickItem",
)}


def load_lines(text):
    bindings = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition(":")
        key, _, modifier = value.partition(":")
        if not separator or not re.fullmatch(r"key_[^:\r\n]+", name) or name in bindings:
            raise ValueError(f"Invalid or repeated mapping: {line}")
        if key not in KEYS or modifier not in {"", *MODIFIER_KEYS} or value.endswith(":"):
            raise ValueError(f"Invalid key or modifier: {line}")
        bindings[name] = value
    return bindings


def context(name):
    if name in VANILLA_GAME or name == "key_key.carry.desc" or name.startswith("key_key.hexerei."):
        return "game"
    if name.startswith("key_key.jei."):
        return "gui"
    return "both"


def conflict(left_name, left, right_name, right):
    left_key, _, left_modifier = left.partition(":")
    right_key, _, right_modifier = right.partition(":")
    if {left_name, right_name} == {"key_key.carry.desc", "key_key.sneak"} and left == right == "key.keyboard.left.shift":
        return False
    if UNBOUND in (left_key, right_key):
        return False
    left_context, right_context = context(left_name), context(right_name)
    if {left_context, right_context} == {"gui", "game"}:
        return False
    if left_key in MODIFIER_KEYS.get(right_modifier, ()) or right_key in MODIFIER_KEYS.get(left_modifier, ()):
        return True
    return left_key == right_key and (
        left_modifier == right_modifier
        or ({left_context, right_context} != {"gui"} and "" in (left_modifier, right_modifier))
    )


def render():
    registered = load_lines((HERE / "registered-keys.txt").read_text(encoding="utf-8"))
    replacements = json.loads((HERE / "layout.json").read_text(encoding="utf-8"))
    if not replacements.keys() <= registered.keys():
        raise ValueError("Layout contains unregistered IDs")
    resolved = registered | replacements
    load_lines("\n".join(f"{name}:{value}" for name, value in resolved.items()))
    return (
        "# Fear Nightfall 1.2.0 | Minecraft 1.20.1, Forge 47.4.8\n"
        "# Раскладка и контексты описаны в tools/keybinds/design.md.\n"
        + "".join(f"{name}:{value}\n" for name, value in resolved.items())
    )


if __name__ == "__main__":
    PRESET.write_bytes(render().encode("utf-8"))
