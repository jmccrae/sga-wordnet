"""Check that every accepted/corrected sense's WordNet part of speech
matches the Old Irish lemma's own grammatical part of speech, as tagged
in the corpus (CoNLL-U `upos`, carried into data/sga_incomplete.teanga.yaml).

A sense key encodes its own English WordNet part of speech (noun, verb,
adjective, adjective satellite, or adverb) - but nothing checks that
against how the Old Irish word is actually used. This matters in
practice: several sense_corrections.csv entries turned out to shift part
of speech relative to the original (rejected) sense - e.g. correcting to
a *noun* "active voice"/"passive voice" sense for a lemma the corpus
tags ADJ, where an adjectival WordNet sense would fit its actual usage
better. This script finds all such mismatches systematically, across
both outright-accepted and corrected rows.

For every (lemma, sense key) that ends up accepted - outright, or via
sense_corrections.csv - this locates its corpus occurrences the same way
scripts/annotate_corpus_senses.py does (word-alignment + WSD candidates),
reads each occurrence's `upos` tag, maps it to a WordNet pos, and flags
any (lemma, sense key) where that never matches the sense's own pos.
"""

import argparse
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import teanga

sys.path.insert(0, str(Path(__file__).parent))
from annotate_corpus_senses import (
    DEFAULT_ALIGN,
    DEFAULT_SENSES,
    DEFAULT_TEANGA,
    load_alignments,
    load_senses,
)
from populate_wordnet import (
    DEFAULT_CORRECTIONS,
    DEFAULT_WN_DB,
    DEFAULT_XLSX,
    load_corrections,
    load_sense_key_map,
    resolve_sense,
)

# CoNLL-U/UD upos -> WordNet pos. Function words (ADP, DET, PRON, ...) have
# no WordNet equivalent and are left unmapped - they shouldn't have been
# WSD-matched to a content-word sense in the first place, and any that did
# get accepted will show up as a mismatch against whatever pos they land on.
UPOS_TO_WN_POS = {
    "NOUN": "n",
    "PROPN": "n",
    "VERB": "v",
    "AUX": "v",
    "ADJ": "a",
    "ADV": "r",
}


def collect_upos_by_occurrence(corpus, alignments, senses, sense_key_map):
    """(lemma, original_sense_key) -> Counter of UD upos tags seen at its
    matched Old Irish token occurrences."""
    doc_ids = list(corpus.doc_ids)
    result = defaultdict(Counter)
    for doc_id, by_english, sense_entries in zip(doc_ids, alignments, senses):
        doc = corpus.doc_by_id(doc_id)
        lemmas = doc.lemma
        upos = doc.upos
        for entry in sense_entries:
            if not entry["matches"]:
                continue
            original_sk = entry["matches"][0]["sk"]
            for english_idx in entry["indexes"]:
                for irish_idx in by_english.get(english_idx, []):
                    if irish_idx >= len(lemmas):
                        continue
                    lemma = lemmas[irish_idx]
                    if (lemma, original_sk) not in sense_key_map:
                        continue
                    result[(lemma, original_sk)][upos[irish_idx]] += 1
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsx", default=DEFAULT_XLSX)
    parser.add_argument("--corrections", default=DEFAULT_CORRECTIONS)
    parser.add_argument("--wn-db", default=DEFAULT_WN_DB, help="Path to a `wn` library sqlite database")
    parser.add_argument("--teanga", default=DEFAULT_TEANGA)
    parser.add_argument("--align", default=DEFAULT_ALIGN)
    parser.add_argument("--senses", default=DEFAULT_SENSES)
    args = parser.parse_args()

    corrections = load_corrections(args.corrections)
    sense_key_map = load_sense_key_map(args.xlsx, corrections)
    con = sqlite3.connect(args.wn_db)

    corpus = teanga.read_yaml(args.teanga)
    alignments = load_alignments(args.align)
    senses = load_senses(args.senses)

    upos_by_occurrence = collect_upos_by_occurrence(corpus, alignments, senses, sense_key_map)

    mismatches = []
    unmatched = []
    for (lemma, original_sk), effective_sk in sorted(sense_key_map.items()):
        resolved = resolve_sense(con, effective_sk)
        if resolved is None:
            continue
        _oewn_id, pos, _lexfile, _ili, _definition, _english_lemmas = resolved
        wn_pos = "a" if pos == "s" else pos

        upos_counts = upos_by_occurrence.get((lemma, original_sk))
        if not upos_counts:
            unmatched.append((lemma, original_sk, effective_sk))
            continue

        corpus_pos = {UPOS_TO_WN_POS[u] for u in upos_counts if u in UPOS_TO_WN_POS}
        if corpus_pos and wn_pos not in corpus_pos:
            mismatches.append((lemma, original_sk, effective_sk, wn_pos, dict(upos_counts)))

    print(f"{len(sense_key_map)} accepted sense annotation(s) checked")
    print(f"{len(mismatches)} part-of-speech mismatch(es):")
    for lemma, original_sk, effective_sk, wn_pos, upos_counts in mismatches:
        corrected = " (via correction)" if effective_sk != original_sk else ""
        print(f"  {lemma}: sense {effective_sk!r}{corrected} is pos={wn_pos!r}, but corpus upos is {upos_counts}")

    if unmatched:
        print(f"\n{len(unmatched)} accepted sense(s) with no corpus occurrence located (can't check):")
        for lemma, original_sk, effective_sk in unmatched:
            print(f"  {lemma} {original_sk!r} -> {effective_sk!r}")


if __name__ == "__main__":
    main()
