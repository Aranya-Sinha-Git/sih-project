'use client';
import {FormEvent,useState} from 'react';
import Link from 'next/link';
import {ShieldAlert} from 'lucide-react';

export default function Login(){
  const [token,setToken]=useState(''); const [error,setError]=useState('');
  function submit(event:FormEvent){event.preventDefault();if(!token.trim()){setError('Enter the reviewer token.');return}window.localStorage.setItem('sif-api-token',token.trim());window.location.href='/';}
  function signOut(){window.localStorage.removeItem('sif-api-token');setToken('');setError('Signed out.');}
  return <main style={{minHeight:'100vh',display:'grid',placeItems:'center',padding:20}}><section className="panel" style={{width:'min(440px,100%)',padding:28}}><div className="brand" style={{color:'#17252c'}}><span className="brand-mark"><ShieldAlert size={16}/></span>SIF Sentinel</div><p className="subtle">Enter the server-issued reviewer token for this workspace.</p><form onSubmit={submit}><label className="input-label" htmlFor="reviewer-token">Reviewer token</label><input id="reviewer-token" className="input" type="password" value={token} onChange={event=>setToken(event.target.value)} autoComplete="off"/><button className="button" style={{display:'block',width:'100%',marginTop:12}}>Open workspace</button></form>{error&&<p className="error" role="alert">{error}</p>}<button className="button secondary" style={{width:'100%',marginTop:10}} onClick={signOut}>Sign out</button><Link href="/" className="row-meta" style={{display:'block',marginTop:14}}>Use explicit loopback demo mode</Link></section></main>;
}
