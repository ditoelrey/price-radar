"""Deriving category and gender from offers, and the facet plans behind it.

The bug these replace: ``create_product`` stamped a category once and nothing
revised it, so re-sweeping sportm's 2,069 listings moved its uncategorised
count from 221 to 223 -- the 1,348 new products were classified and the old
ones were never looked at again. 2,767 products sat in the generic footwear
bucket and all 10,731 claimed to be unisex, that last one straight from a
``NOT NULL DEFAULT 'unisex'``.

The measurements that shaped the rules, taken over the live catalogue:

*   Four of six shops put no category word in a title at all. Pooling every
    merchant's title for a product leaves 2,580 of the 2,767 still silent, so
    the facet has to be the strong source and the title the fallback.
*   Low-top versus high-top is derivable for 6.2 percent of footwear
    products, so it stays out of the canonical tree (V17) and lives in
    ``merchant_offer.merchant_category_path``.
*   1,935 products carry two or more shops' offers and 42 carry four, so
    "whichever shop we met first" is not an acceptable answer.
"""
from __future__ import annotations

import pytest

from mkagg.derive import (OfferEvidence, derive_category, derive_gender)
from mkagg.discover import FACET_CATEGORY, FACET_PLANS, as_facets
from mkagg.taxonomy import FACET_GENDERS, FOOTWEAR_SLUGS, KNOWN_GENDERS


def offer(merchant="sportvision", path=None, gender=None, title=None,
          url=None):
    return OfferEvidence(merchant_slug=merchant, merchant_category_path=path,
                         merchant_gender=gender, raw_title=title,
                         product_url=url)


class TestCategoryFromFacets:
    def test_one_facet_decides(self):
        assert derive_category([offer(path="kopacki")]) == ("cleats", "facet")

    def test_two_shops_agreeing_through_different_words(self):
        """The whole point of the canonical tree.

        sportm files this shoe under "Патики-ниски" and sportvision under
        "patiki". Different vocabularies, one bucket, so the shops agree even
        though neither used the other's word.
        """
        assert derive_category([
            offer("sportm", path="Патики-ниски"),
            offer("sportvision", path="patiki"),
        ]) == ("sneakers", "facet")

    def test_a_majority_wins(self):
        assert derive_category([
            offer("a", path="patiki"),
            offer("b", path="Патики-високи"),
            offer("c", path="Чизми"),
        ]) == ("sneakers", "facet")

    def test_a_tie_between_leaves_falls_back_to_the_parent(self):
        """"A shoe, and the shops disagree which kind" is a true statement.

        Picking a side would not be, and the parent category exists to say
        exactly this -- see V17.
        """
        assert derive_category([
            offer("a", path="patiki"),
            offer("b", path="Чизми"),
        ]) == ("footwear", "facet")

    def test_a_title_breaks_a_tie_between_facets(self):
        """The one place the weaker source decides.

        Found in the live catalogue: 15 products sat in the generic parent
        bucket because two shops shelved them differently, while their own
        titles said "Terrex" or "Predator" plainly. Two shops disagreeing
        does not make a shoe unknowable, and the parent is only the right
        answer when nothing else can speak.
        """
        assert derive_category([
            offer("a", path="patiki", title="Adidas TERREX AX4 GTX"),
            offer("b", path="Чизми", title="Adidas TERREX AX4 GTX"),
        ]) == ("shoes_boots", "title")

    def test_a_tie_with_a_silent_title_still_gives_the_parent(self):
        assert derive_category([
            offer("a", path="patiki", title="adidas Samba OG"),
            offer("b", path="Чизми", title="adidas Samba OG"),
        ]) == ("footwear", "facet")

    def test_a_non_footwear_title_cannot_break_a_footwear_tie(self):
        """Both shops say it is a shoe; they only disagree about which kind.

        A stray sock word in the title is not grounds to overrule that, so
        the tie-break takes footwear readings only.
        """
        assert derive_category([
            offer("a", path="patiki", title="Чорапи Nike"),
            offer("b", path="Чизми", title="Чорапи Nike"),
        ]) == ("footwear", "facet")

    def test_facet_beats_title(self):
        """A title keyword cannot overrule the shop's own department.

        This offer's title says Папучи, which on its own classifies as
        slides; the shop filed it under its sneakers facet, and the shop is
        the stronger source.

        This reverses the order ``create_product`` used before V17, where the
        title won and the hint was only consulted on silence. That ordering
        was right for the hint it had -- a generic "footwear", which cannot
        settle a leaf -- and it was the rule that kept a pack of socks out of
        the footwear tree in V10. So the reversal was checked rather than
        assumed: across all 4,537 offers a facet walk has labelled, the
        number whose title names a *non*-footwear kind is zero. The two
        sources do not disagree about whether something is a shoe, so the
        simpler rule is also the safe one. If that ever stops being true, this
        is the test that should gain a non-footwear veto -- and the measure
        above is how to know.
        """
        assert derive_category([
            offer(path="patiki", title="Папучи NIKE SOMETHING"),
        ]) == ("sneakers", "facet")

    def test_an_unknown_label_is_not_evidence(self):
        """A facet label no plan declares means nothing, so it decides nothing.

        It would be worse than useless to map it to a plausible bucket: the
        label exists precisely to be looked up, and a miss means a plan
        changed without this mapping changing with it.
        """
        assert derive_category([offer(path="totally-new-facet")]) == (None, None)


