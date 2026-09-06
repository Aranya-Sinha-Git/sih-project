import type { NextConfig } from 'next';

const configuredPublicApi = process.env.NEXT_PUBLIC_API_URL?.trim();

if (process.env.VERCEL && !configuredPublicApi) {
  throw new Error(
    'Vercel deployment requires NEXT_PUBLIC_API_URL.',
  );
}

const nextConfig: NextConfig = {
  reactStrictMode: true,
  devIndicators: false,
};
export default nextConfig;
