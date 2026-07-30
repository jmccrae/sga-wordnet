"""Add a sense-annotation layer to the Teanga corpus for EWE's concordance view.

EWE looks up where a synset occurs in the corpus via an "element" layer
named "{id_prefix}_key" (see key_layer_name in ewe_dioxus's
backend/senses.rs), holding one project-prefixed synset id per tagged
token (e.g. "sga-80714279-n"), ";"-joined if more than one sense applies.
Written as sparse (index, value) pairs (teanga.rs's `Layer::L1S`), not one
entry per token - see annotate()'s docstring for why that distinction
matters.

data/sga_incomplete.senses records, for every content word in each
sentence's ENGLISH translation, a ranked list of WordNet sense candidates -
the top candidate (highest similarity) is the sense the WSD pipeline
actually proposed, i.e. the one recorded in data/sga_incomplete.
results_AD.xlsx's Sense Key column. data/sga_incomplete.align word-aligns
the Old Irish lemma sequence (source) to that same tokenized English
translation (target) as fast_align's default "src-trg" pairs. Combining
the two locates, for each Old Irish token, which proposed sense (if any)
applies to it; running that through populate_wordnet.load_sense_key_map
(the same accepted-outright-or-corrected mapping populate_wordnet.py
itself uses) gives the sense key actually imported.

That sense key still needs turning into *our* synset id. Project sense ids
in src/yaml/entries-*.yaml do NOT reliably reuse the source English sense
key's lex_id (EWE assigns each new sense the next free lex_id for that
lemma/lexfile, independently of the source's own numbering - e.g. the
source sense construction%1:10:01:: became imḟognam%1:10:00:: here, since
it was imḟognam's first sense in that lexfile). The robust join is via
ili instead: resolve the sense key to its English synset's ili via the
same local `wn` database populate_wordnet.py uses, then match that ili
against src/yaml/{noun,verb,adj,adv}.*.yaml's own `ili` fields (set by
populate_wordnet.py's change_ili action, so it's exactly the same value).

Run this after scripts/conllu_to_teanga.py (which this reads and
overwrites by default) and after scripts/populate_wordnet.py --apply (its
output, src/yaml/*.yaml, is this script's other main input).
"""

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import teanga

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from populate_wordnet import (
    DEFAULT_CORRECTIONS,
    DEFAULT_WN_DB,
    DEFAULT_XLSX,
    load_corrections,
    load_sense_key_map,
    resolve_sense,
)

DEFAULT_TEANGA = "data/sga_incomplete.teanga.yaml"
DEFAULT_ALIGN = "data/sga_incomplete.align"
DEFAULT_SENSES = "data/sga_incomplete.senses"
DEFAULT_SYNSET_GLOBS = ("noun.*.yaml", "verb.*.yaml", "adj.*.yaml", "adv.*.yaml")
DEFAULT_WORDNET_DIR = "."
DEFAULT_ID_PREFIX = "sga"


def load_synsets_by_ili(wordnet_dir, synset_globs=DEFAULT_SYNSET_GLOBS):
    """ili -> (synset id, member lemmas), read from src/yaml/{noun,verb,adj,adv}.*.yaml."""
    lookup = {}
    yaml_dir = Path(wordnet_dir) / "src" / "yaml"
    for pattern in synset_globs:
        for path in sorted(yaml_dir.glob(pattern)):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for synset_id, synset in data.items():
                ili = synset.get("ili")
                if ili:
                    lookup[ili] = (synset_id, set(synset.get("members", [])))
    return lookup


def load_alignments(align_path):
    """One dict per corpus sentence: english token index -> Old Irish token
    index(es) aligned to it."""
    alignments = []
    with open(align_path, encoding="utf-8") as f:
        for line in f:
            by_english = defaultdict(list)
            for pair in line.split():
                irish_idx, english_idx = pair.split("-")
                by_english[int(english_idx)].append(int(irish_idx))
            alignments.append(by_english)
    return alignments


