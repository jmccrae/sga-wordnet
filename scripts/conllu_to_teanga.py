"""Convert the Old Irish UD corpus (CoNLL-U) to Teanga YAML.

Teanga (https://github.com/TeangaNLP/teanga) is the corpus format used by
the EWE Wordnet Editor's "where does this sense occur" lookups
(`corpus_source` in settings.toml).
"""

import argparse

from teanga.conllu import read_conllu_file

DEFAULT_INPUT = "data/sga_incomplete.conllu"
DEFAULT_OUTPUT = "data/sga_incomplete.teanga.yaml"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DEFAULT_INPUT, help="CoNLL-U source file")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Teanga YAML destination")
    args = parser.parse_args()

    corpus = read_conllu_file(args.input)
    corpus.to_yaml(args.output)
    print(f"Wrote {len(corpus.doc_ids)} documents to {args.output}")


if __name__ == "__main__":
    main()