class TestCategoryFromTitles:
    def test_used_when_no_facet_covered_the_product(self):
        assert derive_category([
            offer(title="JQ2626 Патики GALAXY 7 M - Megasport"),
        ]) == ("sneakers", "title")

    def test_silence_stays_silent(self):
        assert derive_category([offer(title="adidas Supernova Rise")]) == \
            (None, None)
        assert derive_category([]) == (None, None)

    def test_disagreement_about_whether_it_is_even_a_shoe_is_unresolved(self):
        """One title says socks, another says sneakers, and there are two.

        Averaging kinds is how a pack of socks ended up in the footwear
        storefront (V10). A null is a question someone can answer; a wrong
        value looks finished.
        """
        assert derive_category([
            offer("a", title="GH0331 Чорапи CREW SOCK 3P"),
            offer("b", title="Патики GALAXY 7"),
        ]) == (None, None)

    def test_a_title_tie_within_footwear_still_gives_the_parent(self):
        assert derive_category([
            offer("a", title="Чизми Timberland"),
            offer("b", title="Папучи Adilette"),
        ]) == ("footwear", "title")


class TestGender:
    def test_one_department(self):
        assert derive_gender([offer(gender="men")]) == ("men", "facet")
        assert derive_gender([offer(gender="kids")]) == ("kids", "facet")

    def test_both_adult_departments_is_what_unisex_means(self):
        """Not a compromise -- the shops' own construction.

        Sport Vision lists a unisex article in both "maski+unisex" and
        "unisex+zenski". Appearing in both adult departments is the only
        evidence either shop publishes for it, and buzz alone has 279 such
        products that a NOT NULL DEFAULT could never distinguish from
        "nobody looked".
        """
        assert derive_gender([
            offer("a", gender="men"), offer("b", gender="women"),
        ]) == ("unisex", "facet")

    def test_kids_plus_adult_is_left_unresolved(self):
        """This is a defect report, not a product attribute.

        Either a shop mis-shelved it or two different articles were merged
        into one product. Both are worth seeing; neither is worth averaging.
        """
        assert derive_gender([
            offer("a", gender="kids"), offer("b", gender="men"),
        ]) == (None, None)
        assert derive_gender([
            offer("a", gender="kids"), offer("b", gender="women"),
        ]) == (None, None)

    def test_one_shop_can_already_say_unisex(self):
        """The facet walk collapses a shop's own overlapping departments, so
        a single offer arrives already reading `unisex`."""
        assert derive_gender([offer(gender="unisex")]) == ("unisex", "facet")
        assert derive_gender([
            offer("a", gender="unisex"), offer("b", gender="men"),
        ]) == ("unisex", "facet")

    def test_title_is_the_fallback(self):
        assert derive_gender([offer(title="Патики за деца Nike")]) == \
            ("kids", "title")

    def test_silence(self):
        assert derive_gender([offer(title="adidas Samba OG")]) == (None, None)
        assert derive_gender([]) == (None, None)

    def test_never_invents_unisex_from_a_title(self):
        """``unisex`` is a two-facet finding and must stay one.

        If a title could produce it, "unisex" would quietly become the same
        catch-all that the schema default was before V17.
        """
        got, source = derive_gender([offer(title="Patiki unisex Nike")])
        assert got != "unisex"

    def test_every_value_fits_the_enum(self):
        cases = [
            [offer(gender="men")], [offer(gender="women")],
            [offer(gender="kids")],
            [offer("a", gender="men"), offer("b", gender="women")],
            [offer(title="za deca")],
        ]
        for case in cases:
            got, _ = derive_gender(case)
            assert got is None or got in KNOWN_GENDERS | {"unisex"}, got


