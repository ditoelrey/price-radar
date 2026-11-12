import type { NextConfig } from "next";

const API_BASE = (process.env.API_BASE_URL ?? "http://localhost:8080").replace(
  /\/$/,
  "",
);

const nextConfig: NextConfig = {
  /**
   * Proxy the outbound redirect to the Spring API.
   *
   * The API renders every buy button as a relative `/out/{variantId}`, which
   * is deliberate: the click must stay same-origin. Without this rewrite the
   * browser asks Next for `/out/368`, Next has no such route, and the button
   * 404s — the one path in the product that must never fail.
   *
   * A rewrite rather than an absolute URL to :8080, because same-origin
   * clicks keep the two services behind one domain in production, avoid a
   * cross-origin hop on the revenue path, and let the API's own
   * `Referrer-Policy: no-referrer` govern what the shop sees.
   *
   * Next passes the proxied status and headers straight through, so the
   * API's 302 and its `no-store` reach the browser unchanged.
   */
  async rewrites() {
    return [
      { source: "/out/:variantId", destination: `${API_BASE}/out/:variantId` },
    ];
  },

  // Images are hotlinked from the shops' own CDNs for the MVP. They are
  // served through a plain <img>, not next/image, because a remote allowlist
  // would need editing every time a merchant is added — and would fail
  // closed, blanking that shop's photos with no error anywhere.
  images: { unoptimized: true },
};

export default nextConfig;
