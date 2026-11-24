"""Joining a fragrance on what it is, because no code says so.

Every other vertical in this catalogue is matched on a manufacturer code
that both shops print. The two perfumeries print an internal row number
each -- e-elixir sends "278" for Valentino Donna, Schatze calls the same
bottle 4976 -- so a code match joins nothing across shops, and could join
the wrong things within one.

These run against a real Postgres because what is being tested is what gets
written: the product's name, its slug, its concentration column, and whether
two offers land on one row. A mocked database would assert the call
arguments and miss all four.
"""
from __future__ import annotations

import os

import pytest

from mkagg.load.promote import UPSERT_OFFER_SQL, resolve_offer
from mkagg.models import RawOffer, RawVariant

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


def fragrance_offer(title, *, merchant="eelixir", sku="278", brand=None,
                    volumes=(("50ml", 5000),)):
    """One perfumery's listing of one bottle."""
    return RawOffer(
        merchant_slug=merchant, merchant_sku=sku or "no-sku",
        raw_title=title, raw_brand=brand, raw_mpn=sku or None,
        product_url=f"https://example.test/{sku or 'x'}",
        category_hint="perfume",
        variants=[RawVariant(size_label=label, price_minor=price)
                  for label, price in volumes])


def shoe_offer(sku="392290-02", merchant="sportvision"):
    return RawOffer(
        merchant_slug=merchant, merchant_sku=sku,
        raw_title="Puma Caven 2.0 Patiki", raw_brand="Puma", raw_mpn=sku,
        product_url=f"https://example.test/{sku}",
        category_hint="sneakers",
        variants=[RawVariant(size_label="42", price_minor=2863)])


def merchant_id(conn, slug):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM merchant WHERE slug = %s", (slug,))
        row = cur.fetchone()
    assert row, f"merchant {slug!r} is not seeded in the test database"
    return row[0]


def resolve(conn, offer, slug=None):
    return resolve_offer(conn, offer, merchant_id(conn, slug or offer.merchant_slug),
                         create_missing=True, report=None)


def promote(conn, offer, slug=None):
    """Resolve an offer *and* write it, the way `promote_run` does.

    The order is the point. `promote_run` upserts each offer immediately
    after resolving it, so the next offer of the same run is matched against
    a database that already holds this one -- which is what lets
    `find_product_by_identity` see that a shop lists two names separately.
    A test that only resolves leaves `merchant_offer` empty and cannot
    exercise that guard at all.
    """
    mid = merchant_id(conn, slug or offer.merchant_slug)
    product_id, result = resolve_offer(conn, offer, mid, create_missing=True,
                                       report=None)
    with conn.cursor() as cur:
        cur.execute(UPSERT_OFFER_SQL, {
            "merchant": mid, "product": product_id,
            "sku": offer.merchant_sku, "mpn": offer.raw_mpn,
            "title": offer.raw_title[:500], "brand": offer.raw_brand,
            "url": offer.product_url, "image": offer.image_url,
            "category_path": offer.category_path,
            "gender": offer.gender_hint,
            "method": result.method if product_id else None,
            "confidence": result.confidence if product_id else None,
            "status": "active" if product_id else "unmatched"})
    return product_id, result


@pytest.mark.usefixtures("clean_db")
class TestTwoShopsOneBottle:
    def test_the_join_the_vertical_rests_on(self, conn):
        """Schatze omits the brand from the title and keeps it in a
        Manufacturer field; e-elixir leads with it. Compared as strings,
        these two titles share nothing in the same position.
        """
        a, _ = resolve(conn, fragrance_offer(
            "Versace Pour Homme Eau de toilette", sku="278", brand="Versace"))
        b, res = resolve(conn, fragrance_offer(
            "Pour Homme - edt", merchant="sportvision", sku="4976",
            brand="Versace"))
        assert a is not None
        assert b == a, "the same fragrance must be one product"
        assert res.method == "identity"

    def test_a_macedonian_title_joins_the_english_one(self, conn):
        """e-elixir writes 98 of its titles in Macedonian."""
        a, _ = resolve(conn, fragrance_offer(
            "Gucci Guilty Eau de toilette", sku="1", brand="Gucci"))
        b, _ = resolve(conn, fragrance_offer(
            "Gucci Guilty тоалетна вода за мажи", sku="2",
            brand="Gucci"))
        assert a is not None and b == a


