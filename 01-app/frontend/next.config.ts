import type { NextConfig } from 'next';

const configuredPublicApi = process.env.NEXT_PUBLIC_API_URL?.trim();
const configuredSupabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL?.trim();
const configuredSupabaseKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY?.trim();

if (process.env.VERCEL && (!configuredPublicApi || !configuredSupabaseUrl || !configuredSupabaseKey)) {
  throw new Error(
    'Vercel deployment requires NEXT_PUBLIC_API_URL, NEXT_PUBLIC_SUPABASE_URL, and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY.',
  );
}

const nextConfig: NextConfig = {
  reactStrictMode: true,
  devIndicators: false,
};
export default nextConfig;
