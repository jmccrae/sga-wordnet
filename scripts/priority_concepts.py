"""Rank English WordNet concepts worth translating next, to grow this
wordnet's link structure rather than just its raw synset count.

Two metrics, both computed from the hypernym graph in a local `wn`
library database (see https://github.com/goodmami/wn):

  - top_concept: English WordNet's `noun.Tops` lexicographer file - the
    ~51 canonical "unique beginner" concepts (entity, abstraction, event,
    ...) every noun hypernym chain eventually traces back to. Only a
    handful are in this wordnet so far; translating the rest gives every
    future noun a foundation to attach to. Ranked by how many of our
    existing synsets already descend from it (via hypernym) - the ones
    that would validate/connect the most existing work first.
  - bridging: everything else that is a hypernym (direct or transitive)
    of the most existing synsets here, excluding noun.Tops synsets
    (already covered above). Translating one of these creates a hypernym
    link for every existing synset beneath it in one go, rather than one
    link per translation.

Both use `ili` to match English synsets against src/yaml/*.yaml's own
`ili` fields, the same join scripts/annotate_corpus_senses.py and
scripts/link_existing_synsets.py use (see their docstrings for why).

Writes data/priority_concepts.csv, meant for manual review - not applied
automatically, since choosing (and translating) an Old Irish lemma for
each concept is a linguistic judgement call, not something to automate.
"""

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from annotate_corpus_senses import DEFAULT_WORDNET_DIR, load_synsets_by_ili
from populate_wordnet import DEFAULT_WN_DB

DEFAULT_OUTPUT = "data/priority_concepts.csv"
TOP_CONCEPT_LEXFILE = "noun.Tops"


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


def ancestors_of(rowid, parents, cache):
    if rowid in cache:
        return cache[rowid]
    result = set()
    for parent in parents.get(rowid, []):
        result.add(parent)
        result |= ancestors_of(parent, parents, cache)
    cache[rowid] = result
    return result


def synset_info(con, rowid):
    """(ili, pos, lexfile, definition, english_lemmas) for a synset rowid."""
    cur = con.execute(
        """
        select ili.id, syn.pos, lf.name, d.definition
        from synsets syn
        join lexfiles lf on syn.lexfile_rowid = lf.rowid
        left join ilis ili on syn.ili_rowid = ili.rowid
        left join definitions d on d.synset_rowid = syn.rowid
        where syn.rowid = ?
        """,
        (rowid,),
    )
    ili, pos, lexfile, definition = cur.fetchone()
    cur = con.execute(
        """
        select f.form
        from senses s
        join entries e on s.entry_rowid = e.rowid
        join forms f on f.entry_rowid = e.rowid and f.rank = 0
        where s.synset_rowid = ?
        order by s.synset_rank
        """,
        (rowid,),
    )
    english_lemmas = [r[0] for r in cur.fetchall()]
    return ili, pos, lexfile, definition, english_lemmas


def rank_top_concepts(con, parents, our_rowids):
    cur = con.execute(
        """
        select syn.rowid, ili.id
        from synsets syn
        join lexfiles lf on syn.lexfile_rowid = lf.rowid
        left join ilis ili on syn.ili_rowid = ili.rowid
        where lf.name = ?
        """,
        (TOP_CONCEPT_LEXFILE,),
    )
    top_concepts = cur.fetchall()

    cache = {}
    ranked = []
    for rowid, ili in top_concepts:
        if rowid in our_rowids:
            continue
        descendant_count = sum(1 for our_rowid in our_rowids if rowid in ancestors_of(our_rowid, parents, cache))
        ranked.append((descendant_count, rowid))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]))
    return ranked


def rank_bridging_concepts(con, parents, our_rowids, top_concept_rowids):
    cache = {}
    counts = {}
    for our_rowid in our_rowids:
        for ancestor in ancestors_of(our_rowid, parents, cache):
            if ancestor in our_rowids or ancestor in top_concept_rowids:
                continue
            counts[ancestor] = counts.get(ancestor, 0) + 1
    ranked = [(count, rowid) for rowid, count in counts.items()]
    ranked.sort(key=lambda pair: (-pair[0], pair[1]))
    return ranked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wn-db", default=DEFAULT_WN_DB, help="Path to a `wn` library sqlite database")
    parser.add_argument("--wordnet-dir", default=DEFAULT_WORDNET_DIR, help="Directory containing settings.toml / src/yaml")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    synsets_by_ili = load_synsets_by_ili(args.wordnet_dir)
    con = sqlite3.connect(args.wn_db)

    cur = con.execute("select syn.rowid, ili.id from synsets syn join ilis ili on syn.ili_rowid = ili.rowid")
    our_rowids = {rowid for rowid, ili in cur.fetchall() if ili in synsets_by_ili}

    cur = con.execute(
        "select syn.rowid from synsets syn join lexfiles lf on syn.lexfile_rowid = lf.rowid where lf.name = ?",
        (TOP_CONCEPT_LEXFILE,),
    )
    top_concept_rowids = {r[0] for r in cur.fetchall()}

    parents = build_hypernym_parents(con)

    top_concepts = rank_top_concepts(con, parents, our_rowids)
    bridging_concepts = rank_bridging_concepts(con, parents, our_rowids, top_concept_rowids)

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "synset_id", "pos", "lexfile", "category", "link_count", "english_lemmas", "definition"])
        rank = 1
        for link_count, rowid in top_concepts:
            _ili, pos, lexfile, definition, english_lemmas = synset_info(con, rowid)
            cur = con.execute("select id from synsets where rowid = ?", (rowid,))
            synset_id = cur.fetchone()[0]
            writer.writerow([rank, synset_id, pos, lexfile, "top_concept", link_count, ", ".join(english_lemmas), definition])
            rank += 1
        for link_count, rowid in bridging_concepts:
            _ili, pos, lexfile, definition, english_lemmas = synset_info(con, rowid)
            cur = con.execute("select id from synsets where rowid = ?", (rowid,))
            synset_id = cur.fetchone()[0]
            writer.writerow([rank, synset_id, pos, lexfile, "bridging", link_count, ", ".join(english_lemmas), definition])
            rank += 1

    print(f"{len(top_concepts)} untranslated top concept(s), {len(bridging_concepts)} bridging concept(s) -> {args.output}")


if __name__ == "__main__":
    main()
