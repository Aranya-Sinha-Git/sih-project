const configuredApi=process.env.NEXT_PUBLIC_API_URL?.trim();
export const API=configuredApi?configuredApi.replace(/\/+$/,''):'/api';
import {supabase} from './supabase';

async function headers():Promise<HeadersInit>{const {data}=await supabase.auth.getSession();return data.session?.access_token?{'Authorization':`Bearer ${data.session.access_token}`}:{}}
async function checked<T>(r:Response):Promise<T>{if(r.status===401&&typeof window!=='undefined'){await supabase.auth.signOut();window.location.href='/login';throw new Error('Your session has expired. Please sign in again.')}if(!r.ok){if(r.status>=500)throw new Error('The service is temporarily unavailable.');throw new Error('Request could not be completed.')}return r.json()}
export async function get<T>(path:string):Promise<T>{return checked<T>(await fetch(API+path,{cache:'no-store',headers:await headers()}))}
export async function send<T>(path:string,method:string,body?:unknown):Promise<T>{return checked<T>(await fetch(API+path,{method,headers:{'Content-Type':'application/json',...(await headers())},body:body?JSON.stringify(body):undefined}))}
