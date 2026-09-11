const configuredApi=process.env.NEXT_PUBLIC_API_URL?.trim();
export const API=configuredApi?configuredApi.replace(/\/+$/,''):'/api';
import {supabase} from './supabase';

async function headers():Promise<HeadersInit>{const {data}=await supabase.auth.getSession();return data.session?.access_token?{'Authorization':`Bearer ${data.session.access_token}`}:{}}
function validationMessage(payload:any):string{if(Array.isArray(payload)){return payload.map((item:any)=>{const location=Array.isArray(item?.loc)?item.loc.filter((part:any)=>part!=='body').join(' → '):'request';return `${location}: ${item?.msg||'invalid value'}`}).join('; ')}if(typeof payload?.detail==='string')return payload.detail;if(payload?.detail)return JSON.stringify(payload.detail);return 'Request could not be completed.'}
async function checked<T>(r:Response):Promise<T>{if(r.status===401&&typeof window!=='undefined'){await supabase.auth.signOut();window.location.href='/login';throw new Error('Your session has expired. Please sign in again.')}if(!r.ok){let payload:any;try{payload=await r.json()}catch{payload=null}if(r.status>=500)throw new Error('The service is temporarily unavailable.');throw new Error(validationMessage(payload))}return r.json()}
export async function get<T>(path:string):Promise<T>{return checked<T>(await fetch(API+path,{cache:'no-store',headers:await headers()}))}
export async function send<T>(path:string,method:string,body?:unknown):Promise<T>{return checked<T>(await fetch(API+path,{method,headers:{'Content-Type':'application/json',...(await headers())},body:body?JSON.stringify(body):undefined}))}
