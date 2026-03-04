/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
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
