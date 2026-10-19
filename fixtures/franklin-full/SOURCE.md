# Franklin, full text

`autobiography.txt` is the whole *Autobiography of Benjamin Franklin* as edited by Frank Woodworth Pine, Project Gutenberg eBook #20203 (public domain in the United States): chapters I–XIX, from the 1771 letter to his son to the unfinished account of 1757. The editor's appendix (letters, *The Way to Wealth*) is not included. Pine's edition already omits the letters from Abel James and Benjamin Vaughan that Franklin inserted between the first and second parts.

`clean.py` builds it from the Gutenberg plain text (`python3 clean.py pg20203.txt autobiography.txt`). It removes chapter numbers and headings, datelines, every line indented four spaces or more (the editor's footnotes, and with them some verse and an epitaph Franklin quotes), the editor's facsimile of two almanac pages with its transcriber's note, illustration captions set in brackets, transcriber's notes, the editor's part markers, inline footnote markers and italic underscores. Franklin's daily-schedule table loses its indented rows; its unindented rows remain as a few garbled lines in era e4. Each paragraph is joined onto one line. No sentence is edited. Chapters I–IV match `fixtures/franklin/autobiography.txt` paragraph for paragraph, except that the excerpt keeps one transcriber's note.

`eras.json` splits the record into six life periods along chapter boundaries:

| Era | Chapters | Paragraphs |
|---|---|---|
| e1 Boston boyhood and apprenticeship, 1706–1723 | I–II | p0001–p0044 |
| e2 Arrival in Philadelphia and first return to Boston, 1723–1724 | III–V | p0045–p0083 |
| e3 London and beginning business, 1724–1730 | VI–VII | p0084–p0149 |
| e4 Business success and the plan for moral perfection, 1730–1733 | VIII–IX | p0150–p0257 |
| e5 The almanac, public affairs and defence of the province, 1732–1753 | X–XIII | p0258–p0342 |
| e6 Albany plan, proprietary quarrels, Braddock's expedition, science and the London agency, 1754–1757 | XIV–XIX | p0343–p0443 |

The models know this book, and restore names from it. A run on it shows what two model families agree Franklin's own account shows; it does not test whether the method is blind.
