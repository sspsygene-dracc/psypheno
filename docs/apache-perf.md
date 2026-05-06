# Apache performance tweaks for psypheno.gi.ucsc.edu

This page is an email draft you can forward to the UCSC sysadmins to ask
them to enable HTTP/2 and brotli on the public-facing Apache vhost.

---

Hi,

Could you enable HTTP/2 and brotli on the Apache vhost serving
`psypheno.gi.ucsc.edu` / `psypheno-dev.gi.ucsc.edu` (and the
`sspsygene-data.ucsc.edu` alias)? Both are pure Apache config changes
— no app-side work needed. Details and the rationale below.

## Why

The site's per-request latency is dominated by network round-trips to
UCSC (~180 ms RTT from a typical client). Two server-side changes would
let users get more out of each round-trip:

1. **HTTP/2** — currently the server's ALPN advertises `http/1.1` only
   (verified with `curl --http2 -v https://psypheno-dev.gi.ucsc.edu/`).
   With HTTP/2, the browser can multiplex multiple in-flight
   autocomplete / API requests on a single TLS connection (no
   head-of-line blocking) and HPACK-compresses the request/response
   headers. The autocomplete experience involves bursts of small
   requests, so this is a meaningful win.
2. **Brotli** — currently only `gzip` is offered. Brotli typically
   compresses our JSON payloads ~30–40 % smaller than gzip
   (e.g. `/api/full-datasets`: 48 KB → 10 KB gzip → ~7 KB brotli).

Neither change requires a code deploy, and both are independent — feel
free to enable just one if the other is more involved.

## Suggested directives

Add these to the Apache config (typically the vhost's `*.conf`, or a
shared snippet under `conf.d/`):

```apache
# --- HTTP/2 ---
# Requires Apache built with mod_http2 (typically packaged as
# `mod_http2` on Rocky / RHEL). Add inside the existing
# <VirtualHost *:443> for the psypheno hostnames.
LoadModule http2_module modules/mod_http2.so
Protocols h2 http/1.1

# --- Brotli ---
# Requires mod_brotli. Quality 5 is the recommended balance:
# near-max compression ratio at low CPU cost.
LoadModule brotli_module modules/mod_brotli.so
<IfModule mod_brotli.c>
  AddOutputFilterByType BROTLI_COMPRESS \
    application/json application/javascript \
    text/html text/css text/plain text/xml \
    image/svg+xml application/xml
  BrotliCompressionQuality 5
</IfModule>
```

## How to verify after restart

Run these from outside UCSC (e.g. a laptop on a home network):

```bash
# Should report HTTP/2 (look for "ALPN: server accepted h2")
curl -sI --http2 -v https://psypheno-dev.gi.ucsc.edu/api/full-datasets 2>&1 \
  | grep -E "ALPN|HTTP/"

# Should report content-encoding: br and a smaller body
curl -sI -H 'Accept-Encoding: br' \
  https://psypheno-dev.gi.ucsc.edu/api/full-datasets \
  | grep -i content-encoding
curl -s  -H 'Accept-Encoding: br' \
  https://psypheno-dev.gi.ucsc.edu/api/full-datasets | wc -c
```

Expected: HTTP/2 negotiated, `content-encoding: br`, body ~6–8 KB
(vs. ~10 KB gzip / ~48 KB uncompressed).

Thanks!
— Johannes
