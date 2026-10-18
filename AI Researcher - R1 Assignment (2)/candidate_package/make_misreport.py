"""Misclassified diagnostic report: answers_1x/3x/10x vs visible_key.

Writes misclassified_report.xlsx (real .xlsx, stdlib only).
Sheets: Summary, Miss_1x, Miss_3x, Miss_10x.
Miss sheets have 4 columns: item | predicted | ground_truth | analysis.
Usage: python make_misreport.py
"""
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))


def load(n):
    with open(os.path.join(ROOT, n), encoding="utf-8") as f:
        return json.load(f)


def norm(a):
    if not isinstance(a, dict):
        return None
    out = {}
    for p, fs in a.items():
        if not isinstance(fs, dict):
            return None
        out[str(p)] = tuple(sorted((str(k), str(v)) for k, v in fs.items()))
    return out


def match(truth, guess):
    if not isinstance(guess, dict) or set(guess) != set(truth):
        return False
    for p, fields in truth.items():
        g = dict(guess[p])
        if any(g.get(f) != v for f, v in fields):
            return False
    return True


HEDGES = ("i'm fairly sure ", "from what i recall, ", "as far as i know, ",
          "i believe ", "going off the roster, ", "if memory serves, ",
          "my recollection is that ", "unless i have this wrong, ",
          "speaking from memory, ", "i'm reasonably confident ")


def squash(s):
    return " ".join(str(s).split()).casefold()


def squash_stmt(s):
    s = squash(s)
    head, sep, tail = s.partition(": ")
    if sep and tail and len(head) < 60:
        s = tail
    for h in HEDGES:
        if s.startswith(h):
            return s[len(h):]
    return s


def short_assign(a):
    try:
        return "; ".join("%s=%s%s" % (p, f.get("block", "?"),
                                      ("/" + f["station"]
                                       if "station" in f else ""))
                         for p, f in sorted(a.items()))
    except Exception:
        return "?"


def pred_summary(got):
    if not isinstance(got, dict):
        return "missing/unparsed"
    c = got.get("case")
    if c == "unique":
        a = got.get("assignment")
        if a is None:
            l = got.get("assignments")
            a = l[0] if isinstance(l, list) and len(l) == 1 else None
        return "unique: %s" % (short_assign(a) if a else "?")
    if c == "ambiguous":
        l = got.get("assignments")
        if not isinstance(l, list):
            return "ambiguous: ?"
        return "ambiguous[%d]: %s" % (
            len(l), " | ".join(short_assign(x) for x in l[:2]))
    if c == "inconsistent":
        cs = got.get("conflicts")
        if cs is None:
            cs = got.get("conflict_lines")
        if not isinstance(cs, list):
            return "inconsistent: ?"
        return "inconsistent[%d cited]: %s" % (len(cs), " // ".join(cs[:3]))
    return "unparsed (case=%r)" % (c,)


def truth_summary(k):
    c = k.get("case")
    if c == "unique":
        al = k.get("assignments") or []
        return "unique: %s" % (short_assign(al[0]) if al else "?")
    if c == "ambiguous":
        al = k.get("assignments") or []
        return "ambiguous[%d]" % len(al)
    cores = k.get("conflict_line_sets") or []
    return "inconsistent[%d min-set(s), smallest=%d]" % (
        len(cores), min((len(s) for s in cores), default=0))


def analyze(iid, k, got):
    if not isinstance(got, dict) or got.get("case") not in (
            "unique", "ambiguous", "inconsistent"):
        return ("missing/unparsed prediction; scorer counts 0. Check diag "
                "for transient/budget error on this id.")
    gc, tc = got["case"], k.get("case")
    if gc != tc:
        if tc == "inconsistent":
            return ("wrong case: predicted %s but key is inconsistent. "
                    "Solver count/MUS off; extraction over/under-constrained."
                    % gc)
        if tc == "unique":
            return ("wrong case: predicted %s but key is unique. Solution "
                    "count != 1 (missed or extra constraint)." % gc)
        return ("wrong case: predicted %s but key is ambiguous. Need EVERY "
                "solution, no extras." % gc)
    if tc == "unique":
        truth = norm((k.get("assignments") or [{}])[0])
        a = got.get("assignment")
        if a is None:
            l = got.get("assignments")
            a = l[0] if isinstance(l, list) and len(l) == 1 else None
        if not match(truth, norm(a) or {}):
            return ("unique case right but assignment differs (block/station "
                    "cell mismatch).")
        return "exact (should not be listed)"
    if tc == "ambiguous":
        truth = [norm(a) for a in (k.get("assignments") or [])]
        lst = got.get("assignments")
        if not isinstance(lst, list):
            return "ambiguous case right but assignments unparsable."
        payload = [norm(x) for x in lst]
        if len(payload) != len(truth):
            return ("ambiguous case right but cardinality wrong: %d vs %d "
                    "(need EVERY solution, no extras)." % (len(payload),
                                                           len(truth)))
        for t in truth:
            if not any(match(t, p) for p in payload):
                return ("ambiguous case right but a true solution missing "
                        "(dropped constraint).")
        return "ambiguous case right but extra non-solution included."
    cores = k.get("conflict_line_sets") or []
    cs = got.get("conflicts")
    if cs is None:
        cs = got.get("conflict_lines", [])
    if not isinstance(cs, list) or not cs:
        return ("inconsistent case right but no conflicts cited (label-only "
                "scores 0; need a minimal set).")
    gnorm = [squash_stmt(c) for c in cs]
    for core in cores:
        wnorm = [squash_stmt(w) for w in core]
        if (len(gnorm) == len(wnorm) and len(set(gnorm)) == len(gnorm)
                and all(sum(1 for w in wnorm if w in c) == 1
                        for c in gnorm)
                and all(sum(1 for c in gnorm if w in c) >= 1
                        for w in wnorm)):
            return "exact (should not be listed)"
    if len(set(gnorm)) != len(gnorm):
        return "inconsistent case right but duplicate citations."
    return ("inconsistent case right but cited set is not an exact minimal "
            "conflicting set (too many/too few/wrong lines).")