class TestFacetPlans:
    """The plans are data, and wrong data here mislabels a whole shop."""

    def test_every_shop_with_offers_has_a_plan(self):
        assert set(FACET_PLANS) == {"sportvision", "sportreality", "buzz",
                                    "megasport", "sizeer", "sportm"}

    def test_every_facet_carries_both_a_category_and_a_gender(self):
        """A facet missing either is a facet that teaches us nothing."""
        for slug, plan in FACET_PLANS.items():
            for facet in as_facets(plan.categories):
                assert facet.category, (slug, facet.path)
                assert facet.gender, (slug, facet.path)
                assert facet.label, (slug, facet.path)

    def test_every_category_is_a_footwear_leaf_we_seeded(self):
        for slug, plan in FACET_PLANS.items():
            for facet in as_facets(plan.categories):
                assert facet.category in FOOTWEAR_SLUGS, (slug, facet.category)

    def test_every_gender_is_a_department_not_a_conclusion(self):
        """Facets record men/women/kids. ``unisex`` is derived from two of
        them and must never be asserted by one."""
        for slug, plan in FACET_PLANS.items():
            for facet in as_facets(plan.categories):
                assert facet.gender in FACET_GENDERS, (slug, facet.gender)

    def test_labels_that_repeat_across_shops_agree(self):
        """"patiki" is a label on both Sport Vision and megasport.

        FACET_CATEGORY is a single flat mapping, so two shops using one label
        for different things would silently overwrite each other.
        """
        for slug, plan in FACET_PLANS.items():
            for facet in as_facets(plan.categories):
                assert FACET_CATEGORY[facet.label] == facet.category, (
                    slug, facet.label)

    def test_the_three_genders_are_all_present_per_shop(self):
        """Every shop sells to men, women and children.

        A shop missing a department would mean a third of its catalogue keeps
        a NULL gender for no reason other than a typo in a plan.
        """
        for slug, plan in FACET_PLANS.items():
            genders = {f.gender for f in as_facets(plan.categories)}
            assert genders == {"men", "women", "kids"}, (slug, genders)

    @pytest.mark.parametrize("slug,expected", [
        # Verified by fetching each one: sportreality's women's Копачки and
        # all three of buzz's came back with zero products, and buzz's titles
        # agree -- not one of its 1,921 offers carries a cleat word.
        ("sportvision", 12), ("sportreality", 12), ("buzz", 9),
        ("megasport", 14), ("sizeer", 16), ("sportm", 28),
    ])
    def test_facet_counts_are_what_recon_found(self, slug, expected):
        assert len(as_facets(FACET_PLANS[slug].categories)) == expected

    def test_the_aspnet_shops_share_a_product_group_dictionary(self):
        """PodGrupa is shared between sizeer and sport-m; Segment is not.

        That asymmetry is why MERCHANT_PLANS exists at all -- reading
        sizeer's Segment=03 as its whole catalogue cost us 599 products -- and
        it cuts the other way here: the group codes really are the same
        dictionary, so 503 is "Патики-ниски" on both.
        """
        def codes(slug):
            return {f.path.rsplit("PodGrupa=", 1)[1]: f.category
                    for f in as_facets(FACET_PLANS[slug].categories)}

        sizeer, sportm = codes("sizeer"), codes("sportm")
        shared = set(sizeer) & set(sportm)
        assert shared, "the two shops should share group codes"
        for code in shared:
            assert sizeer[code] == sportm[code], code

    def test_the_shops_ask_for_their_own_departments(self):
        """Segment numbering is per installation, as MERCHANT_PLANS records."""
        def segments(slug):
            return {f.path.split("Segment=")[1].split("&")[0]
                    for f in as_facets(FACET_PLANS[slug].categories)}

        assert segments("sizeer") == {"51", "52", "53"}
        assert segments("sportm") == {"03", "04", "05"}


