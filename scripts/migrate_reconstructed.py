"""Move `*`-prefixed lemmas over to EWE's `reconstructed` flag (jmccrae/ewe#54).

Until now an unattested (reconstructed) form was marked by a literal
leading `*` in the lemma, in the synset's `members` and in the entry's key
and sense ids. EWE now stores it as a flag on the entry (`reconstructed:
true`; WN-LMF 1.5's `Lemma/@reconstructed`) and shows the asterisk itself,
so the stored lemma must not contain one.

For every `*lemma` entry in src/yaml/entries-*.yaml this generates an
automaton script that deletes the starred entry, re-adds the plain lemma
with `reconstructed: true` on the same synset(s), and finally restores each
touched synset's original member order. It is then applied to
--wordnet-dir with a local ewe_cli build (`ewe automaton`), which also
re-files the entry under its new first letter and re-derives the sense ids.
"""

import argparse
import shutil
import subprocess
from pathlib import Path

import yaml

def build_automaton(project_dir):
    """Return (actions, n_lemmas, skipped) for every starred lemma under project_dir/src/yaml."""
    wordnet_dir = project_dir / "src" / "yaml"
    entries = {}
    for path in sorted(wordnet_dir.glob("entries-*.yaml")):
        entries.update(yaml.safe_load(path.read_text("utf-8")) or {})

    starred = []  # (lemma, pos, synset)
    skipped = []
    for lemma, by_pos in entries.items():
        if lemma.startswith("*"):
            for pos, entry in by_pos.items():
                # The flag is per entry (lemma + pos), so it can't tell a starred
                # sense from an attested one of the same plain lemma.
                if pos in entries.get(lemma[1:], {}):
                    skipped.append((lemma, pos))
                    continue
                for sense in entry["sense"]:
                    starred.append((lemma, pos, sense["synset"]))

    touched = {synset for _, _, synset in starred}
    members = {}  # synset id -> members, in original order
    for path in sorted(wordnet_dir.glob("*.yaml")):
        if path.name.startswith("entries-") or path.name == "frames.yaml":
            continue
        for synset, body in (yaml.safe_load(path.read_text("utf-8")) or {}).items():
            if synset in touched:
                members[synset] = body["members"]

    converted = {lemma for lemma, _, _ in starred}

    def convert(member):
        return member[1:] if member in converted else member

    actions = []
    for lemma, _, synset in starred:
        actions.append({"delete_entry": {"synset": synset, "lemma": lemma}})
    for lemma, pos, synset in starred:
        actions.append(
            {"add_entry": {"synset": synset, "lemma": lemma[1:], "pos": pos, "reconstructed": True}}
        )
    for synset, original in members.items():
        actions.append(
            {"change_members": {"synset": synset, "members": [convert(m) for m in original]}}
        )
    actions.append("validate")
    return actions, len(converted), skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--wordnet-dir", default=".", help="The project directory (holds settings.toml)")
    parser.add_argument("--script-out", default="reconstructed_automaton.yaml")
    parser.add_argument("--ewe-bin", default="ewe-cli")
    parser.add_argument("--apply", action="store_true", help="Run the script against --wordnet-dir")
    args = parser.parse_args()

    actions, n, skipped = build_automaton(Path(args.wordnet_dir))
    out = Path(args.script_out)
    out.write_text(yaml.safe_dump(actions, allow_unicode=True, sort_keys=False), "utf-8")
    print(f"{n} starred lemmas -> {out}")
    for lemma, pos in skipped:
        print(f"skipped {lemma!r} ({pos}): an attested {lemma[1:]!r} entry already exists")
    if args.apply:
        ewe_bin = shutil.which(args.ewe_bin) or args.ewe_bin
        subprocess.run([ewe_bin, "automaton", str(out.resolve()), "--wordnet", args.wordnet_dir], input="y\n", text=True, check=True)


if __name__ == "__main__":
    main()
