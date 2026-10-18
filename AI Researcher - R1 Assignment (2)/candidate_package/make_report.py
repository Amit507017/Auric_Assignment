"""Write 1-page methodology report (real .docx, stdlib only)."""
import os

ROOT = os.path.dirname(os.path.abspath(__file__))

ROWS = [
    ("Budget", "Calls/item", "Macro EM", "Unique", "Ambiguous",
     "Inconsistent", "Cell acc"),
    ("1x", "1", "0.317", "0.25 (5/20)", "0.20 (4/20)", "0.50 (10/20)",
     "0.438"),
    ("3x", "1-3", "0.417", "0.35 (7/20)", "0.50 (10/20)", "0.40 (8/20)",
     "0.438"),
    ("10x", "1-10", "0.433", "0.35 (7/20)", "0.35 (7/20)", "0.60 (12/20)",
     "0.431"),
]


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def table_xml(rows):
    t = ['<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/>'
         '<w:tblW w:w="0" w:type="auto"/></w:tblPr><w:tblGrid>']
    t += ['<w:gridCol/>' for _ in rows[0]]
    t.append('</w:tblGrid>')
    for ri, row in enumerate(rows):
        t.append('<w:tr>')
        for cell in row:
            shd = ('<w:shd w:fill="D9E2F3" w:val="clear"/>' if ri == 0
                   else '')
            b = '<w:b/>' if ri == 0 else ''
            t.append('<w:tc><w:tcPr>%s</w:tcPr><w:p><w:r>%s<w:t>%s</w:t>'
                     '</w:r></w:p></w:tc>' % (shd, b, esc(cell)))
        t.append('</w:tr>')
    t.append('</w:tbl>')
    return "".join(t)


def para(text, style=None):
    if style == "Title":
        return ('<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:b>'
                '<w:sz w:val="32"/><w:t>%s</w:t></w:b></w:r></w:p>'
                % esc(text))
    if style == "H1":
        return ('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r>'
                '<w:b><w:t>%s</w:t></w:b></w:r></w:p>' % esc(text))
    return ('<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>'
            % esc(text))


def doc_xml():
    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             '<w:document xmlns:w="http://schemas.openxmlformats.org/'
             'wordprocessingml/2006/main"><w:body>']
    parts.append(para("Shift-Roster Reasoning under a Model-Call Budget",
                      "Title"))
    parts.append(para("Methodology: model extracts, solver decides", "H1"))
    parts.append(para(
        "Each puzzle gives a header (5 staff, 5 blocks, 3 stations with "
        "holders) plus about 20 shift-note lines. A weak model "
        "(ibm-granite/granite-4.2-8b) translates lines into a closed fact "
        "language (on, not_on, before, adj, between, station, station_not, "
        "st_before_p, p_before_st, st_before_st); fillers (trivia, history, "
        "counterfactuals, failed requests, open questions) map to no facts. "
        "Hedged assertions count as active constraints. A stdlib symbolic "
        "solver brute-forces block-by-station permutations (cap 6): 1 "
        "solution is unique, 2 to 4 is ambiguous, more than 4 is "
        "under-constrained, 0 is inconsistent with statement-level deletion "
        "MUS cited verbatim. The verdict never invents constraints."))
    parts.append(para(
        "1x uses one batched extraction call per item with no repair. 3x "
        "adds two staged reinferences: Call 2 re-asks flagged suspects; "
        "Call 3 verifies the single highest-impact line. 10x adds two "
        "independent full re-extractions (Calls 2-3, temporal and "
        "negation/sequence emphasis) with majority vote, then disagreement "
        "re-examination (Calls 4-6) and solver-guided verifies (Calls "
        "7-10) with no-progress early stop. Budget is enforced per item by "
        "a counter plus X-Item-Id header."))
    parts.append(para("Results (60 items: 20/20/20)", "H1"))
    parts.append(table_xml(ROWS))
    parts.append(para(
        "Extra budget helps most on inconsistent (0.50 to 0.60) and "
        "ambiguous recall, but exact ambiguous stays hard because it needs "
        "every solution with no extras, and inconsistent exactness needs "
        "minimal conflict sets. 3x captures most of the gain; 10x voting "
        "mainly stabilises holder and temporal calls."))
    parts.append('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                 '<w:pgMar w:top="720" w:right="720" w:bottom="720" '
                 'w:left="720"/></w:sectPr></w:body></w:document>')
    return "".join(parts)


def main():
    import zipfile
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
          'content-types"><Default Extension="rels" ContentType="application/'
          'vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/'
          'vnd.openxmlformats-officedocument.wordprocessingml.document.main'
          '+xml"/><Override PartName="/word/styles.xml" ContentType='
          '"application/vnd.openxmlformats-officedocument.wordprocessingml.'
          'styles+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/'
            'package/2006/relationships"><Relationship Id="rId1" Type='
            '"http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
    wrels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Relationships xmlns="http://schemas.openxmlformats.org/'
             'package/2006/relationships"></Relationships>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:styles xmlns:w="http://schemas.openxmlformats.org/'
              'wordprocessingml/2006/main"><w:style w:type="paragraph" '
              'w:styleId="Title"><w:name w:val="Title"/></w:style>'
              '<w:style w:type="paragraph" w:styleId="Heading1">'
              '<w:name w:val="heading 1"/></w:style></w:styles>')
    out = os.path.join(ROOT, "methodology_report.docx")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc_xml())
        z.writestr("word/_rels/document.xml.rels", wrels)
        z.writestr("word/styles.xml", styles)
    print("wrote", out)


if __name__ == "__main__":
    main()
