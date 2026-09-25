"""Import Old Irish translations from data/priority_concepts.csv into
src/yaml/.

scripts/priority_concepts.py generates data/priority_concepts.csv as a
read-only report ranking untranslated English WordNet concepts; a
contributor then fills in its `old_irish_lemmas` column by hand. This
script reads that filled-in column and builds an EWE automaton script
(https://github.com/jmccrae/ewe) that creates one new synset per row that
has at least one Old Irish lemma - same pos/lexfile/ili as the English
synset_id the row names, with the Old Irish lemma(s) as members instead
of the English ones. Rows with an empty `old_irish_lemmas` column (not
yet translated) are skipped.

A lemma prefixed with `*` is a contributor's mark for a doubtful or
unattested form (standard historical-linguistics notation) - kept as-is
in the member string, asterisk and all, rather than stripped, so the
uncertainty stays visible in src/yaml/ itself and not just in the CSV.

The synset's ili is looked up from `synset_id` (an oewn- id, e.g.
"oewn-00001740-n") via a local `wn` library database - see
https://github.com/goodmami/wn - same as scripts/populate_wordnet.py.

The generated script is then applied to --wordnet-dir with a local
ewe_cli build (`ewe automaton`), same as populate_wordnet.py.
"""

import argparse
import csv
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import yaml

DEFAULT_CSV = "data/priority_concepts.csv"
DEFAULT_WN_DB = str(Path("~/.wn_data/wn.db").expanduser())


def load_rows(csv_path):
    """(synset_id, pos, lexfile, english_lemmas, definition, [old_irish_lemma,
    ...]) tuples for every row with at least one Old Irish lemma. Lemmas are
    split on ',' and stripped of surrounding whitespace; a leading '*' is
    kept as part of the lemma."""
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            lemmas = [l.strip() for l in row["old_irish_lemmas"].split(",") if l.strip()]
            if not lemmas:
                continue
            rows.append(
                (
                    row["synset_id"],
                    row["pos"],
                    row["lexfile"],
                    row["english_lemmas"],
                    row["definition"],
                    lemmas,
                )
            )
    return rows


def resolve_ili(con, synset_id):
    cur = con.execute(
        "select ili.id from synsets syn left join ilis ili on syn.ili_rowid = ili.rowid where syn.id = ?",
        (synset_id,),
    )
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def build_automaton(rows, con):
    actions = []
    unresolved = []
    definitions = []
    for synset_id, pos, lexfile, english_lemmas, definition, lemmas in rows:
        ili = resolve_ili(con, synset_id)
        if ili is None:
            unresolved.append(synset_id)
            continue
        full_definition = f"{english_lemmas} — {definition}"
        definitions.append(full_definition)
        actions.append(
            {
                "add_synset": {
                    "definition": full_definition,
                    "lexfile": lexfile,
                    "pos": pos,
                    "lemmas": lemmas,
                }
            }
        )
        actions.append({"change_ili": {"synset": "last", "ili": ili}})
    return actions, unresolved, definitions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=DEFAULT_CSV)
    parser.add_argument("--wn-db", default=DEFAULT_WN_DB, help="Path to a `wn` library sqlite database")
    parser.add_argument("--wordnet-dir", default=".", help="Directory containing settings.toml / src/yaml")
    parser.add_argument("--ewe-bin", default="ewe-cli", help="Path to (or name on PATH of) the ewe_cli binary")
    parser.add_argument("--script-out", default="priority_automaton.yaml", help="Where to write the generated automaton script")
    parser.add_argument("--apply", action="store_true", help="Actually run the script through ewe_cli (default: only generate it)")
    args = parser.parse_args()

    rows = load_rows(args.csv)
    con = sqlite3.connect(args.wn_db)
    actions, unresolved, definitions = build_automaton(rows, con)

    if len(definitions) != len(set(definitions)):
        dupes = {d for d in definitions if definitions.count(d) > 1}
        print(f"WARNING: {len(dupes)} duplicate definition(s) across distinct synsets - "
              f"EWE mints synset ids from a hash of the definition, so these will collide:",
              file=sys.stderr)
        for d in dupes:
            print(f"  {d}", file=sys.stderr)

    with open(args.script_out, "w", encoding="utf-8") as f:
        yaml.safe_dump(actions, f, allow_unicode=True, sort_keys=False)

    n_synsets = len(actions) // 2
    print(f"{len(rows)} translated rows -> {n_synsets} synsets ({len(unresolved)} unresolved synset ids)")
    for synset_id in unresolved:
        print(f"  unresolved: {synset_id}", file=sys.stderr)
    print(f"Automaton script written to {args.script_out}")

    if not args.apply:
        return

    ewe_bin = shutil.which(args.ewe_bin) or args.ewe_bin
    subprocess.run(
        [ewe_bin, "automaton", str(Path(args.script_out).resolve()), "--wordnet", args.wordnet_dir],
        input="y\n",
        text=True,
        check=True,
    )


if __name__ == "__main__":
    main()
