import {createClient} from '@supabase/supabase-js';

// Build-time placeholders keep `next build` deterministic; deployed/local
// environments must provide the public Supabase variables.
const url=process.env.NEXT_PUBLIC_SUPABASE_URL||'https://placeholder.supabase.co';
const key=process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY||'placeholder-publishable-key';
export const supabase=createClient(url,key,{auth:{persistSession:true,autoRefreshToken:true,detectSessionInUrl:true}});