def is_mis(iid, k, got):
    return analyze(iid, k, got) != "exact (should not be listed)"


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def col_letter(i):
    s = ""
    while True:
        s = chr(65 + i % 26) + s
        i = i // 26 - 1
        if i < 0:
            return s


def sheet_xml(rows):
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/'
           'spreadsheetml/2006/main"><sheetData>']
    for r, row in enumerate(rows, 1):
        out.append('<row r="%d">' % r)
        for c, v in enumerate(row):
            ref = "%s%d" % (col_letter(c), r)
            style = ' s="1"' if r == 1 else ""
            out.append('<c r="%s"%s t="inlineStr"><is><t>%s</t></is></c>'
                       % (ref, style, esc(v if v is not None else "")))
        out.append('</row>')
    out.append('</sheetData><cols><col min="1" max="1" width="12"/>'
               '<col min="2" max="3" width="60"/>'
               '<col min="4" max="4" width="80"/></cols></worksheet>')
    return "".join(out)


def write_xlsx(path, sheets):
    import zipfile
    ct = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
          'content-types">',
          '<Default Extension="rels" ContentType="application/vnd.'
          'openxmlformats-package.relationships+xml"/>',
          '<Default Extension="xml" ContentType="application/xml"/>']
    for i, _ in enumerate(sheets, 1):
        ct.append('<Override PartName="/xl/worksheets/sheet%d.xml" '
                  'ContentType="application/vnd.openxmlformats-'
                  'officedocument.spreadsheetml.worksheet+xml"/>' % i)
    ct += ['<Override PartName="/xl/workbook.xml" ContentType="application/'
           'vnd.openxmlformats-officedocument.spreadsheetml.sheet+xml"/>',
           '<Override PartName="/xl/styles.xml" ContentType="application/'
           'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
           '</Types>']
    wb = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
          '<workbook xmlns="http://schemas.openxmlformats.org/'
          'spreadsheetml/2006/main" xmlns:r="http://schemas.'
          'openxmlformats.org/officeDocument/2006/relationships">'
          '<sheets>']
    for i, (nm, _) in enumerate(sheets, 1):
        wb.append('<sheet name="%s" sheetId="%d" r:id="rId%d"/>'
                  % (esc(nm), i, i))
    wb.append('</sheets></workbook>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/'
            'package/2006/relationships"><Relationship Id="rId0" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>')
    wrels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             '<Relationships xmlns="http://schemas.openxmlformats.org/'
             'package/2006/relationships">']
    for i, _ in enumerate(sheets, 1):
        wrels.append('<Relationship Id="rId%d" Type="http://schemas.'
                     'openxmlformats.org/officeDocument/2006/relationships/'
                     'worksheet" Target="worksheets/sheet%d.xml"/>'
                     % (i, i))
    wrels.append('</Relationships>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet xmlns="http://schemas.openxmlformats.org/'
              'spreadsheetml/2006/main"><fonts><font><b/></font><font/>'
              '</fonts><fills><fill><patternFill patternType="none"/>'
              '</fill><fill><patternFill patternType="gray125"/></fill>'
              '</fills><borders><border/></borders><cellStyleXfs count="1">'
              '<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
              '</cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" '
              'fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="0" '
              'fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
              '<cellStyles count="1"><cellStyle name="Normal" xfId="0" '
              'builtinId="0"/></cellStyles></styleSheet>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "".join(ct))
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", "".join(wb))
        z.writestr("xl/_rels/workbook.xml.rels", "".join(wrels))
        z.writestr("xl/styles.xml", styles)
        for i, (_, rows) in enumerate(sheets, 1):
            z.writestr("xl/worksheets/sheet%d.xml" % i, sheet_xml(rows))


def main():
    key = load("visible_key.json")
    subs = {"1x": load("answers_1x.json"),
            "3x": load("answers_3x.json"),
            "10x": load("answers_10x.json")}
    hdr = ["item", "predicted", "ground_truth", "analysis"]
    data = {}
    summary = [["budget", "n_items", "n_misclassified", "misclassified_ids"]]
    for b in ("1x", "3x", "10x"):
        sub = subs[b]
        rows = [hdr]
        miss = []
        for iid in sorted(key):
            k = key[iid]
            got = sub.get(iid)
            if analyze(iid, k, got) != "exact (should not be listed)":
                miss.append(iid)
                rows.append([iid, pred_summary(got), truth_summary(k),
                             analyze(iid, k, got)])
        data[b] = rows
        summary.append([b, str(len(key)), str(len(miss)), ", ".join(miss)])
    out = os.path.join(ROOT, "misclassified_report.xlsx")
    write_xlsx(out, [("Summary", summary), ("Miss_1x", data["1x"]),
                     ("Miss_3x", data["3x"]), ("Miss_10x", data["10x"])])
    for b in ("1x", "3x", "10x"):
        print("%s: %d misclassified of %d" % (b, len(data[b]) - 1,
                                              len(key)))
    print("wrote", out)


if __name__ == "__main__":
    main()