# ===========================================================================
# Re-derivation over real rows -- needs Postgres
# ===========================================================================

import os  # noqa: E402

DSN = os.environ.get(
    "MKAGG_TEST_DSN",
    "postgresql://mkagg:mkagg_dev_only@localhost:5433/mkagg_test")


@pytest.fixture(scope="module")
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


def _product(conn, *, slug, category=None, source=None, gender=None,
             gender_source=None):
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO product (brand_id, category_id, category_source,
                                    gender, gender_source, model_name,
                                    canonical_name, primary_mpn, slug)
               VALUES ((SELECT id FROM brand LIMIT 1),
                       (SELECT id FROM category WHERE slug = %s),
                       %s, %s::gender_t, %s, %s, %s, %s, %s)
               RETURNING id""",
            (category, source, gender, gender_source, slug, slug, slug, slug))
        return cur.fetchone()[0]


def _offer(conn, product_id, *, merchant="sportvision", path=None,
           gender=None, title="adidas Supernova Rise", sku=None):
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO merchant_offer (merchant_id, product_id,
                        merchant_sku, raw_title, product_url,
                        merchant_category_path, merchant_gender, status)
               VALUES ((SELECT id FROM merchant WHERE slug = %s), %s, %s, %s,
                       %s, %s, %s, 'active')""",
            (merchant, product_id, sku or f"{product_id}-{merchant}", title,
             f"https://x/{product_id}/{merchant}", path, gender))


