'use client';
import {FormEvent,useEffect,useState} from 'react';
import {ShieldAlert} from 'lucide-react';
import {supabase} from '../../lib/supabase';
import {usernameToInternalEmail} from '../../lib/auth';

export default function Login(){
  const [username,setUsername]=useState(''); const [password,setPassword]=useState(''); const [error,setError]=useState(''); const [loading,setLoading]=useState(false); const showDemo=process.env.NEXT_PUBLIC_SHOW_DEMO_CREDENTIALS==='true';
  useEffect(()=>{supabase.auth.getSession().then(({data})=>{if(data.session)window.location.replace('/')})},[]);
  async function submit(event:FormEvent){event.preventDefault();setError('');if(!username.trim()||!password){setError('Enter your User ID and password.');return}setLoading(true);try{const {error}=await supabase.auth.signInWithPassword({email:usernameToInternalEmail(username),password});if(error)throw error;window.location.replace('/')}catch{setError('Incorrect User ID or password.')}finally{setLoading(false)}}
  return <main style={{minHeight:'100vh',display:'grid',placeItems:'center',padding:20}}><section className="panel" style={{width:'min(440px,100%)',padding:28}}><div className="brand" style={{color:'#17252c'}}><span className="brand-mark"><ShieldAlert size={16}/></span>SIF Sentinel</div><p className="subtle">Safety Intelligence</p><form onSubmit={submit}><label className="input-label" htmlFor="user-id">User ID</label><input id="user-id" className="input" style={{width:'100%',marginTop:6}} value={username} onChange={event=>setUsername(event.target.value)} autoComplete="username"/><label className="input-label" htmlFor="password" style={{display:'block',marginTop:12}}>Password</label><input id="password" className="input" style={{width:'100%',marginTop:6}} type="password" value={password} onChange={event=>setPassword(event.target.value)} autoComplete="current-password"/><button className="button" disabled={loading} style={{display:'block',width:'100%',marginTop:12}}>{loading?'Signing in…':'Sign in'}</button></form>{showDemo&&<p className="row-meta" style={{marginTop:12}}>Demo: test / test123</p>}{error&&<p className="error" role="alert">{error}</p>}</section></main>;
}
