"""Generate the fast_align input bitext from the Old Irish UD corpus.

Each line pairs the Old Irish sentence (as its lemma sequence, one lemma per
CoNLL-U token) with the English `# translation` comment, tokenized with
NLTK's word_tokenize, separated by ` ||| ` (fast_align's expected format).
"""

import argparse

import conllu
import nltk
from nltk.tokenize import word_tokenize

DEFAULT_INPUT = "data/sga_incomplete.conllu"
DEFAULT_OUTPUT = "data/sga_incomplete.en-ga"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DEFAULT_INPUT, help="CoNLL-U source file")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="fast_align bitext destination")
    args = parser.parse_args()

    nltk.download("punkt_tab", quiet=True)

    with open(args.input, encoding="utf-8") as f:
        sentences = conllu.parse(f.read())

    with open(args.output, "w", encoding="utf-8") as out:
        for sentence in sentences:
            lemmas = " ".join(token["lemma"] for token in sentence)
            translation = " ".join(word_tokenize(sentence.metadata["translation"]))
            out.write(f"{lemmas} ||| {translation}\n")

    print(f"Wrote {len(sentences)} sentence pairs to {args.output}")


if __name__ == "__main__":
    main()