class TestRederiveOverRows:
    """The runner, against real rows -- where the guards actually matter."""

    def test_a_facet_fills_what_the_title_never_said(self, clean_db):
        """The case the whole exercise exists for.

        2,767 products sat in the generic `footwear` bucket because their
        titles are bare "Brand Model" and nothing ever revisited them. One
        facet walk and one re-derivation is the repair.
        """
        from mkagg.derive import rederive
        pid = _product(clean_db, slug="p1", category="footwear",
                       source="title")
        _offer(clean_db, pid, path="kopacki", gender="men")
        clean_db.commit()

        rederive(clean_db)

        with clean_db.cursor() as cur:
            cur.execute("""SELECT c.slug, p.category_source, p.gender::text,
                                  p.gender_source
                             FROM product p
                             JOIN category c ON c.id = p.category_id
                            WHERE p.id = %s""", (pid,))
            assert cur.fetchone() == ("cleats", "facet", "men", "facet")

    def test_running_it_twice_changes_nothing(self, clean_db):
        """Idempotence is the property that makes this safe to schedule."""
        from mkagg.derive import rederive
        pid = _product(clean_db, slug="p2")
        _offer(clean_db, pid, path="patiki", gender="women")
        clean_db.commit()

        first = rederive(clean_db)
        second = rederive(clean_db)
        assert first.category_set == 1
        assert second.category_set == 0
        assert second.unchanged == second.products

    def test_a_title_guess_never_overwrites_a_facet(self, clean_db):
        """The no-downgrade guard.

        A walk that simply did not reach this product must not cost it the
        evidence an earlier walk found. Without this, every re-derivation run
        between facet walks would quietly erode the catalogue back to title
        guesses.
        """
        from mkagg.derive import rederive
        pid = _product(clean_db, slug="p3", category="cleats", source="facet",
                       gender="men", gender_source="facet")
        # No facet label on the offer any more, and a title that reads as
        # something else entirely.
        _offer(clean_db, pid, title="Папучи Adilette")
        clean_db.commit()

        report = rederive(clean_db)

        with clean_db.cursor() as cur:
            cur.execute("""SELECT c.slug, p.category_source
                             FROM product p
                             JOIN category c ON c.id = p.category_id
                            WHERE p.id = %s""", (pid,))
            assert cur.fetchone() == ("cleats", "facet")
        assert report.kept_facet == 1

    def test_a_tie_break_is_not_a_downgrade(self, clean_db):
        """The guard asks whether facets were visible, not who decided.

        This product's facets still disagree, so the title breaks the tie --
        and the result must be allowed to replace the parent-bucket value an
        earlier pass stored, even though the earlier one was marked 'facet'.
        An over-eager guard pinned 16 real products in the generic bucket.
        """
        from mkagg.derive import rederive
        pid = _product(clean_db, slug="p7", category="footwear",
                       source="facet")
        _offer(clean_db, pid, merchant="sportvision", path="patiki",
               title="Adidas TERREX AX4 GTX")
        _offer(clean_db, pid, merchant="megasport", path="chizmi",
               title="Adidas TERREX AX4 GTX")
        clean_db.commit()

        report = rederive(clean_db)

        with clean_db.cursor() as cur:
            cur.execute("""SELECT c.slug, p.category_source FROM product p
                             JOIN category c ON c.id = p.category_id
                            WHERE p.id = %s""", (pid,))
            assert cur.fetchone() == ("shoes_boots", "title")
        assert report.kept_facet == 0

    def test_two_shops_make_a_product_unisex(self, clean_db):
        from mkagg.derive import rederive
        pid = _product(clean_db, slug="p4")
        _offer(clean_db, pid, merchant="sportvision", path="patiki",
               gender="men")
        _offer(clean_db, pid, merchant="buzz", path="patiki", gender="women")
        clean_db.commit()

        rederive(clean_db)

        with clean_db.cursor() as cur:
            cur.execute("SELECT gender::text FROM product WHERE id = %s",
                        (pid,))
            assert cur.fetchone()[0] == "unisex"

    def test_a_product_nothing_says_anything_about_stays_null(self, clean_db):
        from mkagg.derive import rederive
        pid = _product(clean_db, slug="p5")
        _offer(clean_db, pid, title="adidas Handball Spezial")
        clean_db.commit()

        rederive(clean_db)

        with clean_db.cursor() as cur:
            cur.execute("""SELECT category_id, category_source, gender,
                                  gender_source FROM product WHERE id = %s""",
                        (pid,))
            assert cur.fetchone() == (None, None, None, None)

    def test_dry_run_writes_nothing(self, clean_db):
        from mkagg.derive import rederive
        pid = _product(clean_db, slug="p6")
        _offer(clean_db, pid, path="kopacki", gender="kids")
        clean_db.commit()

        report = rederive(clean_db, dry_run=True)
        assert report.category_set == 1

        with clean_db.cursor() as cur:
            cur.execute("SELECT category_id FROM product WHERE id = %s",
                        (pid,))
            assert cur.fetchone()[0] is None


