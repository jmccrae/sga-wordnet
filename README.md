# Old Irish Wordnet

A wordnet for Old Irish (ISO 639-3: `sga`), linked to the [Open English
Wordnet](https://github.com/globalwordnet/english-wordnet) (OEWN) through
ILI identifiers. Browse it at <https://goidelc.teanga.io/>.

Each synset has the definition, part of speech and ILI of the OEWN synset it
was derived from, with Old Irish lemmas as its members. Hypernym and other
relations are included wherever both endpoints exist in the wordnet. Lemmas that are reconstructed rather than attested are
flagged with the `reconstructed` attribute (WN-LMF 1.5 `Lemma/@reconstructed`).

## Provenance

The wordnet was induced with
[WISTERIA](https://github.com/jmccrae/wisteria) (Wordnet Induction from
Sense-Tagged Resources by Interlingual Alignment), which follows the *expand*
method: an Old Irish–English parallel corpus is word-aligned and the English
side is sense-disambiguated, so Old Irish lemmas can be attached to the OEWN
synsets they translate. The corpus is the Old Irish [Universal
Dependencies](https://universaldependencies.org/) treebank by Adrian Doyle.
The induced candidates were then manually reviewed and corrected.

The intermediate data from this process is kept in `data/`. The scripts that
built the wordnet from it were removed once it had been built; they remain in
the git history before the cleanup, and WISTERIA covers the induction
pipeline.

## Contents

| Path | Description |
|---|---|
| `src/yaml/` | The wordnet, in the YAML layout of the [English WordNet source](https://github.com/globalwordnet/english-wordnet/tree/main/src/yaml): `entries-*.yaml`, one file per lexicographer file (`noun.*`, `verb.*`, `adj.*`, `adv.*`) and `frames.yaml`. |
| `data/OI_Combined.conllu` | The full source corpus, in CoNLL-U with English translations. |
| `data/OI_Combined.wisteria.yaml` | WISTERIA's annotation of that corpus: word alignments to the English translation and the OEWN senses of the English words. |
| `data/OI_Combined.teanga.yaml` | The corpus as [Teanga](https://github.com/teangaNLP/teanga) YAML, with tokens tagged by wordnet synset (`sga_key` layer), for EWE's concordance view. Built by `scripts/build_corpus.py`. |
| `data/sga_incomplete.conllu` | The first, smaller release of the corpus that the first batch of candidates came from. |
| `data/sga_incomplete.{align,en-ga}` | Word alignments (fast_align) and the Old Irish–English bitext they were computed from. |
| `data/sga_incomplete.senses`, `data/sga_incomplete.results_AD.xlsx` | Word sense disambiguation candidates for the English side, with the annotator's verdicts. |
| `data/sense_corrections.csv`, `data/pos_corrections.csv` | Manual corrections to the disambiguated senses and parts of speech. |
| `data/OI_Combined.review.csv`, `data/OI_Combined.corrections.csv` | A second batch of reviewed candidates and how the reviewer's notes were acted on. |
| `data/priority_concepts.csv` | English synsets ranked by how useful they are to translate next. |
| `downloads.toml` | The released versions of the wordnet. |
| `settings.toml`, `branding/` | Configuration and branding for the [EWE](https://github.com/jmccrae/ewe) wordnet editor. |

## Corpus

`data/OI_Combined.teanga.yaml` is generated, so rebuild it after changing
the wordnet's entries:

```sh
uv run scripts/build_corpus.py   # needs a `wn` database with OEWN (--wn-db, default ~/.wn_data/wn.db)
```

A token is tagged with one of its lemma's synsets when WISTERIA aligned it
to an English word with that sense, or to an English word that is a member
of exactly one of the candidate synsets, or when the lemma has a single
synset of a matching part of speech. Lemmas left with no occurrence are
then tagged with their first synset; the script prints those, and the
entries that do not occur in the corpus at all.

## Using the data

The wordnet is edited with [EWE](https://github.com/jmccrae/ewe): open this
directory (it contains `settings.toml`) in the desktop app, or serve it from
an EWE checkout. Released versions are published as YAML, WN-LMF XML and
RDF/Turtle (see `downloads.toml`). To produce a release from a commit:

```sh
uv run scripts/build_downloads.py add 0.2 --commit <sha>   # defaults to HEAD
EWE=/path/to/ewe uv run scripts/build_downloads.py build   # --force rebuilds
```

`EWE` may be the `ewe-cli` binary or an EWE checkout with a release build;
otherwise `ewe-cli` is taken from the `PATH`. A `Dockerfile` packages the
wordnet with a read-only EWE web server.

## License

[Creative Commons Attribution 4.0
International](https://creativecommons.org/licenses/by/4.0/) (see `LICENSE`),
the same license as the Open English Wordnet. The logo and favicon in
`branding/` are a separate asset: a half-uncial *g* from [Wikimedia
Commons](https://commons.wikimedia.org/wiki/File:Half-uncial,_g,_Roman_Uncial_Modern.svg).
