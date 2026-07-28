/** Cloudflare Worker entry point for the vinext-starter template. */
import { handleImageOptimization, DEFAULT_DEVICE_SIZES, DEFAULT_IMAGE_SIZES } from "vinext/server/image-optimization";
import handler from "vinext/server/app-router-entry";

interface Env {
  ASSETS: Fetcher;
  DB: D1Database;
  BUCKET: R2Bucket;
  IMAGES: {
    input(stream: ReadableStream): {
      transform(options: Record<string, unknown>): {
        output(options: { format: string; quality: number }): Promise<{ response(): Response }>;
      };
    };
  };
}

interface ExecutionContext {
  waitUntil(promise: Promise<unknown>): void;
  passThroughOnException(): void;
}

// Image security config. SVG sources with .svg extension auto-skip the
// optimization endpoint on the client side (served directly, no proxy).
// To route SVGs through the optimizer (with security headers), set
// dangerouslyAllowSVG: true in next.config.js and uncomment below:
// const imageConfig: ImageConfig = { dangerouslyAllowSVG: true };

const worker = {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const userId = request.headers.get("oai-authenticated-user-id") ??
      request.headers.get("oai-authenticated-user-email");

    if (url.pathname === "/api/strategy-state") {
      if (!userId) return Response.json({ error: "Authenticated user unavailable" }, { status: 401 });
      const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(userId));
      const key = `strategy-state/${Array.from(new Uint8Array(digest), byte =>
        byte.toString(16).padStart(2, "0")).join("")}.json.gz`;
      if (request.method === "GET") {
        const object = await env.BUCKET.get(key);
        if (!object) return new Response(null, { status: 204 });
        return new Response(object.body, {
          headers: {
            "content-type": "application/gzip",
            "cache-control": "no-store",
            "x-strategy-state-saved-at": object.customMetadata?.savedAt ?? "",
          },
        });
      }
      if (request.method === "PUT") {
        if (!request.body || request.headers.get("content-type") !== "application/gzip") {
          return Response.json({ error: "Expected a gzip result payload" }, { status: 400 });
        }
        const savedAt = new Date().toISOString();
        await env.BUCKET.put(key, request.body, {
          httpMetadata: { contentType: "application/gzip" },
          customMetadata: { savedAt },
        });
        return Response.json({ saved: true, savedAt });
      }
      return new Response("Method not allowed", { status: 405, headers: { Allow: "GET, PUT" } });
    }

    if (url.pathname === "/api/strategy-parameters") {
      if (!userId) return Response.json({ error: "Authenticated user unavailable" }, { status: 401 });
      await env.DB.prepare(`
        CREATE TABLE IF NOT EXISTS strategy_parameters (
          user_id TEXT PRIMARY KEY,
          parameters_json TEXT NOT NULL,
          updated_at INTEGER NOT NULL
        )
      `).run();
      if (request.method === "GET") {
        const row = await env.DB.prepare(
          "SELECT parameters_json, updated_at FROM strategy_parameters WHERE user_id = ?"
        ).bind(userId).first<{ parameters_json: string; updated_at: number }>();
        return Response.json(row
          ? { parameters: JSON.parse(row.parameters_json), updatedAt: row.updated_at }
          : { parameters: null, updatedAt: null });
      }
      if (request.method === "PUT") {
        const body = await request.json<{ parameters?: unknown }>();
        if (!body.parameters || typeof body.parameters !== "object" ||
            JSON.stringify(body.parameters).length > 20_000) {
          return Response.json({ error: "Invalid strategy parameters" }, { status: 400 });
        }
        const now = Date.now();
        await env.DB.prepare(`
          INSERT INTO strategy_parameters (user_id, parameters_json, updated_at)
          VALUES (?, ?, ?)
          ON CONFLICT(user_id) DO UPDATE SET
            parameters_json = excluded.parameters_json,
            updated_at = excluded.updated_at
        `).bind(userId, JSON.stringify(body.parameters), now).run();
        return Response.json({ saved: true, updatedAt: now });
      }
      return new Response("Method not allowed", { status: 405, headers: { Allow: "GET, PUT" } });
    }

    if (url.pathname === "/_vinext/image") {
      const allowedWidths = [...DEFAULT_DEVICE_SIZES, ...DEFAULT_IMAGE_SIZES];
      return handleImageOptimization(request, {
        fetchAsset: (path) => env.ASSETS.fetch(new Request(new URL(path, request.url))),
        transformImage: async (body, { width, format, quality }) => {
          const result = await env.IMAGES.input(body).transform(width > 0 ? { width } : {}).output({ format, quality });
          return result.response();
        },
      }, allowedWidths);
    }

    return handler.fetch(request, env, ctx);
  },
};

export default worker;
