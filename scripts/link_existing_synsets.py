"""Add relations between synsets that already both exist in this wordnet.

populate_wordnet.py deliberately doesn't import relations (hypernym, etc.)
since most relation targets don't exist in this sparse a wordnet yet - but
some do: wherever English WordNet has a hypernym/attribute/similar/also
relation and *both* endpoints already have an Old Irish synset here (via
their shared `ili`), that relation can be added for free, no new
translation needed.

Matching is via ili, the same join scripts/annotate_corpus_senses.py uses
and for the same reason: project sense ids in src/yaml/entries-*.yaml
don't reliably reuse the source English sense key's lex_id, so ili is the
only robust way to tell whether a given English synset already has an Old
Irish counterpart here (see that script's docstring for the details).

The generated script is then applied to --wordnet-dir with a local ewe_cli
build (`ewe automaton`), same as populate_wordnet.py.
"""

import argparse
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from annotate_corpus_senses import DEFAULT_WORDNET_DIR, load_synsets_by_ili
from populate_wordnet import DEFAULT_WN_DB

# hypernym is asymmetric (its inverse, hyponym, is excluded from
# DEFAULT_RELATION_TYPES entirely - EWE's own `id`/`word` display already
# infers and shows it by reverse-looking-up stored hypernym edges, exactly
# like it does for the types below, confirmed empirically in a scratch
# wordnet). similar/also/attribute are all effectively symmetric here too:
# EWE only *auto-stores* the reverse edge for similar/also
# (ewe_lib::change_manager::insert_rel's is_symmetric check), but its
# display layer does generic reverse-relation lookup regardless - adding
# attribute in just one direction, confirmed the same way, already shows
# correctly from both synsets, so storing wn.db's other direction too (it
# stores attribute both ways, unlike hypernym/hyponym) would just be a
# redundant duplicate edge. antonym never actually appears at the synset
# level in practice (it's a sense-level relation in wn.db), kept here only
# so a future wn.db that did populate it wouldn't be silently skipped.
DEFAULT_RELATION_TYPES = ("hypernym", "attribute", "similar", "antonym", "also")
SYMMETRIC_TYPES = {"similar", "also", "attribute"}


def find_internal_relations(con, synsets_by_ili, relation_types):
    """(source synset id, relation type, target synset id) triples where
    both endpoints already exist in synsets_by_ili (keyed by ili)."""
    cur = con.execute("select syn.rowid, ili.id from synsets syn join ilis ili on syn.ili_rowid = ili.rowid")
    our_ili_by_rowid = {rowid: ili for rowid, ili in cur.fetchall() if ili in synsets_by_ili}

    placeholders = ",".join("?" for _ in relation_types)
    cur = con.execute(
        f"""
        select sr.source_rowid, rt.type, sr.target_rowid
        from synset_relations sr
        join relation_types rt on sr.type_rowid = rt.rowid
        where rt.type in ({placeholders})
        """,
        relation_types,
    )
    triples = []
    for source_rowid, rel_type, target_rowid in cur.fetchall():
        source_ili = our_ili_by_rowid.get(source_rowid)
        target_ili = our_ili_by_rowid.get(target_rowid)
        if source_ili is None or target_ili is None:
            continue
        source_id, _ = synsets_by_ili[source_ili]
        target_id, _ = synsets_by_ili[target_ili]
        triples.append((source_id, rel_type, target_id))
    return triples


def dedupe(triples):
    """Drop redundant reverse rows for effectively-symmetric relation types
    (see SYMMETRIC_TYPES) - not needed for hypernym, which is asymmetric
    and where DEFAULT_RELATION_TYPES already excludes its inverse."""
    seen = set()
    result = []
    for source, rel_type, target in triples:
        key = (rel_type, frozenset((source, target))) if rel_type in SYMMETRIC_TYPES else (rel_type, source, target)
        if key in seen:
            continue
        seen.add(key)
        result.append((source, rel_type, target))
    return result


def build_automaton(triples):
    return [{"add_relation": {"source": source, "relation": rel_type, "target": target}} for source, rel_type, target in triples]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wn-db", default=DEFAULT_WN_DB, help="Path to a `wn` library sqlite database")
    parser.add_argument("--wordnet-dir", default=DEFAULT_WORDNET_DIR, help="Directory containing settings.toml / src/yaml")
    parser.add_argument("--relation-types", nargs="+", default=list(DEFAULT_RELATION_TYPES))
    parser.add_argument("--ewe-bin", default="ewe-cli", help="Path to (or name on PATH of) the ewe_cli binary")
    parser.add_argument("--script-out", default="link_automaton.yaml", help="Where to write the generated automaton script")
    parser.add_argument("--apply", action="store_true", help="Actually run the script through ewe_cli (default: only generate it)")
    args = parser.parse_args()

    synsets_by_ili = load_synsets_by_ili(args.wordnet_dir)
    con = sqlite3.connect(args.wn_db)

    triples = dedupe(find_internal_relations(con, synsets_by_ili, args.relation_types))
    actions = build_automaton(triples)
    with open(args.script_out, "w", encoding="utf-8") as f:
        yaml.safe_dump(actions, f, allow_unicode=True, sort_keys=False)

    print(f"{len(triples)} internal relation(s) found -> {args.script_out}")
    for source, rel_type, target in triples:
        print(f"  {source} ={rel_type}=> {target}")

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
