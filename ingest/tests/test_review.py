"""The manual-review loop: export the open questions, apply the answers.

These run against a real Postgres because the whole point of the feature is
what it writes: ``category_source = 'manual'`` is the one value
:func:`mkagg.derive.rederive` treats as settled, and a test that mocked the
database would assert the CSV parsing and miss whether the guard actually
holds. The last test here re-derives over an applied answer and checks it
survives, which is the promise the feature is making to a reviewer.
"""
from __future__ import annotations

import csv
import os

import pytest

from mkagg import review
from mkagg.derive import rederive

DSN = os.environ.get(
    "MKAGG_TEST_DSN",
    "postgresql://mkagg:mkagg_dev_only@localhost:5433/mkagg_test")


@pytest.fixture
def conn():
    psycopg = pytest.importorskip("psycopg")
    try:
        connection = psycopg.connect(DSN, connect_timeout=3)
    except Exception as exc:               # pragma: no cover
        pytest.skip(f"no database at {DSN}: {exc}")
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture
def clean_db(conn):
    with conn.cursor() as cur:
        cur.execute("""
            TRUNCATE stage_offer, stage_variant, ingest_run, price_point,
                     click_event, verification_event, match_candidate,
                     user_price_report, product_price_summary, offer_variant,
                     merchant_offer, product_identifier, product
            RESTART IDENTITY CASCADE""")
    conn.commit()
    return conn


