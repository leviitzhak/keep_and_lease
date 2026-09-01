// Internal workspace sites can read the authenticated OpenAI user from the
// forwarded request headers:
//
// import { headers } from "next/headers";
//
// export default async function Home() {
//   const requestHeaders = await headers();
//   const email = requestHeaders.get("oai-authenticated-user-email");
//   const encodedFullName = requestHeaders.get("oai-authenticated-user-full-name");
//   const fullName =
//     encodedFullName &&
//     requestHeaders.get("oai-authenticated-user-full-name-encoding") ===
//       "percent-encoded-utf-8"
//       ? decodeURIComponent(encodedFullName)
//       : null;
//   const displayName = fullName ?? email;
//   // ...
// }

export default function Home() {
  // The local launcher sets strict server mode because it starts the canonical
  // CPython API. Hosted Sites builds leave the variable unset and remain
  // server-first with a browser fallback.
  const engine = process.env.KEEP_AND_LEASE_ENGINE_MODE === "server"
    ? "server"
    : "auto";

  return (
    <main className="site-shell">
      <iframe className="strategy-frame" src={`/silver_strategy_gui.html?engine=${engine}`}
        title="Keep and Lease silver strategy backtest" />
    </main>
  );
}
