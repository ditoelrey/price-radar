import { redirect } from "next/navigation";

// The listing is the home page. A separate marketing landing page would only
// stand between a shopper and the prices they came for.
export default function Home() {
  redirect("/products");
}
