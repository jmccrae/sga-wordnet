# /// script
# requires-python = ">=3.11"
# dependencies = ["teanga", "pyyaml"]
# ///
"""Build the Teanga corpus that EWE uses for its concordance view.

Converts data/OI_Combined.conllu (the Old Irish UD treebank, the same
corpus WISTERIA induced the wordnet from) to Teanga YAML and adds an
`sga_key` layer tagging each token with the synset it attests, as sparse
`[token index, "sga-<synset id>"]` pairs (EWE's `{id_prefix}_key` layer).

A token whose lemma is a wordnet entry is tagged with one of that entry's
synsets when either

1. *aligned*: WISTERIA aligned the token to an English word that it
   disambiguated to an OEWN synset with the same ILI as the entry's synset
   (data/OI_Combined.wisteria.yaml, `alignment` and `oewn_senses`);
2. *translated*: the token is aligned to an English word whose lemma is a
   member of exactly one of the entry's synsets' OEWN counterparts; or
3. *monosemous*: the entry has a single synset whose part of speech agrees
   with the token's UPOS; or, failing all of those,
4. *fallback*: the entry would otherwise have no occurrence at all, so
   tokens whose UPOS agrees with its part of speech are tagged with its
   first-listed synset. These are printed for review.

Multiword entries (e.g. "rann insce") are matched as runs of consecutive
lemmas and tagged on their first token, in preference to any single-word
tag there. Tokens that match neither rule (a polysemous entry with no
supporting alignment) are left untagged. A token never gets more than one
key, since EWE's index cannot find `;`-joined keys.

    uv run scripts/build_corpus.py [--wn-db ~/.wn_data/wn.db]

The ILIs of OEWN synsets are read from a `wn` library database containing
an OEWN lexicon. The script prints the non-reconstructed entries that it
could not find in the corpus.
"""

import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path

from teanga.conllu import read_conllu_str
from teanga.utils import TokenizationMismatch, find_spans

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONLLU = ROOT / "data/OI_Combined.conllu"
DEFAULT_WISTERIA = ROOT / "data/OI_Combined.wisteria.yaml"
DEFAULT_OUTPUT = ROOT / "data/OI_Combined.teanga.yaml"
DEFAULT_WN_DB = Path.home() / ".wn_data/wn.db"
YAML_DIR = ROOT / "src/yaml"
ID_PREFIX = "sga"
KEY_LAYER = f"{ID_PREFIX}_key"

UPOS_TO_POS = {
    "NOUN": {"n"},
    "PROPN": {"n"},
    "VERB": {"v"},
    "AUX": {"v"},
    "ADJ": {"a", "s"},
    "ADV": {"r"},
}


def load_wordnet():
    """Returns (lemma -> [synset id], synset id -> (pos, ili), reconstructed lemmas)."""
    synsets = {}
    for path in sorted(YAML_DIR.glob("*.*.yaml")):
        if path.name.startswith("entries-"):
            continue
        for synset_id, synset in (
            yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        ).items():
            synsets[synset_id] = (synset["partOfSpeech"], synset.get("ili"))
    senses = defaultdict(list)
    reconstructed = set()
    for path in sorted(YAML_DIR.glob("entries-*.yaml")):
        for lemma, by_pos in (
            yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        ).items():
            flags = []
            for entry in by_pos.values():
                flags.append(bool(entry.get("reconstructed")))
                for sense in entry.get("sense", []):
                    if sense["synset"] not in senses[lemma]:
                        senses[lemma].append(sense["synset"])
            if all(flags):
                reconstructed.add(lemma)
    return dict(senses), synsets, reconstructed


def oewn_ilis(wn_db, oewn_ids):
    con = sqlite3.connect(wn_db)
    ilis = {}
    for oewn_id in oewn_ids:
        row = con.execute(
            "select i.id from synsets s join ilis i on s.ili_rowid = i.rowid where s.id = ? limit 1",
            (oewn_id,),
        ).fetchone()
        if row:
            ilis[oewn_id] = row[0]
    return ilis


def oewn_lemmas(wn_db, ilis):
    """ili -> lowercased English lemmas of the OEWN synset with that ili."""
    con = sqlite3.connect(wn_db)
    lemmas = {}
    for ili in ilis:
        rows = con.execute(
            """
            select f.form from ilis i
            join synsets s on s.ili_rowid = i.rowid
            join senses se on se.synset_rowid = s.rowid
            join forms f on f.entry_rowid = se.entry_rowid and f.rank = 0
            where i.id = ?
            """,
            (ili,),
        ).fetchall()
        lemmas[ili] = {form.lower() for (form,) in rows}
    return lemmas


def fix_texts(conllu, wisteria_docs):
    """The CoNLL-U with each `# text` that does not tokenize-match its own
    tokens (a handful of sentences merge tokens without the space) replaced
    by the text WISTERIA reconstructed from the token forms."""
    blocks = conllu.strip("\n").split("\n\n")
    if len(blocks) != len(wisteria_docs):
        raise SystemExit(
            f"{len(blocks)} CoNLL-U sentences but {len(wisteria_docs)} WISTERIA documents"
        )
    fixed = 0
    for n, (block, wdoc) in enumerate(zip(blocks, wisteria_docs)):
        lines = block.split("\n")
        forms = [
            line.split("\t")[1] for line in lines if line and not line.startswith("#")
        ]
        for k, line in enumerate(lines):
            if line.startswith("# text = "):
                try:
                    find_spans(forms, line[len("# text = ") :])
                except TokenizationMismatch:
                    lines[k] = "# text = " + wdoc["text"]
                    fixed += 1
        blocks[n] = "\n".join(lines)
    return "\n\n".join(blocks) + "\n\n", fixed


