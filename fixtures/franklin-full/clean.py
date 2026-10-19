"""Build autobiography.txt from Project Gutenberg #20203 (Pine): `python3 clean.py pg20203.txt autobiography.txt`.

Keeps chapters I-XIX, one paragraph per line, and prints each chapter's first paragraph number (the era bounds).
"""
import re
import sys

ROMAN = re.compile(r"^[IVXL]+$")
EDITORIAL = ("[Illustration", "[Transcriber", "[_Continuation", "[Thus far")

lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
start = next(i for i, line in enumerate(lines) if line.strip() == "I" and i > 500)
end = next(i for i, line in enumerate(lines) if line.startswith("[Illustration: Medal with inscription"))
# Lines indented four spaces are the editor's footnotes (and the few verse and table lines set the same way).
body = [line for line in lines[start:end] if not line.startswith("    ")]

paragraphs, current = [], []
for line in [*body, ""]:
    if line.strip():
        current.append(line)
    elif current:
        paragraphs.append(current)
        current = []

out, chapters, after_number, in_plate = [], [], False, False
for para in paragraphs:
    # The editor's facsimile of two almanac pages, with its transcriber's note: from the caption to the note's "]".
    if para[0].startswith("Two pages from _Poor Richard's Almanac_"):
        in_plate = True
    if in_plate:
        in_plate = not para[-1].rstrip().endswith("]")
        continue
    if len(para) == 1 and ROMAN.match(para[0].strip()):
        chapters.append((para[0].strip(), len(out) + 1))
        after_number = True
        continue
    if after_number and all(line.strip().isupper() for line in para):  # the chapter heading
        after_number = False
        continue
    after_number = False
    if para[0].startswith("  ") and len(para) <= 2 and re.search(r"\d{4}", " ".join(para)):
        continue  # a dateline
    text = " ".join(line.strip() for line in para)
    if text.startswith(EDITORIAL):
        continue
    if text.startswith('[_"'):  # Franklin's own 1788 memorandum, set in editorial brackets
        text = re.sub(r"\]\s*(\[\d+\])?$", "", text[1:])
    out.append(re.sub(r"\[\d+\]", "", text).replace("_", "").replace(" [unfinished]", ""))

open(sys.argv[2], "w", encoding="utf-8").write("\n\n".join(out) + "\n")
print(f"{len(out)} paragraphs, {sum(len(t.split()) for t in out)} words")
for number, first in chapters:
    print(f"chapter {number}: p{first:04d}")