@pytest.mark.usefixtures("clean_db")
class TestTheOnesThatMustStayApart:
    """Each pair below is stocked side by side at different prices."""

    def test_a_flanker_is_its_own_product(self, conn):
        a, _ = resolve(conn, fragrance_offer(
            "Valentino Donna Eau de parfum", sku="1", brand="Valentino"))
        b, _ = resolve(conn, fragrance_offer(
            "Valentino Donna Born In Roma Eau de parfum", sku="2",
            brand="Valentino"))
        assert a is not None and b is not None and a != b

    def test_a_different_strength_is_its_own_product(self, conn):
        a, _ = resolve(conn, fragrance_offer(
            "Versace Pour Homme Eau de toilette", sku="1", brand="Versace"))
        b, _ = resolve(conn, fragrance_offer(
            "Versace Pour Homme Eau de parfum", sku="2", brand="Versace"))
        assert a != b

    def test_elixir_in_the_name_does_not_merge(self, conn):
        """"Le Male ELIXIR - Eau de Parfum" is an EDP whose fragrance is
        called Le Male Elixir. Read as a strength it would merge with plain
        Le Male EDP, a different bottle at a different price."""
        a, _ = resolve(conn, fragrance_offer(
            "Jean Paul Gaultier Le Male ELIXIR Eau de Parfum", sku="1",
            brand="Jean Paul Gaultier"))
        b, _ = resolve(conn, fragrance_offer(
            "Jean Paul Gaultier Le Male Eau de parfum", sku="2",
            brand="Jean Paul Gaultier"))
        assert a != b


@pytest.mark.usefixtures("clean_db")
class TestTheAudienceVeto:
    """One line sold to two audiences is two bottles -- but only when the
    shops actually disagree about the audience.

    The rule is a veto, not a key. Requiring the genders to match would be
    the obvious reading and it would be wrong: e-elixir marks a fragrance
    `unisex` whenever it appears in both of its departments -- 218 of 690 --
    while Schatze files most things under one gender. Equality there splits
    nearly a third of the catalogue into two pages per bottle.
    """

    def test_a_mens_and_a_womens_version_stay_apart(self, conn):
        """The seven products this fixed, all the same shape.

        Ajmal Amaze for men is 100ml at 2 145 den; Ajmal Amaze for women
        is 75ml at 3 065. Different compositions, different volumes,
        different prices, and the audience word is the only thing in either
        title that says so -- which is why it cannot simply be stripped.
        """
        a, _ = resolve(conn, fragrance_offer(
            "Ajmal Amaze Eau de parfum for women", sku="11818",
            brand="Ajmal"))
        b, _ = resolve(conn, fragrance_offer(
            "Ajmal Amaze Eau de parfum for men", sku="12561", brand="Ajmal"))
        assert a is not None and b is not None and a != b

    def test_the_same_audience_still_converges(self, conn):
        """e-elixir lists some fragrances twice. Those must still merge --
        14 products in the live catalogue do."""
        a, _ = resolve(conn, fragrance_offer(
            "Ajmal Amaze Eau de parfum for women", sku="1", brand="Ajmal"))
        b, _ = resolve(conn, fragrance_offer(
            "Ajmal Amaze Eau de parfum for women", sku="2", brand="Ajmal"))
        assert a is not None and b == a

    def test_unisex_still_meets_a_gendered_shelf(self, conn):
        """The cross-shop case the veto is shaped around.

        e-elixir calls a bottle unisex because it sits in both departments;
        Schatze files the same bottle under men. Nothing about that is a
        disagreement over which bottle it is.
        """
        a, _ = resolve(conn, fragrance_offer(
            "Lattafa Ajwad Eau de parfum for women and men", sku="1",
            brand="Lattafa"))
        b, res = resolve(conn, fragrance_offer(
            "Ajwad - edp", merchant="sportvision", sku="2", brand="Lattafa"))
        assert a is not None and b == a
        assert res.method == "identity"

    def test_a_silent_title_meets_a_gendered_one(self, conn):
        """Only 12 percent of Schatze's titles name an audience, so most
        cross-shop joins have a gender on one side only."""
        a, _ = resolve(conn, fragrance_offer(
            "Moschino Toy 2 Eau de parfum for women", sku="1",
            brand="Moschino"))
        b, _ = resolve(conn, fragrance_offer(
            "Toy 2 - edp", merchant="sportvision", sku="2", brand="Moschino"))
        assert a is not None and b == a

    def test_the_veto_is_only_men_against_women(self, conn):
        from mkagg.load.promote import genders_conflict

        assert genders_conflict("men", "women")
        assert genders_conflict("women", "men")
        for pair in [("men", "men"), ("men", "unisex"), ("unisex", "women"),
                     ("kids", "men"), (None, "men"), ("men", None),
                     (None, None)]:
            assert not genders_conflict(*pair), pair