class TestAPersonOutranksBothSources:
    """`manual`, the third source V22 added.

    It exists for a shop that contradicts itself. Sport Reality shelves
    `puma-wardrobe-essentials-62974230` under `/mk/gradnik/`, badges it
    ГРАДНИК, and describes it on the same page as a "женска lifestyle slim
    маица". The facet is wrong, the title names no garment, and descriptions
    are weaker evidence than either -- a bra listing routinely describes the
    top worn over it. So a person decides, and the decision has to survive
    every later pass.
    """

    def test_a_manual_category_survives_a_contradicting_facet(self, clean_db):
        """The exact shape of the Puma row: a live facet saying otherwise.

        This is what separates `manual` from `facet`. The existing guard
        keeps a facet value only when *no* offer carries facet evidence; here
        one does, and says bra.
        """
        from mkagg.derive import rederive
        pid = _product(clean_db, slug="p-manual", category="tshirts",
                       source="manual")
        _offer(clean_db, pid, path="gradnik", title="Puma Wardrobe Essentials")
        clean_db.commit()

        report = rederive(clean_db)
        assert report.kept_manual == 1

        with clean_db.cursor() as cur:
            cur.execute("""SELECT c.slug, p.category_source
                             FROM product p
                             JOIN category c ON c.id = p.category_id
                            WHERE p.id = %s""", (pid,))
            assert cur.fetchone() == ("tshirts", "manual")

    def test_it_survives_being_re_derived_twice(self, clean_db):
        """A guard that holds once and not twice is worse than none: the row
        would look corrected until the next scheduled pass."""
        from mkagg.derive import rederive
        pid = _product(clean_db, slug="p-manual-2", category="tshirts",
                       source="manual")
        _offer(clean_db, pid, path="gradnik", title="Puma Wardrobe Essentials")
        clean_db.commit()

        rederive(clean_db)
        rederive(clean_db)

        with clean_db.cursor() as cur:
            cur.execute("""SELECT c.slug FROM product p
                             JOIN category c ON c.id = p.category_id
                            WHERE p.id = %s""", (pid,))
            assert cur.fetchone()[0] == "tshirts"

    def test_a_manual_gender_is_kept_the_same_way(self, clean_db):
        from mkagg.derive import rederive
        pid = _product(clean_db, slug="p-manual-3", category="tshirts",
                       source="manual", gender="women",
                       gender_source="manual")
        _offer(clean_db, pid, path="gradnik", gender="men",
               title="Puma Wardrobe Essentials")
        clean_db.commit()

        rederive(clean_db)

        with clean_db.cursor() as cur:
            cur.execute("""SELECT gender::text, gender_source FROM product
                            WHERE id = %s""", (pid,))
            assert cur.fetchone() == ("women", "manual")

    def test_nothing_else_is_frozen_by_it(self, clean_db):
        """The guard must key on the source, not leak onto its neighbours."""
        from mkagg.derive import rederive
        kept = _product(clean_db, slug="p-kept", category="tshirts",
                        source="manual")
        _offer(clean_db, kept, path="gradnik")
        moved = _product(clean_db, slug="p-moved", category="footwear",
                         source="title")
        _offer(clean_db, moved, path="kopacki")
        clean_db.commit()

        report = rederive(clean_db)
        assert report.kept_manual == 1

        with clean_db.cursor() as cur:
            cur.execute("""SELECT p.slug, c.slug FROM product p
                             JOIN category c ON c.id = p.category_id
                            ORDER BY p.slug""")
            assert cur.fetchall() == [("p-kept", "tshirts"),
                                      ("p-moved", "cleats")]


class TestAnExplicitUnisexFacetIsEvidence:
    """A department that says Унисекс outright.

    Until Опрема, unisex could only ever be *inferred*: an article listed in
    both `maski+unisex` and `unisex+zenski` resolves to unisex because it was
    found in two departments. That is all the footwear and apparel plans can
    produce, and it is fine for them -- footwear is 4.2 percent unisex and
    apparel 0.2.

    Equipment is 55 to 66 percent unisex on the two shops that count it, and
    Sport Reality's section carries no men's or women's URL at all for those
    404 articles -- only a Унисекс filter. Inference has nothing to work
    with there, so the facet has to be allowed to say it.
    """

    def test_one_offer_can_carry_it(self, clean_db):
        from mkagg.derive import rederive
        pid = _product(clean_db, slug="u1")
        _offer(clean_db, pid, path="ranci", gender="unisex")
        clean_db.commit()

        rederive(clean_db)

        with clean_db.cursor() as cur:
            cur.execute("""SELECT gender::text, gender_source FROM product
                            WHERE id = %s""", (pid,))
            assert cur.fetchone() == ("unisex", "facet")

    def test_it_agrees_with_the_inferred_kind(self, clean_db):
        """An explicit unisex and a men's listing are not a contradiction.

        Both say "adults, not only one department", so they collapse the
        same way two opposing departments would.
        """
        from mkagg.derive import rederive
        pid = _product(clean_db, slug="u2")
        _offer(clean_db, pid, merchant="sportvision", path="ranci",
               gender="unisex")
        _offer(clean_db, pid, merchant="megasport", path="ranci",
               gender="men")
        clean_db.commit()

        rederive(clean_db)

        with clean_db.cursor() as cur:
            cur.execute("SELECT gender::text FROM product WHERE id = %s",
                        (pid,))
            assert cur.fetchone()[0] == "unisex"

    def test_a_title_still_cannot_claim_it(self):
        """The narrower promise, unchanged: only a department may say this."""
        from mkagg.taxonomy import KNOWN_GENDERS, classify_gender
        assert "unisex" not in KNOWN_GENDERS
        for title in ("adidas Ранец Unisex", "Nike Backpack unisex adult"):
            assert classify_gender(title) != "unisex"


