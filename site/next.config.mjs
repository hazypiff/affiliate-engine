/** Static export: deployable to Cloudflare Pages (or any static host) per vertical domain. */
const nextConfig = {
  output: "export",
  images: { unoptimized: true },
};

export default nextConfig;
