"""Add hypernym relations that require skipping untranslated English synsets.

scripts/link_existing_synsets.py only adds a relation where *both* English
WordNet endpoints already have an Old Irish synset here - so a pair like
cathair ("city") and leth ("region") stays unlinked as long as every
English synset on the hypernym path between them (city -> urban district
-> ... -> region) is untranslated, even though hypernym is the one
relation type where that path can be safely skipped: it's transitive, so
"cathair's nearest translated ancestor is leth" is exactly as true and
useful a fact as a direct edge would be, and translating one of the
skipped synsets later just inserts it into the chain (see
scripts/priority_concepts.py, whose "bridging" ranking already prioritises
exactly these skipped-over synsets for that reason).

For every synset here, walks up wn.db's hypernym graph from its English
counterpart (matched via ili, same join scripts/annotate_corpus_senses.py
and scripts/link_existing_synsets.py use) past any number of untranslated
synsets, stopping each branch at the first translated ancestor it finds
(via ili) - i.e. its nearest Old Irish hypernym(s), which may be more than
one if English WordNet's multiple-inheritance parents lead to different
translated ancestors. Purely additive: never revisits past a translated
ancestor, so this can be re-run after every new batch of translations
without redoing work or overshooting into ancestors-of-ancestors.

Not extended to attribute/similar/also/antonym - unlike hypernym, those
aren't chains where skipping an untranslated link in between still means
the same thing.

The generated script is then applied to --wordnet-dir with a local ewe_cli
build (`ewe automaton`), same as link_existing_synsets.py.
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


def build_hypernym_parents(con):
    """child synset rowid -> [parent synset rowid, ...]."""
    parents = {}
    cur = con.execute(
        """
        select sr.source_rowid, sr.target_rowid
        from synset_relations sr
        join relation_types rt on sr.type_rowid = rt.rowid
        where rt.type = 'hypernym'
        """
    )
    for child, parent in cur.fetchall():
        parents.setdefault(child, []).append(parent)
    return parents


def build_ili_by_rowid(con):
    cur = con.execute("select syn.rowid, ili.id from synsets syn join ilis ili on syn.ili_rowid = ili.rowid")
    return dict(cur.fetchall())


def nearest_translated_ancestors(rowid, parents_by_rowid, ili_by_rowid, synsets_by_ili):
    """Old Irish synset ids of the nearest translated hypernym ancestor(s) of
    `rowid`, walking past any number of untranslated ones. Each branch of
    the (possibly multiple-inheritance) hypernym DAG stops as soon as it
    hits a translated synset - it isn't expanded further, so this only
    ever returns *nearest* ancestors, never grandparents of an already-
    translated parent."""
    found = set()
    stack = list(parents_by_rowid.get(rowid, []))
    visited = set()
    while stack:
        parent_rowid = stack.pop()
        if parent_rowid in visited:
            continue
        visited.add(parent_rowid)
        parent_ili = ili_by_rowid.get(parent_rowid)
        if parent_ili and parent_ili in synsets_by_ili:
            found.add(synsets_by_ili[parent_ili][0])
            continue
        stack.extend(parents_by_rowid.get(parent_rowid, []))
    return found


def find_transitive_hypernyms(con, synsets_by_ili):
    parents_by_rowid = build_hypernym_parents(con)
    ili_by_rowid = build_ili_by_rowid(con)
    ili_to_rowid = {ili: rowid for rowid, ili in ili_by_rowid.items()}

    triples = []
    for ili, (our_id, _members) in synsets_by_ili.items():
        rowid = ili_to_rowid.get(ili)
        if rowid is None:
            continue
        for target_id in nearest_translated_ancestors(rowid, parents_by_rowid, ili_by_rowid, synsets_by_ili):
            if target_id != our_id:
                triples.append((our_id, target_id))
    return sorted(set(triples))


def build_automaton(triples):
    return [{"add_relation": {"source": source, "relation": "hypernym", "target": target}} for source, target in triples]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wn-db", default=DEFAULT_WN_DB, help="Path to a `wn` library sqlite database")
    parser.add_argument("--wordnet-dir", default=DEFAULT_WORDNET_DIR, help="Directory containing settings.toml / src/yaml")
    parser.add_argument("--ewe-bin", default="ewe-cli", help="Path to (or name on PATH of) the ewe_cli binary")
    parser.add_argument("--script-out", default="transitive_hypernym_automaton.yaml", help="Where to write the generated automaton script")
    parser.add_argument("--apply", action="store_true", help="Actually run the script through ewe_cli (default: only generate it)")
    args = parser.parse_args()

    synsets_by_ili = load_synsets_by_ili(args.wordnet_dir)
    con = sqlite3.connect(args.wn_db)

    triples = find_transitive_hypernyms(con, synsets_by_ili)
    actions = build_automaton(triples)
    with open(args.script_out, "w", encoding="utf-8") as f:
        yaml.safe_dump(actions, f, allow_unicode=True, sort_keys=False)

    print(f"{len(triples)} transitive hypernym relation(s) found -> {args.script_out}")
    for source, target in triples:
        print(f"  {source} =hypernym=> {target}")

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