@pytest.mark.usefixtures("clean_db")
class TestWhatGetsWritten:
    def test_the_strength_is_in_the_name_a_shopper_reads(self, conn):
        """Otherwise a listing shows "Versace Pour Homme" twice, at two
        prices, with nothing on screen to tell them apart."""
        pid, _ = resolve(conn, fragrance_offer(
            "Versace Pour Homme Eau de toilette", brand="Versace"))
        with conn.cursor() as cur:
            cur.execute("""SELECT canonical_name, model_name, concentration
                             FROM product WHERE id = %s""", (pid,))
            canonical, model, concentration = cur.fetchone()
        assert canonical == "Versace Pour Homme EDT"
        assert model == "Pour Homme"
        assert concentration == "EDT"

    def test_the_slug_carries_no_code(self, conn):
        """A shoe is slugged with its article code, because two colourways
        share a name. A fragrance must do the opposite: the two shops send
        different codes for one bottle, so a code in the slug would
        guarantee they never meet."""
        pid, _ = resolve(conn, fragrance_offer(
            "Versace Pour Homme Eau de toilette", sku="278", brand="Versace"))
        with conn.cursor() as cur:
            cur.execute("SELECT slug FROM product WHERE id = %s", (pid,))
            slug = cur.fetchone()[0]
        # The audience is appended, and must be: one line sold to two
        # audiences is two products competing for one slug. "Pour Homme" in
        # the title is where this one's `men` comes from -- the offer names
        # no shelf at all.
        assert slug == "versace-pour-homme-edt-men"
        assert "278" not in slug

    def test_an_internal_row_number_is_not_filed_as_an_mpn(self, conn):
        """e-elixir sends "278" as a sku. Filed as an MPN, any other shop's
        row 278 would match this perfume."""
        pid, _ = resolve(conn, fragrance_offer(
            "Versace Pour Homme Eau de toilette", sku="278", brand="Versace"))
        with conn.cursor() as cur:
            cur.execute("""SELECT count(*) FROM product_identifier
                            WHERE product_id = %s""", (pid,))
            assert cur.fetchone()[0] == 0

    def test_a_barcode_is_still_filed(self, conn):
        """A real GTIN is the one key that would make cross-shop matching
        exact rather than textual, so it is worth keeping."""
        pid, _ = resolve(conn, fragrance_offer(
            "Versace Pour Homme Eau de toilette", sku="3614273662765",
            brand="Versace"))
        with conn.cursor() as cur:
            cur.execute("""SELECT value_norm FROM product_identifier
                            WHERE product_id = %s""", (pid,))
            assert cur.fetchone()[0] == "3614273662765"


