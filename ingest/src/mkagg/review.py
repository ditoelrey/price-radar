"""The manual-review tail, as a spreadsheet that goes out and comes back.

Automatic derivation answers 98.7 percent of the catalogue. What is left is
not a bug to be fixed with a better rule: it is articles whose own shops
never said what they are. A shelf reading "Текстил" and a title reading
"Adidas Adicolor" together name no garment, and no amount of pattern
matching will make them.

So the last mile is a person, and this is the shortest path to one: export
the open questions as a CSV, answer them in a spreadsheet, apply it back.
No admin panel, no authentication to get wrong, no public write endpoint --
the file is the interface, and it only runs where someone already has the
database credentials.

What comes back is written with ``source = 'manual'``, which
:func:`mkagg.derive.rederive` treats as settled and never revises. That
guard already existed; this is the first thing that makes systematic use of
it.

    python scripts/run_pipeline.py review --export tail.csv
    # ... fill in set_category / set_gender in a spreadsheet ...
    python scripts/run_pipeline.py review --apply tail.csv --dry-run
    python scripts/run_pipeline.py review --apply tail.csv

**Unknown is not always a question.** A football has no gender, and the
schema says so by holding NULL rather than guessing. Exporting those rows
would hand a person hundreds whose correct answer is "leave it", which is
the fastest way to make a review file go unread. Accessory gender is
therefore left out unless `--include-accessory-gender` asks for it.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field

from .taxonomy import PARENT_SLUGS

#: What a person may write in `set_gender`. `unisex` is here and absent from
#: `classify_gender` for the same reason in both places: a title cannot show
#: it, but a person looking at the product can.
REVIEWABLE_GENDERS = ("men", "women", "kids", "unisex")

#: The columns, in the order they open in a spreadsheet. Everything before
#: `set_category` is context and is ignored on the way back -- only the two
#: `set_` columns and `product_id` are read, so a reviewer can sort, filter
#: and delete rows freely without breaking the file.
COLUMNS = (
    "product_id", "name", "brand", "vertical",
    "category", "category_source", "gender", "gender_source",
    "shops", "shelves", "url",
    "set_category", "set_gender", "note",
)

EXPORT_SQL = """
SELECT p.id,
       p.canonical_name,
       b.name                      AS brand,
       c.kind::text                AS vertical,
       c.slug                      AS category,
       p.category_source,
       p.gender::text              AS gender,
       p.gender_source,
       (SELECT string_agg(DISTINCT m.slug, ' ' ORDER BY m.slug)
          FROM merchant_offer mo
          JOIN merchant m ON m.id = mo.merchant_id
         WHERE mo.product_id = p.id AND mo.status = 'active') AS shops,
       (SELECT string_agg(DISTINCT mo.merchant_category_path, ' | ')
          FROM merchant_offer mo
         WHERE mo.product_id = p.id AND mo.status = 'active'
           AND mo.merchant_category_path IS NOT NULL)         AS shelves,
       (SELECT mo.product_url
          FROM merchant_offer mo
         WHERE mo.product_id = p.id AND mo.status = 'active'
         ORDER BY mo.id LIMIT 1)                              AS url
  FROM product p
  LEFT JOIN category c ON c.id = p.category_id
  LEFT JOIN brand b    ON b.id = p.brand_id
 WHERE (
        -- No category at all, or one that names a vertical and no article
        -- within it. Both are open questions about the same axis.
        p.category_id IS NULL
        OR c.slug = ANY(%(parents)s)
        -- A gender we could not read. Scoped to the verticals where the
        -- answer exists: see the module docstring on footballs.
        OR (p.gender IS NULL
            AND (c.kind::text IN ('footwear', 'apparel')
                 OR %(all_genders)s))
       )
   AND p.category_source IS DISTINCT FROM 'manual'
   AND p.gender_source   IS DISTINCT FROM 'manual'
   AND EXISTS (SELECT 1 FROM merchant_offer mo
                WHERE mo.product_id = p.id AND mo.status = 'active')
 ORDER BY c.kind::text NULLS FIRST, c.slug NULLS FIRST, b.name, p.id
