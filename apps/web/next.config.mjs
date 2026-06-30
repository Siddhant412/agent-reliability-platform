const apiBaseUrl = process.env.ARP_API_BASE_URL ?? "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${apiBaseUrl}/api/v1/:path*`,
      },
      {
        source: "/healthz",
        destination: `${apiBaseUrl}/healthz`,
      },
    ];
  },
};

export default nextConfig;