def make_product(conn, name, *, category=None, gender=None,
                 cat_source=None, gender_source=None, shelf="Текстил"):
    """One product with one live offer, which is what export requires."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM category WHERE slug = %s", (category,))
        row = cur.fetchone() if category else None
        # brand_id is NOT NULL, and the reference seed survives the
        # truncate, so any seeded brand will do: these tests are about the
        # category and gender axes.
        cur.execute("SELECT id FROM brand ORDER BY id LIMIT 1")
        brand = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO product (canonical_name, model_name, slug,
                                    brand_id, category_id, gender,
                                    category_source, gender_source)
                    VALUES (%s, %s, %s, %s, %s, %s::gender_t, %s, %s)
                 RETURNING id""",
            (name, name, name.lower().replace(" ", "-"), brand,
             row[0] if row else None,
             gender, cat_source, gender_source))
        pid = cur.fetchone()[0]
        cur.execute("SELECT id FROM merchant WHERE slug = 'sportm'")
        mid = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO merchant_offer (merchant_id, product_id,
                                           merchant_sku, raw_title,
                                           product_url,
                                           merchant_category_path, status)
                    VALUES (%s, %s, %s, %s, %s, %s, 'active')""",
            (mid, pid, f"sku-{pid}", name, f"https://example.test/{pid}",
             shelf))
    conn.commit()
    return pid


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["product_id", "set_category", "set_gender"])
        writer.writeheader()
        writer.writerows(rows)


class TestWhatGetsAsked:
    def test_a_parent_bucket_is_a_question(self, clean_db, tmp_path):
        pid = make_product(clean_db, "Stuck In Apparel",
                           category="apparel", gender="men")
        out = tmp_path / "tail.csv"
        review.export(clean_db, str(out))
        assert [r["product_id"] for r in read_csv(out)] == [str(pid)]

    def test_a_settled_product_is_not(self, clean_db, tmp_path):
        make_product(clean_db, "Known Tee", category="tshirts", gender="men")
        out = tmp_path / "tail.csv"
        review.export(clean_db, str(out))
        assert read_csv(out) == []

    def test_an_accessory_without_a_gender_is_not_asked_about(
            self, clean_db, tmp_path):
        """A football has no gender, and NULL is the true answer.

        Exporting these would hand a reviewer hundreds of rows whose right
        answer is "leave it", which is how a review file goes unread.
        """
        make_product(clean_db, "A Football", category="balls_training")
        out = tmp_path / "tail.csv"
        review.export(clean_db, str(out))
        assert read_csv(out) == []

    def test_unless_it_is_asked_for(self, clean_db, tmp_path):
        pid = make_product(clean_db, "A Football",
                           category="balls_training")
        out = tmp_path / "tail.csv"
        review.export(clean_db, str(out), include_accessory_gender=True)
        assert [r["product_id"] for r in read_csv(out)] == [str(pid)]

    def test_a_garment_without_a_gender_is_asked_about(
            self, clean_db, tmp_path):
        pid = make_product(clean_db, "Genderless Tee", category="tshirts")
        out = tmp_path / "tail.csv"
        review.export(clean_db, str(out))
        assert [r["product_id"] for r in read_csv(out)] == [str(pid)]

    def test_an_answered_product_leaves_the_tail(self, clean_db, tmp_path):
        """Otherwise every export re-asks everything already decided."""
        make_product(clean_db, "Already Decided", category="apparel",
                     gender="men", cat_source="manual")
        out = tmp_path / "tail.csv"
        review.export(clean_db, str(out))
        assert read_csv(out) == []

    def test_the_shops_own_words_travel_with_the_question(
            self, clean_db, tmp_path):
        """A reviewer deciding blind is just guessing faster."""
        make_product(clean_db, "Stuck", category="apparel", gender="men",
                     shelf="Текстил")
        row = read_csv(tmp_path / "tail.csv") if False else None
        out = tmp_path / "tail.csv"
        review.export(clean_db, str(out))
        row = read_csv(out)[0]
        assert row["shelves"] == "Текстил"
        assert row["shops"] == "sportm"
        assert row["url"].startswith("https://example.test/")


class TestApplyingAnswers:
    def test_an_answer_is_recorded_as_a_persons(self, clean_db, tmp_path):
        pid = make_product(clean_db, "Stuck", category="apparel",
                           gender="men")
        path = tmp_path / "answers.csv"
        write_csv(path, [{"product_id": pid, "set_category": "tshirts",
                          "set_gender": ""}])
        report = review.apply(clean_db, str(path))
        assert (report.categories, report.errors) == (1, [])
        with clean_db.cursor() as cur:
            cur.execute("""SELECT c.slug, p.category_source
                             FROM product p JOIN category c
                               ON c.id = p.category_id
                            WHERE p.id = %s""", (pid,))
            assert cur.fetchone() == ("tshirts", "manual")

    def test_a_dry_run_writes_nothing(self, clean_db, tmp_path):
        pid = make_product(clean_db, "Stuck", category="apparel",
                           gender="men")
        path = tmp_path / "answers.csv"
        write_csv(path, [{"product_id": pid, "set_category": "tshirts",
                          "set_gender": ""}])
        report = review.apply(clean_db, str(path), dry_run=True)
        assert report.categories == 1
        with clean_db.cursor() as cur:
            cur.execute("""SELECT c.slug FROM product p
                             JOIN category c ON c.id = p.category_id
                            WHERE p.id = %s""", (pid,))
            assert cur.fetchone() == ("apparel",)

    def test_one_bad_row_stops_the_whole_file(self, clean_db, tmp_path):
        """A half-applied review file is worse than a rejected one.

        Nothing records where it stopped, so a reviewer cannot tell which
        half of their afternoon survived.
        """
        good = make_product(clean_db, "Good", category="apparel",
                            gender="men")
        path = tmp_path / "answers.csv"
        write_csv(path, [
            {"product_id": good, "set_category": "tshirts", "set_gender": ""},
            {"product_id": good, "set_category": "sneakrs", "set_gender": ""},
        ])
        report = review.apply(clean_db, str(path))
        assert report.errors and "sneakrs" in report.errors[0]
        with clean_db.cursor() as cur:
            cur.execute("""SELECT c.slug FROM product p
                             JOIN category c ON c.id = p.category_id
                            WHERE p.id = %s""", (good,))
            assert cur.fetchone() == ("apparel",)

    def test_a_parent_bucket_is_refused_as_an_answer(self, clean_db,
                                                     tmp_path):
        """Marking a vertical "decided" would freeze it there for ever.

        derive never revisits a manual answer, so "apparel" as an answer is
        the one value that makes the tail permanently unanswerable.
        """
        pid = make_product(clean_db, "Stuck", category="apparel",
                           gender="men")
        path = tmp_path / "answers.csv"
        write_csv(path, [{"product_id": pid, "set_category": "apparel",
                          "set_gender": ""}])
        report = review.apply(clean_db, str(path))
        assert report.errors and "names a vertical" in report.errors[0]

    def test_blank_rows_are_simply_skipped(self, clean_db, tmp_path):
        """A reviewer answers what they know and leaves the rest."""
        pid = make_product(clean_db, "Stuck", category="apparel",
                           gender="men")
        path = tmp_path / "answers.csv"
        write_csv(path, [{"product_id": pid, "set_category": "",
                          "set_gender": ""}])
        report = review.apply(clean_db, str(path))
        assert (report.blank, report.categories, report.errors) == (1, 0, [])

    def test_a_gender_can_be_unisex(self, clean_db, tmp_path):
        """The one value no title can establish, which is why a person is
        being asked at all."""
        pid = make_product(clean_db, "Genderless Tee", category="tshirts")
        path = tmp_path / "answers.csv"
        write_csv(path, [{"product_id": pid, "set_category": "",
                          "set_gender": "unisex"}])
        report = review.apply(clean_db, str(path))
        assert (report.genders, report.errors) == (1, [])
        with clean_db.cursor() as cur:
            cur.execute("""SELECT gender::text, gender_source FROM product
                            WHERE id = %s""", (pid,))
            assert cur.fetchone() == ("unisex", "manual")


class TestTheAnswerSurvives:
    def test_derive_does_not_revise_a_person(self, clean_db, tmp_path):
        """The promise the whole feature rests on.

        The product's own shelf says "Текстил", which derive reads as the
        apparel parent. Left alone it would put the product straight back
        there on the next pass, undoing the review silently.
        """
        pid = make_product(clean_db, "Stuck", category="apparel",
                           gender="men", shelf="Текстил")
        path = tmp_path / "answers.csv"
        write_csv(path, [{"product_id": pid, "set_category": "tshirts",
                          "set_gender": "women"}])
        assert review.apply(clean_db, str(path)).errors == []

        report = rederive(clean_db)
        assert report.kept_manual == 1

        with clean_db.cursor() as cur:
            cur.execute("""SELECT c.slug, p.category_source,
                                  p.gender::text, p.gender_source
                             FROM product p JOIN category c
                               ON c.id = p.category_id
                            WHERE p.id = %s""", (pid,))
            assert cur.fetchone() == ("tshirts", "manual", "women", "manual")
