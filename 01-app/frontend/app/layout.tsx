import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata={title:'SIF Sentinel | Safety Intelligence',description:'Human-reviewed SIF precursor intelligence for industrial operations.'};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>}
