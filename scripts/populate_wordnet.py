"""Populate src/yaml/ with wordnet senses accepted by the annotator.

data/sga_incomplete.results_AD.xlsx holds WSD candidates (Old Irish lemma,
English WordNet sense key, definition) reviewed by an annotator, with
"Correct Translation?" / "Correct Definition?" 0/1 columns. This script
keeps rows where both are accepted, resolves each sense key to its English
synset (via a local `wn` library database - see
https://github.com/goodmami/wn), and builds an EWE automaton script
(https://github.com/jmccrae/ewe) that:

  - creates a new synset per accepted English sense (same lexfile and
    part of speech) with the Old Irish lemma(s) as members - multiple
    accepted lemmas mapping to the same English synset become synonyms in
    the same new synset. The definition is the English synset's own
    definition, prefixed with its English member lemma(s) (e.g.
    "definition — a concise explanation of the meaning of a word or
    phrase or symbol"), since the members themselves no longer show the
    English word once they're replaced with Old Irish ones;
  - sets the new synset's ili to the English synset's ili, preserving the
    interlingual link between the two wordnets.

Relations (hypernym, etc.) are deliberately not carried over yet, since
this only imports a sparse subset of English WordNet's synsets - most
relation targets wouldn't exist in this wordnet at all.

The generated script is then applied to --wordnet-dir with a local ewe_cli
build (`ewe automaton`).
"""

import argparse
import shutil
import sqlite3
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path

import openpyxl

import yaml

DEFAULT_XLSX = "data/sga_incomplete.results_AD.xlsx"
DEFAULT_WN_DB = str(Path("~/.wn_data/wn.db").expanduser())


def sense_key_to_wn_id(sense_key: str) -> str:
    """The `wn` library's own encoding of a WordNet sense key as a lexical id."""
    return "oewn-" + sense_key.replace("%", "__").replace(":", ".")


def load_accepted_rows(xlsx_path):
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active
    rows = []
    for lemma, sense_key, _definition, _freq, correct_translation, correct_definition, _notes in ws.iter_rows(
        min_row=2, values_only=True
    ):
        if correct_translation == 1 and correct_definition == 1:
            rows.append((lemma, sense_key))
    return rows


def resolve_sense(con, sense_key):
    """Look up a sense key's synset id, pos, lexfile, ili, definition and
    English member lemmas (in synset order)."""
    cur = con.execute(
        """
        select syn.rowid, syn.id, syn.pos, lf.name, ili.id, d.definition
        from senses s
        join synsets syn on s.synset_rowid = syn.rowid
        join lexfiles lf on syn.lexfile_rowid = lf.rowid
        left join ilis ili on syn.ili_rowid = ili.rowid
        left join definitions d on d.synset_rowid = syn.rowid
        where s.id = ?
        """,
        (sense_key_to_wn_id(sense_key),),
    )
    row = cur.fetchone()
    if row is None:
        return None
    synset_rowid, oewn_id, pos, lexfile, ili, definition = row

    cur = con.execute(
        """
        select f.form
        from senses s2
        join entries e on s2.entry_rowid = e.rowid
        join forms f on f.entry_rowid = e.rowid and f.rank = 0
        where s2.synset_rowid = ?
        order by s2.synset_rank
        """,
        (synset_rowid,),
    )
    english_lemmas = [r[0] for r in cur.fetchall()]
    return oewn_id, pos, lexfile, ili, definition, english_lemmas


def build_groups(rows, con):
    """Group accepted (lemma, sense_key) rows by their English synset, so
    synonyms in the accepted set become members of one new synset rather
    than duplicate synsets."""
    groups = OrderedDict()
    unresolved = []
    for lemma, sense_key in rows:
        resolved = resolve_sense(con, sense_key)
        if resolved is None:
            unresolved.append((lemma, sense_key))
            continue
        oewn_id, pos, lexfile, ili, definition, english_lemmas = resolved
        definition = f"{', '.join(english_lemmas)} — {definition}"
        group = groups.setdefault(
            oewn_id,
            {"pos": pos, "lexfile": lexfile, "ili": ili, "definition": definition, "lemmas": []},
        )
        if lemma not in group["lemmas"]:
            group["lemmas"].append(lemma)
    return groups, unresolved


def build_automaton(groups):
    actions = []
    for group in groups.values():
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
    return actions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsx", default=DEFAULT_XLSX)
    parser.add_argument("--wn-db", default=DEFAULT_WN_DB, help="Path to a `wn` library sqlite database")
    parser.add_argument("--wordnet-dir", default=".", help="Directory containing settings.toml / src/yaml")
    parser.add_argument("--ewe-bin", default="ewe-cli", help="Path to (or name on PATH of) the ewe_cli binary")
    parser.add_argument("--script-out", default="automaton.yaml", help="Where to write the generated automaton script")
    parser.add_argument("--apply", action="store_true", help="Actually run the script through ewe_cli (default: only generate it)")
    args = parser.parse_args()

    rows = load_accepted_rows(args.xlsx)
    con = sqlite3.connect(args.wn_db)
    groups, unresolved = build_groups(rows, con)

    definitions = [g["definition"] for g in groups.values()]
    if len(definitions) != len(set(definitions)):
        dupes = {d for d in definitions if definitions.count(d) > 1}
        print(f"WARNING: {len(dupes)} duplicate definition(s) across distinct synsets - "
              f"EWE mints synset ids from a hash of the definition, so these will collide:",
              file=sys.stderr)
        for d in dupes:
            print(f"  {d}", file=sys.stderr)

    actions = build_automaton(groups)
    with open(args.script_out, "w", encoding="utf-8") as f:
        yaml.safe_dump(actions, f, allow_unicode=True, sort_keys=False)

    print(f"{len(rows)} accepted rows -> {len(groups)} synsets ({len(unresolved)} unresolved sense keys)")
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
