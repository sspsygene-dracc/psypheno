import { describe, it, expect } from "vitest";
import type { NextApiRequest, NextApiResponse } from "next";
import handler from "@/pages/api/search-text";

interface MockRes extends NextApiResponse {
  _status: number;
  _json: unknown;
  _headers: Record<string, string>;
}

function mockReq(opts: {
  method?: string;
  query?: Record<string, string>;
}): NextApiRequest {
  return {
    method: opts.method ?? "GET",
    body: undefined,
    query: opts.query ?? {},
    headers: {},
    cookies: {},
  } as unknown as NextApiRequest;
}

function mockRes(): MockRes {
  const res: Partial<MockRes> & {
    _status: number;
    _json: unknown;
    _headers: Record<string, string>;
  } = {
    _status: 0,
    _json: undefined,
    _headers: {},
  };
  res.status = function (code: number) {
    this._status = code;
    return this as MockRes;
  };
  res.json = function (body: unknown) {
    this._json = body;
    return this as MockRes;
  };
  res.setHeader = function (name: string, value: string | number | string[]) {
    this._headers[name.toLowerCase()] = String(value);
    return this as MockRes;
  };
  return res as MockRes;
}

describe("api/search-text", () => {
  it("returns 405 for non-GET methods", async () => {
    const res = mockRes();
    await handler(mockReq({ method: "POST" }), res);
    expect(res._status).toBe(405);
    expect(res._json).toEqual({ error: "Method not allowed" });
  });

  it("returns 400 when 'text' is missing", async () => {
    const res = mockRes();
    await handler(mockReq({ method: "GET", query: {} }), res);
    expect(res._status).toBe(400);
  });

  it("returns 200 with empty suggestions for empty text", async () => {
    const res = mockRes();
    await handler(mockReq({ method: "GET", query: { text: "" } }), res);
    expect(res._status).toBe(200);
    expect(res._json).toEqual({ suggestions: [] });
  });

  it("sets a Cache-Control header on success", async () => {
    const res = mockRes();
    await handler(mockReq({ method: "GET", query: { text: "BRCA" } }), res);
    expect(res._status).toBe(200);
    expect(res._headers["cache-control"]).toMatch(/max-age=\d+/);
  });

  it("returns 200 with suggestions for a real prefix", async () => {
    const res = mockRes();
    await handler(mockReq({ method: "GET", query: { text: "BRCA" } }), res);
    expect(res._status).toBe(200);
    const body = res._json as {
      suggestions: Array<{
        centralGeneId: number;
        humanSymbol: string | null;
      }>;
      searchText: string;
    };
    expect(Array.isArray(body.suggestions)).toBe(true);
    expect(body.suggestions.length).toBeGreaterThan(0);
    expect(body.searchText).toBe("BRCA");
    const symbols = body.suggestions.map((s) => s.humanSymbol);
    expect(symbols).toContain("BRCA1");
    expect(symbols).toContain("BRCA2");
  });

  it("rejects an invalid 'direction' value", async () => {
    const res = mockRes();
    await handler(
      mockReq({
        method: "GET",
        query: { text: "BRCA", direction: "sideways" },
      }),
      res,
    );
    expect(res._status).toBe(400);
  });

  it("direction-filtered count <= unfiltered count", async () => {
    const all = mockRes();
    await handler(mockReq({ method: "GET", query: { text: "BRCA" } }), all);
    const filtered = mockRes();
    await handler(
      mockReq({
        method: "GET",
        query: { text: "BRCA", direction: "target" },
      }),
      filtered,
    );
    expect(all._status).toBe(200);
    expect(filtered._status).toBe(200);
    const allBody = all._json as { suggestions: unknown[] };
    const filteredBody = filtered._json as { suggestions: unknown[] };
    expect(filteredBody.suggestions.length).toBeLessThanOrEqual(
      allBody.suggestions.length,
    );
  });
});
