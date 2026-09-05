// Same-origin proxy avoids browser/CORS restrictions on the local API port.
export const API=process.env.NEXT_PUBLIC_API_URL||'/api';
function headers():HeadersInit{const token=typeof window==='undefined'?'':window.localStorage.getItem('sif-api-token')||'';return token?{'Authorization':`Bearer ${token}`}:{};}
async function checked<T>(r:Response):Promise<T>{if(r.status===401&&typeof window!=='undefined'){window.localStorage.removeItem('sif-api-token');window.location.href='/login';}if(!r.ok)throw new Error((await r.text())||`Request failed (${r.status})`);return r.json()}
export async function get<T>(path:string):Promise<T>{return checked<T>(await fetch(API+path,{cache:'no-store',headers:headers()}))}
export async function send<T>(path:string,method:string,body?:unknown):Promise<T>{return checked<T>(await fetch(API+path,{method,headers:{'Content-Type':'application/json',...headers()},body:body?JSON.stringify(body):undefined}))}