@pytest.mark.usefixtures("clean_db")
class TestTheEdges:
    def test_an_offer_with_no_code_still_gets_a_product(self, conn):
        """13 live e-elixir fragrances carry no sku at all. Under the
        code-only path they were attached to no product and were absent
        from the catalogue entirely."""
        pid, res = resolve(conn, fragrance_offer(
            "Moschino Toy 2 Eau de parfum for women", sku="",
            brand="Moschino"))
        assert pid is not None
        assert res.method == "identity"

    def test_a_strength_nobody_stated_still_makes_one_product(self, conn):
        """Eight live products name no strength ("Giorgio Armani Code
        Elixir"). The partial unique index cannot hold them -- NULL is never
        equal to NULL -- so the lookup has to, or every crawl mints another.
        """
        a, _ = resolve(conn, fragrance_offer(
            "Giorgio Armani Code Elixir", sku="1", brand="Giorgio Armani"))
        b, _ = resolve(conn, fragrance_offer(
            "Giorgio Armani Code Elixir", sku="2", brand="Giorgio Armani"))
        assert a is not None and b == a

    def test_a_title_naming_no_fragrance_creates_nothing(self, conn):
        """A product keyed on an empty line name would collect every
        unreadable title the shop has."""
        pid, _ = resolve(conn, fragrance_offer("Versace", brand="Versace"))
        assert pid is None

    def test_a_shoe_is_untouched_by_any_of_this(self, conn):
        """The identity path is gated on the fragrance facet. A sneaker is
        still named from its title and slugged with its code."""
        pid, res = resolve(conn, shoe_offer())
        assert pid is not None
        with conn.cursor() as cur:
            cur.execute("""SELECT slug, concentration FROM product
                            WHERE id = %s""", (pid,))
            slug, concentration = cur.fetchone()
        assert "39229002" in slug
        assert concentration is None
        assert res.method == "mpn"


@pytest.mark.usefixtures("clean_db")
class TestTheWordsTheShopsDisagreeAbout:
    """The two perfumeries name one bottle three different ways.

    Measured over 1,625 live fragrance products: 36 were two product pages
    for no reason but this. Each case below is one of them.
    """

    def test_a_house_prefix_does_not_make_a_second_product(self, conn):
        """e-elixir prints "Emporio Armani Stronger With You", Schatze
        prints "Stronger With You". Six bottles over."""
        a, _ = promote(conn, fragrance_offer(
            "Emporio Armani Stronger With You Eau de Parfum",
            sku="a1", brand="Giorgio Armani"))
        b, res = promote(conn, fragrance_offer(
            "Stronger With You - edp", merchant="sportvision", sku="b1",
            brand="Giorgio Armani"))
        assert a is not None and b == a
        assert res.method == "identity"

    def test_the_brand_echoed_mid_name_does_not_either(self, conn):
        a, _ = promote(conn, fragrance_offer(
            "Lattafa Asad Eau de Parfum", sku="a2", brand="Lattafa"))
        b, _ = promote(conn, fragrance_offer(
            "Asad By Lattafa - edp", merchant="sportvision", sku="b2",
            brand="Lattafa"))
        assert a is not None and b == a

    def test_an_audience_marker_does_not_either(self, conn):
        """The commonest of the three: 21 of the 36."""
        a, _ = promote(conn, fragrance_offer(
            "Gucci Guilty Eau de toilette", sku="a3", brand="Gucci"))
        b, _ = promote(conn, fragrance_offer(
            "Guilty Pour Homme - edt", merchant="sportvision", sku="b3",
            brand="Gucci"))
        assert a is not None and b == a

    def test_the_catalogue_keeps_the_shops_own_words(self, conn):
        """The reduction is for comparing, not for displaying. A shopper
        looking for Emporio Armani must still find that on the page."""
        pid, _ = promote(conn, fragrance_offer(
            "Emporio Armani Stronger With You Eau de Parfum",
            sku="a4", brand="Giorgio Armani"))
        with conn.cursor() as cur:
            cur.execute("SELECT model_name FROM product WHERE id = %s", (pid,))
            assert cur.fetchone()[0] == "Emporio Armani Stronger With You"


