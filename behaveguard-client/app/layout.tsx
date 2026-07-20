import type { Metadata } from "next";
import { Inter, Space_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { ToastProvider } from "@/lib/toast";
import Bootloader from "@/components/Bootloader";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const spaceMono = Space_Mono({ subsets: ["latin"], weight: ["400", "700"], variable: "--font-space-mono" });

export const metadata: Metadata = {
  title: "BehaveGuard — Behavioral Pattern Test",
  description:
    "A short typing and mouse-movement test used to study behavioral biometrics.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`h-full ${inter.variable} ${spaceMono.variable}`}>
      <body className="min-h-full bg-bg text-text antialiased">
        <ToastProvider>
          <Bootloader>
            <AuthProvider>{children}</AuthProvider>
          </Bootloader>
        </ToastProvider>
      </body>
    </html>
  );
}
