"""Import the reviewed rows of data/OI_Combined.review.csv into src/yaml/.

data/OI_Combined.review.csv holds WSD candidates (Old Irish lemma, English
WordNet sense key, definition) reviewed by an annotator in PR #4, with the
same "Correct Translation?" / "Correct Definition?" 0/1 columns and free-text
"Notes" as data/sga_incomplete.results_AD.xlsx (see
scripts/populate_wordnet.py). This script keeps rows where both are
accepted, then applies data/OI_Combined.corrections.csv - a manually
curated reading of the annotator's notes, keyed on (lemma, sense_key):

  - corrected_lemma fixes a lemma the MWE handling upstream got wrong
    (a repeated preverb, e.g. "for forcongair"; a stray "_" token, e.g.
    "tír _"; an emphatic pronoun or neighbouring word pulled in, e.g.
    "dofuthraccair sa"). Blank keeps the lemma as-is.
  - corrected_sense_key redirects the row to a better-fitting English
    WordNet sense (e.g. a grammatical sense the WSD system passed over).
    Blank keeps the row's own sense key; "-" drops the row.
  - a (lemma, sense_key) can appear more than once, each row adding one
    target - e.g. to keep the original sense *and* add one the annotator
    noted was missing.

A correction overrides the annotator's flags either way: rejected rows can
be rescued and accepted rows dropped or redirected.

Unlike populate_wordnet.py, this runs against a wordnet that already has
synsets, so each accepted English synset is matched (via ili, same join as
scripts/annotate_corpus_senses.py) against src/yaml/ first: if it already
has an Old Irish counterpart, any lemma not already a member is added to it
with `add_entry`; otherwise a new synset is created exactly as
populate_wordnet.py does (English lemmas prefixed to the definition, ili
carried over).

Run scripts/link_existing_synsets.py and scripts/link_transitive_hypernyms.py
afterwards to link the new synsets into the existing hierarchy.
"""

import argparse
import csv
import shutil
import sqlite3
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from annotate_corpus_senses import load_synsets_by_ili
from populate_wordnet import DEFAULT_WN_DB, resolve_sense

DEFAULT_REVIEW = "data/OI_Combined.review.csv"
DEFAULT_CORRECTIONS = "data/OI_Combined.corrections.csv"
DROP = "-"


def load_corrections(csv_path):
    """(lemma, sense_key) -> [(lemma, sense_key) target, ...]; an empty
    list means the row is dropped."""
    corrections = OrderedDict()
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["lemma"], row["sense_key"])
            targets = corrections.setdefault(key, [])
            if row["corrected_sense_key"] == DROP:
                continue
            targets.append((row["corrected_lemma"] or row["lemma"], row["corrected_sense_key"] or row["sense_key"]))
    return corrections


def load_accepted_rows(review_path, corrections):
    """Effective (lemma, sense_key) rows, in review order and deduplicated,
    plus the correction keys that matched no review row."""
    rows = []
    matched = set()
    with open(review_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["Lemma"], row["Sense Key"])
            if key in corrections:
                matched.add(key)
                targets = corrections[key]
            elif row["Correct Translation?"] == "1" and row["Correct Definition?"] == "1":
                targets = [key]
            else:
                targets = []
            for target in targets:
                if target not in rows:
                    rows.append(target)
    return rows, corrections.keys() - matched


def build_groups(rows, con):
    """Group rows by English synset, as populate_wordnet.build_groups does,
    keeping the ili so they can be matched against existing synsets."""
    groups = OrderedDict()
    unresolved = []
    for lemma, sense_key in rows:
        resolved = resolve_sense(con, sense_key)
        if resolved is None:
            unresolved.append((lemma, sense_key))
            continue
        oewn_id, pos, lexfile, ili, definition, english_lemmas = resolved
        group = groups.setdefault(
            oewn_id,
            {
                "pos": pos,
                "lexfile": lexfile,
                "ili": ili,
                "definition": f"{', '.join(english_lemmas)} — {definition}",
                "lemmas": [],
            },
        )
        if lemma not in group["lemmas"]:
            group["lemmas"].append(lemma)
    return groups, unresolved


def build_automaton(groups, synsets_by_ili):
    """Returns (actions, new synset count, added entry count, already-present
    (lemma, synset id) pairs)."""
    actions = []
    new_synsets = 0
    added_entries = 0
    already_present = []
    for group in groups.values():
        existing = synsets_by_ili.get(group["ili"]) if group["ili"] else None
        if existing is None:
            actions.append(
                {
                    "add_synset": {
                        "definition": group["definition"],
                        "lexfile": group["lexfile"],
                        "pos": group["pos"],
                        "lemmas": group["lemmas"],
                    }
                }
            )
            if group["ili"]:
                actions.append({"change_ili": {"synset": "last", "ili": group["ili"]}})
            new_synsets += 1
            continue
        synset_id, members = existing
        for lemma in group["lemmas"]:
            if lemma in members:
                already_present.append((lemma, synset_id))
                continue
            actions.append({"add_entry": {"synset": synset_id, "lemma": lemma, "pos": group["pos"]}})
            added_entries += 1
    return actions, new_synsets, added_entries, already_present


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--review", default=DEFAULT_REVIEW)
    parser.add_argument("--corrections", default=DEFAULT_CORRECTIONS)
    parser.add_argument("--wn-db", default=DEFAULT_WN_DB, help="Path to a `wn` library sqlite database")
    parser.add_argument("--wordnet-dir", default=".", help="Directory containing settings.toml / src/yaml")
    parser.add_argument("--ewe-bin", default="ewe-cli", help="Path to (or name on PATH of) the ewe_cli binary")
    parser.add_argument("--script-out", default="review_automaton.yaml", help="Where to write the generated automaton script")
    parser.add_argument("--apply", action="store_true", help="Actually run the script through ewe_cli (default: only generate it)")
    args = parser.parse_args()

    corrections = load_corrections(args.corrections)
    rows, unmatched = load_accepted_rows(args.review, corrections)
    for lemma, sense_key in sorted(unmatched):
        print(f"WARNING: correction for {lemma!r} {sense_key!r} did not match any review row", file=sys.stderr)

    con = sqlite3.connect(args.wn_db)
    groups, unresolved = build_groups(rows, con)
    synsets_by_ili = load_synsets_by_ili(args.wordnet_dir)
    actions, new_synsets, added_entries, already_present = build_automaton(groups, synsets_by_ili)

    with open(args.script_out, "w", encoding="utf-8") as f:
        yaml.safe_dump(actions, f, allow_unicode=True, sort_keys=False)

    print(
        f"{len(rows)} accepted rows -> {new_synsets} new synsets, {added_entries} entries added to existing "
        f"synsets, {len(already_present)} already present ({len(unresolved)} unresolved sense keys)"
    )
    for lemma, sk in unresolved:
        print(f"  unresolved: {lemma} {sk}", file=sys.stderr)
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
