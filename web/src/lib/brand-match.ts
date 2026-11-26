/**
 * Matching a brand a shopper typed in Macedonian against its Latin name.
 *
 * Brand names in the catalogue are the brands' own: Adidas, Reebok, New
 * Balance, Dolce & Gabbana. A Macedonian shopper types what they say --
 * `адидас`, `рибок`, `нју баланс` -- and a plain substring filter answers
 * every one of those with an empty list, which reads as "we do not carry it".
 *
 * Two passes, in this order, because the cheap one is also the precise one.
 *
 * **Substring.** Latin or Cyrillic, after transliterating the query. `адидас`
 * becomes `adidas` and matches outright; so does `пума`, `рибок` -> `ribok`
 * does not. This pass alone answers everything a shopper types in Latin and
 * everything whose Macedonian spelling is a letter-for-letter transcription.
 *
 * **Consonant skeleton.** Only when the first pass found nothing, and only
 * from three characters up. Both sides are reduced to their consonants with
 * the sounds Macedonian and English spell differently folded together -- c/k,
 * s/z, v/w, ph/f, doubled letters -- and the query's skeleton has to be a
 * prefix of the brand's. That is what carries `најк` to Nike (n-k), `рибок`
 * to Reebok (r-b-k) and `асикс` to Asics (s-k-s).
 *
 * It is deliberately a fallback and deliberately prefix-anchored: skeletons
 * are short, and matching them anywhere in a name would let a two-consonant
 * query pull in half the list. The cost of a miss here is small -- the shopper
 * sees fewer brands and can scroll the unfiltered list -- while the cost of
 * noise is a filter nobody trusts.
 */

/**
 * Macedonian Cyrillic to Latin, the way the shops' own URLs do it.
 *
 * Matches `mkagg.text.translit_mk` on the ingestion side, including `џ` as
 * `dj` rather than `dz`, so the two halves of the project read a pasted
 * Macedonian word the same way.
 */
const CYRILLIC: Record<string, string> = {
  а: "a",
  б: "b",
  в: "v",
  г: "g",
  д: "d",
  ѓ: "gj",
  е: "e",
  ж: "zh",
  з: "z",
  ѕ: "dz",
  и: "i",
  ј: "j",
  к: "k",
  л: "l",
  љ: "lj",
  м: "m",
  н: "n",
  њ: "nj",
  о: "o",
  п: "p",
  р: "r",
  с: "s",
  т: "t",
  ќ: "kj",
  у: "u",
  ф: "f",
  х: "h",
  ц: "c",
  ч: "ch",
  џ: "dj",
  ш: "sh",
  // Not Macedonian, but a keyboard laid out for Serbian or Russian is a
  // normal thing to be typing on here.
  й: "j",
  ы: "i",
  э: "e",
  ю: "ju",
  я: "ja",
  ъ: "",
  ь: "",
};

/** Lower-cased and transliterated, so one side can be compared to the other. */
export function latinize(text: string): string {
  return Array.from(text.toLowerCase())
    .map((ch) => CYRILLIC[ch] ?? ch)
    .join("");
}

const VOWELS = new Set(["a", "e", "i", "o", "u", "y", "j"]);

/**
 * The consonants of a name, with the sounds the two languages spell
 * differently folded together.
 *
 * `j` counts as a vowel: it is how Macedonian writes the glide English leaves
 * out (`најк`, `nike`), so keeping it would make those two different words.
 */
function skeleton(text: string): string {
  let s = latinize(text)
    // Latin letters and digits only: `Dolce & Gabbana` and `D&G` have to
    // reduce to the same alphabet as what someone types.
    .replace(/[^a-z0-9]+/g, "")
    // `џ` transliterates to `dj`, which is how Macedonian writes the sound
    // `Jordan` starts with.
    .replace(/dj/g, "j")
    .replace(/ph/g, "f")
    // One hiss. Macedonian writes `ш` where English writes `ch` (`шампион`,
    // `champion`) and `че` where it writes `ce` (`версаче`, `Versace`).
    .replace(/ch|sh|zh/g, "s")
    .replace(/ck/g, "k")
    // Soft c, as in `balance`, is an s; everything else is a k, as in
    // `asics`. Macedonian writes both outright.
    .replace(/c(?=[eiy])/g, "s")
    .replace(/c/g, "k")
    .replace(/x/g, "ks")
    .replace(/q/g, "k")
    // Dropped rather than turned into a `v`: in a brand name it is nearly
    // always a glide Macedonian does not write at all -- `нју` for `New` --
    // and both sides lose it together, so `Wilson` still answers `вилсон`.
    .replace(/w/g, "")
    .replace(/z/g, "s");
  s = Array.from(s)
    .filter((ch) => !VOWELS.has(ch))
    .join("");
  // `reebok` and `рибок` only agree once doubled letters collapse.
  return s.replace(/(.)\1+/g, "$1");
}

/**
 * Does this brand answer what the shopper typed?
 *
 * An empty query matches everything, which is what an untouched search box
 * should do.
 */
export function brandMatches(query: string, name: string): boolean {
  const q = query.trim();
  if (q.length === 0) return true;

  const needle = latinize(q);
  const hay = latinize(name);
  if (hay.includes(needle) || hay.includes(q.toLowerCase())) {
    return true;
  }

  if (needle.replace(/[^a-z0-9]/g, "").length < 3) return false;
  const want = skeleton(q);
  return want.length > 0 && skeleton(name).startsWith(want);
}

/** The brands that answer a query, in the order they were given. */
export function filterBrands<T extends { label: string }>(
  options: readonly T[],
  query: string,
): T[] {
  const direct = options.filter((o) => {
    const hay = latinize(o.label);
    return hay.includes(latinize(query.trim()));
  });
  // The skeleton pass only when nothing matched outright, so a shopper typing
  // Latin never sees a phonetic guess beside an exact hit.
  return direct.length > 0 || query.trim() === ""
    ? direct
    : options.filter((o) => brandMatches(query, o.label));
}
