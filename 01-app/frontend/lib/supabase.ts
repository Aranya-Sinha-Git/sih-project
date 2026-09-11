import {createClient} from '@supabase/supabase-js';

// Keep the build deterministic, but expose only a boolean configuration
// signal to the UI. Public values are never treated as secrets here.
const configuredUrl=process.env.NEXT_PUBLIC_SUPABASE_URL?.trim()||'';
const configuredKey=process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY?.trim()||'';
export const supabaseConfigured=Boolean(configuredUrl&&configuredKey);
const url=configuredUrl||'https://placeholder.supabase.co';
const key=configuredKey||'placeholder-publishable-key';
export const supabase=createClient(url,key,{auth:{persistSession:true,autoRefreshToken:true,detectSessionInUrl:true}});