@pytest.mark.usefixtures("clean_db")
class TestWhatTheReductionMustNotJoin:
    def test_one_shop_listing_both_names_is_believed(self, conn):
        """e-elixir sells David Beckham "Classic" and "Classic Homme".
        They are two real releases, and the reduction makes one key of
        them. A shop listing both separately is the evidence that settles
        it -- so the reduced key may only join offers from different
        shops."""
        a, _ = promote(conn, fragrance_offer(
            "David Beckham Classic Eau de toilette",
            sku="a5", brand="David Beckham"))
        b, _ = promote(conn, fragrance_offer(
            "David Beckham Classic Homme Eau de toilette",
            sku="b5", brand="David Beckham"))
        assert a is not None and b is not None
        assert b != a, "one shop's two listings are two fragrances"

    def test_and_they_get_different_slugs(self, conn):
        """Because `ON CONFLICT (slug) DO UPDATE ... RETURNING id` would
        otherwise hand the second one the first one's row and silently
        merge exactly what the guard just refused."""
        a, _ = promote(conn, fragrance_offer(
            "David Beckham Classic Eau de toilette",
            sku="a6", brand="David Beckham"))
        b, _ = promote(conn, fragrance_offer(
            "David Beckham Classic Homme Eau de toilette",
            sku="b6", brand="David Beckham"))
        with conn.cursor() as cur:
            cur.execute("SELECT id, slug FROM product WHERE id IN (%s, %s)",
                        (a, b))
            slugs = dict(cur.fetchall())
        assert len(set(slugs.values())) == 2, slugs

    def test_the_guard_does_not_undo_its_own_merge(self, conn):
        """The trap in guarding by shop. Once Schatze's "Guilty Pour
        Homme" lands on e-elixir's "Guilty", a Schatze offer *is* sitting
        on that product -- and a naive guard would split it off again on
        the next crawl, every crawl. The offer being promoted is excluded
        by its own SKU."""
        a, _ = promote(conn, fragrance_offer(
            "Gucci Guilty Eau de toilette", sku="a7", brand="Gucci"))
        b, _ = promote(conn, fragrance_offer(
            "Guilty Pour Homme - edt", merchant="sportvision", sku="b7",
            brand="Gucci"))
        assert b == a
        again, _ = promote(conn, fragrance_offer(
            "Guilty Pour Homme - edt", merchant="sportvision", sku="b7",
            brand="Gucci"))
        assert again == a, "a re-crawl must not split the merge"

    def test_gender_still_vetoes_what_the_reduction_joined(self, conn):
        """"Dylan Blue Pour Homme" and "Dylan Blue Pour Femme" both reduce
        to "dylan blue". The men-versus-women veto is the only thing left
        holding them apart, which is why gender stays in the key."""
        a, _ = promote(conn, fragrance_offer(
            "Versace Dylan Blue Pour Femme Eau de toilette",
            sku="a8", brand="Versace"))
        b, _ = promote(conn, fragrance_offer(
            "Dylan Blue Pour Homme - edt", merchant="sportvision",
            sku="b8", brand="Versace"))
        assert a is not None and b is not None and b != a

    def test_a_flanker_is_still_its_own_product(self, conn):
        a, _ = promote(conn, fragrance_offer(
            "Lattafa Asad Eau de Parfum", sku="a9", brand="Lattafa"))
        b, _ = promote(conn, fragrance_offer(
            "Asad Elixir - edp", merchant="sportvision", sku="b9",
            brand="Lattafa"))
        assert a is not None and b is not None and b != a


@pytest.mark.usefixtures("clean_db")
class TestTheAudienceAFragranceStates:
    def test_a_title_marker_fills_a_gender_no_shelf_states(self, conn):
        """The Merchant of Venice's La Fenice sits on
        `/niche-fragrances/`, which names no gender, and the general
        derivation does not know that "Pour Femme" is one. Both bottles
        came out NULL -- and NULL is what the match veto needs most here,
        because `identity_key` reduces both to "la fenice"."""
        pid, _ = promote(conn, fragrance_offer(
            "La Fenice Pour Femme - EDP", sku="c1",
            brand="The Merchant of Venice"))
        with conn.cursor() as cur:
            cur.execute("""SELECT gender::text, gender_source
                             FROM product WHERE id = %s""", (pid,))
            assert cur.fetchone() == ("women", "title")

    def test_and_so_the_two_la_fenices_stay_apart(self, conn):
        femme, _ = promote(conn, fragrance_offer(
            "La Fenice Pour Femme - EDP", sku="c2",
            brand="The Merchant of Venice"))
        homme, _ = promote(conn, fragrance_offer(
            "La Fenice Pour Homme - EDP", merchant="sportvision", sku="c3",
            brand="The Merchant of Venice"))
        assert femme is not None and homme is not None
        assert homme != femme, "men and women are two bottles"
