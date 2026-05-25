

const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

const nextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