"""


@dataclass
class ExportReport:
    rows: int = 0
    path: str = ""

    def summary(self) -> str:
        return f"wrote {self.rows} rows to {self.path}"


@dataclass
class ApplyReport:
    read: int = 0
    blank: int = 0
    categories: int = 0
    genders: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"read {self.read} rows ({self.blank} left blank), "
                f"set {self.categories} categories and {self.genders} "
                f"genders, {self.unchanged} already correct")


def export(conn, path: str, *, limit: int | None = None,
           include_accessory_gender: bool = False) -> ExportReport:
    """Write the open questions to ``path`` as CSV."""
    with conn.cursor() as cur:
        cur.execute(EXPORT_SQL, {"parents": sorted(PARENT_SLUGS),
                                 "all_genders": include_accessory_gender})
        rows = cur.fetchall()
    if limit is not None:
        rows = rows[:limit]

    report = ExportReport(path=path)
    # utf-8-sig, because the reviewer opens this in Excel and the shelves
    # column is Cyrillic. Without the BOM Excel reads it as cp1252 and
    # "Текстил" arrives as mojibake -- which a reviewer would reasonably
    # treat as corrupt data rather than as an encoding default.
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        for row in rows:
            writer.writerow(list(row) + ["", "", ""])
            report.rows += 1
    return report


def _categories(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT slug, id FROM category")
        return {slug: cid for slug, cid in cur.fetchall()}


def apply(conn, path: str, *, dry_run: bool = False) -> ApplyReport:
    """Read answers back and record them as a person's decision.

    Every row is validated before any row is written. A file with one
    mistyped slug in it changes nothing at all, rather than applying the
    first half and stopping -- a half-applied review file is worse than a
    rejected one, because nothing says where it stopped.
    """
    report = ApplyReport()
    valid = _categories(conn)

    with conn.cursor() as cur:
        cur.execute("""SELECT p.id, c.slug, p.gender::text
                         FROM product p
                         LEFT JOIN category c ON c.id = p.category_id""")
        current = {pid: (slug, gender) for pid, slug, gender in cur.fetchall()}

    pending: list[tuple[int, str | None, str | None]] = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for line, row in enumerate(csv.DictReader(fh), start=2):
            report.read += 1
            raw_id = (row.get("product_id") or "").strip()
            cat = (row.get("set_category") or "").strip().lower()
            gender = (row.get("set_gender") or "").strip().lower()
            if not cat and not gender:
                report.blank += 1
                continue
            if not raw_id.isdigit():
                report.errors.append(
                    f"line {line}: product_id {raw_id!r} is not a number")
                continue
            pid = int(raw_id)
            if pid not in current:
                report.errors.append(f"line {line}: no product {pid}")
                continue
            if cat and cat not in valid:
                report.errors.append(
                    f"line {line}: {cat!r} is not a category slug")
                continue
            if cat and cat in PARENT_SLUGS:
                # Setting a parent by hand and calling it settled would
                # freeze the product there: derive never revisits a manual
                # answer, so this is the one value a reviewer must not pick.
                report.errors.append(
                    f"line {line}: {cat!r} names a vertical, not an article; "
                    f"leave it blank to keep it in the tail")
                continue
            if gender and gender not in REVIEWABLE_GENDERS:
                report.errors.append(
                    f"line {line}: {gender!r} is not one of "
                    f"{', '.join(REVIEWABLE_GENDERS)}")
                continue
            pending.append((pid, cat or None, gender or None))

    if report.errors:
        return report

    for pid, cat, gender in pending:
        cur_cat, cur_gender = current[pid]
        sets, params = [], {}
        if cat and cat != cur_cat:
            sets.append("category_id = %(cid)s, category_source = 'manual'")
            params["cid"] = valid[cat]
            report.categories += 1
        if gender and gender != cur_gender:
            sets.append("gender = %(g)s::gender_t, gender_source = 'manual'")
            params["g"] = gender
            report.genders += 1
        if not sets:
            report.unchanged += 1
            continue
        if dry_run:
            continue
        params["pid"] = pid
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE product SET {', '.join(sets)}, updated_at = now() "
                f"WHERE id = %(pid)s", params)
    if not dry_run:
        conn.commit()
    return report