class TestTheShelfThePageStates:
    """A shelf no facet can name, and an umbrella that names no garment.

    Two vocabularies reach ``merchant_category_path``. A facet label comes
    from a plan the crawler walked, so the plan already holds its meaning.
    A shelf read off the product page does not: sport-m's sidebar counts 27
    apparel subgroups and its navigation links 18, so nine of them -- Градник,
    Пододело, Дресови-фудбал among them -- are addressable by no `PodGrupa`
    code, and the page is the only place they are stated. 919 products were
    reachable only through the department umbrella, which reads "Текстил".
    """

    def test_a_facet_label_still_wins_outright(self):
        """The dict comes first: it is checked across shops by its own test."""
        assert derive_category([offer(path="Патики-ниски")]) == (
            "sneakers", "facet")

    def test_a_shelf_no_plan_names_is_classified(self):
        """Not one of these nine has a facet, so the dict cannot hold it."""
        for path, expected in (("Градник", "sports_bras"),
                               ("Пододело", "underwear"),
                               ("Дресови-фудбал", "tshirts"),
                               ("Дресови-кошарка", "tshirts"),
                               ("Шорцеви-кошарка", "shorts"),
                               ("Ски Панталони", "trousers"),
                               ("Долна облека", "underwear"),
                               ("Бициклистички", "leggings")):
            assert derive_category([offer(path=path)]) == (expected, "facet")

    def test_a_shelf_is_facet_evidence_not_a_title(self):
        """It is the shop naming its own shelf, so it outranks any title."""
        assert derive_category([
            offer(path="Градник", title="Puma Wardrobe Essentials Tee"),
        ]) == ("sports_bras", "facet")

    def test_an_umbrella_does_not_outrank_a_title(self):
        """"Clothing" and "маица" do not conflict; the second refines it.

        This is what freed sizeer, whose product pages state no subgroup at
        all: 64 of its 91 umbrella products had titles that named the garment
        and were being outranked by a shelf that named only the vertical.
        """
        assert derive_category([
            offer(path="Текстил", title="Nike Маица Sportswear Club"),
        ]) == ("tshirts", "title")

    def test_a_leaf_shelf_beats_an_umbrella_on_another_shop(self):
        assert derive_category([
            offer("sizeer", path="Текстил"),
            offer("sportm", path="Градник"),
        ]) == ("sports_bras", "facet")

    def test_an_umbrella_still_beats_silence(self):
        """Weakest honest answer, and better than NULL."""
        assert derive_category([offer(path="Текстил")]) == (
            "apparel", "facet")

    def test_an_umbrella_survives_titles_that_disagree(self):
        """Two shops arguing over the leaf have not unsaid the vertical."""
        assert derive_category([
            offer("a", path="Текстил", title="Nike Маица Club"),
            offer("b", path="Текстил", title="Nike Панталони Club"),
        ]) == ("apparel", "facet")

    def test_a_shelf_the_tree_has_no_row_for_stays_in_the_parent(self):
        """`Топ` is not a rule, on purpose.

        Keywords match whole words, and ``top`` is a whole word in "Converse
        Chuck Taylor All Star High Top" -- a shoe. Sixteen products across
        three shelves sit in the parent bucket rather than buy them with a
        rule that would misfile sneakers as bras.
        """
        for path in ("Заштитен сет за дожд", "Комбинезони", "Топ"):
            assert derive_category([offer(path=path)]) == (None, None)
