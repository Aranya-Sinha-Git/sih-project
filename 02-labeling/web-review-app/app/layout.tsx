import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SIF Labeling Workbench",
  description: "Structured human review of credible serious injury and fatality potential.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
