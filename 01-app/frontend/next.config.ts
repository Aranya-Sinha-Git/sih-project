import type { NextConfig } from 'next';

const configuredBackend = process.env.BACKEND_URL?.trim().replace(/\/$/, '');
const configuredPublicApi = process.env.NEXT_PUBLIC_API_URL?.trim();
const backendUrl = configuredBackend || 'http://127.0.0.1:8000';

if (process.env.NETLIFY && !configuredBackend && !configuredPublicApi) {
  throw new Error(
    'Netlify deployment requires BACKEND_URL (recommended for the same-origin /api proxy) or NEXT_PUBLIC_API_URL.',
  );
}

const nextConfig: NextConfig = {
  reactStrictMode: true,
  devIndicators: false,
  async rewrites() {
    return [{source:'/api/:path*',destination:`${backendUrl}/:path*`}];
  },
};
export default nextConfig;
