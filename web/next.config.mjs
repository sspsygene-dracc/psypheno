/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // `next dev` takes a lock on its build directory, so a second dev server —
  // e.g. one pointed at a scratch SSPSYGENE_DATA_DB on another port, to verify
  // a rebuild without disturbing the one on :3000 — refuses to start. Give it
  // its own directory instead:
  //   NEXT_DIST_DIR=.next-scratch SSPSYGENE_DATA_DB=… PORT=3010 npm run dev
  distDir: process.env.NEXT_DIST_DIR || ".next",
  async redirects() {
    return [
      {
        source: "/combined-pvalues",
        destination: "/most-significant",
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
