# Franklin fixture

`autobiography.txt` is an excerpt from *Autobiography of Benjamin Franklin*, edited by Frank Woodworth Pine, Project Gutenberg eBook #20203 (public domain in the United States). It holds chapters I–II (Boston, to the departure from the apprenticeship) and III–IV (arrival in Philadelphia, first visit back to Boston).

Cleaning, applied once by script: the editor's chapter numbers and headings, the dateline, indented footnote blocks, inline footnote markers (`[n]`), illustration captions and italic underscores were removed; each paragraph was rejoined onto one line, paragraphs separated by a blank line. No sentence was edited.

`eras.json` puts chapters I–II in `e1` (segments p0001–p0045) and III–IV in `e2` (p0046–p0076). `redactions.json` is a supplied, approved list that exercises redaction; it is not a claim about which names need protecting.

The models know this book. Runs on it test plumbing and zoning, not the method's validity.
