export function SiteFooter() {
  return (
    <footer className="mt-16 border-t bg-muted/30">
      <div className="mx-auto max-w-7xl space-y-2 px-4 py-8 text-xs text-muted-foreground sm:px-6">
        <p>
          Prices and availability are reported by the shops and may have
          changed since we last checked. Every offer shows its own check time.
        </p>
        <p>
          price<span className="font-semibold">radar</span> earns a commission
          on some outbound clicks. That never changes the ranking: offers are
          always ordered by total price including delivery.
        </p>
      </div>
    </footer>
  );
}