def load_senses(senses_path):
    with open(senses_path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def annotate(corpus, alignments, senses, sense_key_map, synsets_by_ili, con, id_prefix):
    """Adds a "{id_prefix}_key" layer to every tagged document in `corpus`
    (a teanga.Corpus, mutated in place), holding sparse (index, value)
    pairs - i.e. teanga.rs's `Layer::L1S` shape, `[[1, "sga-..."], [3,
    "sga-..."]]` - rather than a dense one-entry-per-token list, since a
    plain list of strings deserializes as the (unindexed) `Layer::LS`
    instead and ewe_dioxus's senses::all_concordance_lines only recognises
    L1S. Returns (tagged_token_count, tagged_doc_count)."""
    key_layer = f"{id_prefix}_key"
    doc_ids = list(corpus.doc_ids)
    if not (len(doc_ids) == len(alignments) == len(senses)):
        raise SystemExit(
            f"Sentence count mismatch: {len(doc_ids)} corpus docs, "
            f"{len(alignments)} alignment lines, {len(senses)} sense lines - "
            "these must all derive from the same conllu run"
        )

    # "element" (not "seq"): teanga's "seq" layers must have exactly one
    # entry per base-layer token (Python's teanga.Document enforces this;
    # most tokens have no sense here). "element" is teanga's layer type for
    # sparse, possibly-repeated per-token annotations - exactly this case -
    # and (like "seq") still lowers to teanga.rs's Layer::L1S.
    corpus.add_layer_meta(key_layer, layer_type="element", base="tokens", data="string")

    ili_cache = {}

    def ili_for(sense_key):
        if sense_key not in ili_cache:
            resolved = resolve_sense(con, sense_key)
            ili_cache[sense_key] = resolved[3] if resolved else None
        return ili_cache[sense_key]

    tagged_tokens = 0
    tagged_docs = 0
    for doc_id, by_english, sense_entries in zip(doc_ids, alignments, senses):
        doc = corpus.doc_by_id(doc_id)
        lemmas = doc.lemma
        keys_by_index = {}
        for entry in sense_entries:
            if not entry["matches"]:
                continue
            original_sk = entry["matches"][0]["sk"]
            for english_idx in entry["indexes"]:
                for irish_idx in by_english.get(english_idx, []):
                    if irish_idx >= len(lemmas):
                        continue
                    lemma = lemmas[irish_idx]
                    effective_sk = sense_key_map.get((lemma, original_sk))
                    if effective_sk is None:
                        continue
                    ili = ili_for(effective_sk)
                    if ili is None:
                        continue
                    synset = synsets_by_ili.get(ili)
                    if synset is None:
                        continue
                    synset_id, members = synset
                    if lemma not in members:
                        continue
                    tag = f"{id_prefix}-{synset_id}"
                    existing = keys_by_index.get(irish_idx)
                    if existing is None:
                        keys_by_index[irish_idx] = tag
                        tagged_tokens += 1
                    elif tag not in existing.split(";"):
                        keys_by_index[irish_idx] = existing + ";" + tag
        if keys_by_index:
            tagged_docs += 1
            doc[key_layer] = [[idx, keys_by_index[idx]] for idx in sorted(keys_by_index)]

    return tagged_tokens, tagged_docs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teanga", default=DEFAULT_TEANGA, help="Teanga corpus YAML to read and annotate")
    parser.add_argument("--align", default=DEFAULT_ALIGN)
    parser.add_argument("--senses", default=DEFAULT_SENSES)
    parser.add_argument("--xlsx", default=DEFAULT_XLSX)
    parser.add_argument("--corrections", default=DEFAULT_CORRECTIONS)
    parser.add_argument("--wn-db", default=DEFAULT_WN_DB, help="Path to a `wn` library sqlite database")
    parser.add_argument("--wordnet-dir", default=DEFAULT_WORDNET_DIR, help="Directory containing settings.toml / src/yaml (the populated wordnet)")
    parser.add_argument("--id-prefix", default=DEFAULT_ID_PREFIX, help="Must match settings.toml's id_prefix")
    parser.add_argument("--output", default=None, help="Defaults to overwriting --teanga in place")
    args = parser.parse_args()

    corrections = load_corrections(args.corrections)
    sense_key_map = load_sense_key_map(args.xlsx, corrections)
    synsets_by_ili = load_synsets_by_ili(args.wordnet_dir)
    con = sqlite3.connect(args.wn_db)

    corpus = teanga.read_yaml(args.teanga)
    alignments = load_alignments(args.align)
    senses = load_senses(args.senses)

    tagged_tokens, tagged_docs = annotate(
        corpus, alignments, senses, sense_key_map, synsets_by_ili, con, args.id_prefix
    )

    output = args.output or args.teanga
    corpus.to_yaml(output)

    print(f"Tagged {tagged_tokens} token(s) across {tagged_docs} document(s) -> {output}")


if __name__ == "__main__":
    main()
