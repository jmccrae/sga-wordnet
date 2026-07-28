# sga-wordnet

A wordnet for Old Irish (ISO 639-3: `sga`), built with the [extend
method](https://globalwordnet.github.io/gwadoc/) from the [Open English
Wordnet](https://github.com/globalwordnet/english-wordnet).

## Method

1. Start from the Old Irish [Universal
   Dependencies](https://universaldependencies.org/) corpus developed by
   Adrian Doyle, which pairs Old Irish sentences with English translations.
2. Word-align the Old Irish and English sentences to find candidate
   translation pairs for each Old Irish lemma.
3. Run word sense disambiguation on the English side of each aligned pair to
   identify the Open English Wordnet sense it expresses.
4. Import that English Wordnet sense, replacing its English lemma with the
   corresponding Old Irish lemma from the corpus, to create the Old Irish
   entry.

The resulting wordnet is produced in the [Global WordNet Association
LMF](https://globalwordnet.github.io/schemas/) format so that it is
compatible with, and editable in, the [EWE Wordnet
Editor](https://github.com/jmccrae/ewe).

## Repository layout

- `data/` — working/derived data (e.g. the UD corpus in CoNLL-U format).
- `assets/` — source corpus files: alignments (`.align`), CoNLL-U parses,
  English translations (`.en`), Old Irish/English sentence pairs
  (`.en-ga`), and sense-disambiguation output (`.senses`, `.results.csv`).
- `main.py` — entry point for the pipeline.
- `src/yaml/` — the wordnet itself, in the same per-lexfile YAML layout as
  [english-wordnet's `src/yaml/`](https://github.com/globalwordnet/english-wordnet/tree/main/src/yaml)
  (`entries-{0,a-z}.yaml`, `noun.*.yaml`, `verb.*.yaml`, `adj.*.yaml`,
  `adv.*.yaml`, `frames.yaml`), populated as the pipeline imports senses.
  Each file starts out as an empty YAML mapping (`{}`) rather than a
  0-byte file — EWE only registers a lexfile as writable once it's parsed
  at least one YAML value, so a truly empty file silently blocks adding
  new synsets to it.
- `settings.toml` — configuration for the [EWE Wordnet
  Editor](https://github.com/jmccrae/ewe); paths inside it (`wordnet_source
  = "src/yaml"`) are relative to this file, so the repo can be opened
  directly from EWE's desktop app "Open Wordnet Folder" picker, or served
  with `dx serve` from a checkout of `ewe_dioxus` pointed at this
  directory. `wordnet.db`/`corpus.db`, the databases EWE builds from
  `src/yaml/`, are git-ignored and rebuilt locally on first run.

## Development

This project uses [uv](https://docs.astral.sh/uv/) for dependency
management.

```sh
uv sync
uv run main.py
```