def pos_agrees(upos, pos):
    return pos in UPOS_TO_POS.get(upos, set())


def tag_document(lemmas, upos, aligned_ilis, aligned_words, senses, synsets, english):
    """token index -> (synset id, rule) for one sentence."""
    tags = {}
    for i, lemma in enumerate(lemmas):
        candidates = senses.get(lemma)
        if not candidates:
            continue
        hits = [s for s in candidates if synsets[s][1] in aligned_ilis.get(i, ())]
        words = aligned_words.get(i, set())
        translated = [
            s for s in candidates if words & english.get(synsets[s][1], set())
        ]
        if len(hits) == 1:
            tags[i] = (hits[0], "aligned")
        elif len(translated) == 1:
            tags[i] = (translated[0], "translated")
        elif len(candidates) == 1 and pos_agrees(upos[i], synsets[candidates[0]][0]):
            tags[i] = (candidates[0], "monosemous")
    for lemma, candidates in senses.items():
        words = lemma.split()
        if len(words) < 2 or len(candidates) != 1:
            continue
        for i in range(len(lemmas) - len(words) + 1):
            if lemmas[i : i + len(words)] == words:
                tags[i] = (candidates[0], "multiword")
    return tags


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--conllu", type=Path, default=DEFAULT_CONLLU)
    parser.add_argument("--wisteria", type=Path, default=DEFAULT_WISTERIA)
    parser.add_argument("--wn-db", type=Path, default=DEFAULT_WN_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    senses, synsets, reconstructed = load_wordnet()
    wisteria = yaml.safe_load(args.wisteria.read_text(encoding="utf-8"))
    wisteria_docs = [doc for doc_id, doc in wisteria.items() if doc_id != "_meta"]
    conllu, fixed = fix_texts(args.conllu.read_text(encoding="utf-8"), wisteria_docs)
    corpus = read_conllu_str(conllu)
    doc_ids = list(corpus.doc_ids)
    if len(doc_ids) != len(wisteria_docs):
        raise SystemExit(
            f"{len(doc_ids)} CoNLL-U sentences but {len(wisteria_docs)} WISTERIA documents"
        )

    ilis = oewn_ilis(
        args.wn_db,
        {sk for doc in wisteria_docs for _, sk in doc.get("oewn_senses", [])},
    )
    english = oewn_lemmas(args.wn_db, {ili for _, ili in synsets.values() if ili})

    corpus.add_layer_meta(KEY_LAYER, layer_type="element", base="tokens", data="string")
    all_tags = {}
    for doc_id, wdoc in zip(doc_ids, wisteria_docs):
        doc = corpus.doc_by_id(doc_id)
        lemmas, upos = list(doc.lemma), list(doc.upos)
        if lemmas != wdoc["lemma"]:
            raise SystemExit(
                f"Document {doc_id} does not match its WISTERIA counterpart: {doc.text}"
            )
        english_ilis = defaultdict(set)
        for idx, sk in wdoc.get("oewn_senses", []):
            if sk in ilis:
                english_ilis[idx].add(ilis[sk])
        aligned_ilis = defaultdict(set)
        aligned_words = defaultdict(set)
        for src, tgt in wdoc.get("alignment", []):
            aligned_ilis[src] |= english_ilis[tgt]
            aligned_words[src].add(wdoc["translation_lemmas"][tgt].lower())

        all_tags[doc_id] = tag_document(
            lemmas, upos, aligned_ilis, aligned_words, senses, synsets, english
        )

    def attested_lemmas():
        attested = set()
        for doc_id, tags in all_tags.items():
            lemmas = corpus.doc_by_id(doc_id).lemma
            for i, (synset_id, _) in tags.items():
                for lemma, candidates in senses.items():
                    if (
                        synset_id in candidates
                        and lemmas[i : i + len(lemma.split())] == lemma.split()
                    ):
                        attested.add(lemma)
        return attested

    unattested = set(senses) - reconstructed - attested_lemmas()
    fallbacks = defaultdict(int)
    for doc_id, tags in all_tags.items():
        doc = corpus.doc_by_id(doc_id)
        for i, (lemma, pos) in enumerate(zip(doc.lemma, doc.upos)):
            if (
                lemma in unattested
                and i not in tags
                and pos_agrees(pos, synsets[senses[lemma][0]][0])
            ):
                tags[i] = (senses[lemma][0], "fallback")
                fallbacks[lemma] += 1

    counts = defaultdict(int)
    for doc_id, tags in all_tags.items():
        if tags:
            corpus.doc_by_id(doc_id)[KEY_LAYER] = [
                [i, f"{ID_PREFIX}-{tags[i][0]}"] for i in sorted(tags)
            ]
        for _, rule in tags.values():
            counts[rule] += 1

    corpus.to_yaml(str(args.output))
    print(
        f"Wrote {len(doc_ids)} documents to {args.output} ({fixed} texts rebuilt from their tokens)"
    )
    print(
        "Tagged tokens: "
        + ", ".join(f"{n} {rule}" for rule, n in sorted(counts.items()))
    )
    for lemma, n in sorted(fallbacks.items()):
        print(
            f"Fallback: {n} token(s) of {lemma} tagged {ID_PREFIX}-{senses[lemma][0]}"
        )
    missing = sorted(set(senses) - reconstructed - attested_lemmas())
    print(
        f"{len(missing)} non-reconstructed entries have no corpus occurrence: {', '.join(missing)}"
    )


if __name__ == "__main__":
    main()
