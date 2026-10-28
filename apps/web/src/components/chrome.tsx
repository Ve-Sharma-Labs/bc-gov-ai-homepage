"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ArrowUpRight, X, ArrowRight, Info } from "lucide-react";
import { ThemeControl } from "./theme-control";
import { Button } from "./ui/button";

const navigation = [
  { href: "/", label: "Home" },
  { href: "/chat", label: "Chat" },
  { href: "/how-it-works", label: "How it works" },
  { href: "/services", label: "Browse services" },
  { href: "/sources", label: "Our sources" },
  { href: "/about", label: "About this pilot" },
];

export function Header() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const isChat = pathname === "/chat";
  const reduced = useReducedMotion();
  useEffect(() => { setOpen(false); }, [pathname]);
  return (
    <>
      {!isChat && <div className="government-banner"><Link href="/about">A service assistant for British Columbia <span className="banner-pilot">Pilot</span><Info size={13} aria-hidden="true" /></Link></div>}
      <header className={`site-header${isChat ? " chat-header" : ""}`}>
        <div className="header-inner">
          <div className="header-brand">
            <Link className="identity" href="/" aria-label="British Columbia service assistant home">
              <img className="identity-logo" src="/brand/bc-logo-horizontal-transparent.png" width={361} height={120} alt="Government of British Columbia" />
            </Link>
            {isChat && <Link className="chat-pilot-label" href="/about">Pilot</Link>}
          </div>
          <DialogPrimitive.Root open={open} onOpenChange={setOpen}>
            <DialogPrimitive.Trigger render={<Button className="menu-trigger" />} aria-label="Menu">Menu</DialogPrimitive.Trigger>
            <AnimatePresence>
              {open && <DialogPrimitive.Portal keepMounted>
                <DialogPrimitive.Backdrop className="menu-scrim" render={<motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reduced ? 0 : 0.2 }} />} />
                <DialogPrimitive.Popup
                  className="menu-panel"
                  render={<motion.div initial={reduced ? false : { opacity: 0, scale: 0.88, borderRadius: 50 }} animate={{ opacity: 1, scale: 1, borderRadius: 32 }} exit={{ opacity: 0, scale: reduced ? 1 : 0.94 }} transition={{ duration: reduced ? 0 : 0.4, ease: [0.22, 1, 0.36, 1] }} />}
                >
                  <div className="menu-top"><DialogPrimitive.Title className="sr-only">Explore the pilot</DialogPrimitive.Title><span>Find your next step.</span><DialogPrimitive.Close render={<Button variant="ghost" size="icon" className="menu-close" />} aria-label="Close menu"><X size={20} /></DialogPrimitive.Close></div>
                  <DialogPrimitive.Description className="sr-only">Navigate the site and choose your appearance.</DialogPrimitive.Description>
                  <nav aria-label="Main navigation">
                    {navigation.map((item, index) => <motion.div key={item.href} initial={reduced ? false : { opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: reduced ? 0 : index * 0.035 }}>
                      <Link href={item.href} onClick={() => setOpen(false)} className="menu-link" aria-current={pathname === item.href ? "page" : undefined}>{item.label}<ArrowUpRight size={22} aria-hidden="true" /></Link>
                    </motion.div>)}
                  </nav>
                  <div className="menu-appearance"><span>Make yourself comfortable</span><ThemeControl /></div>
                  <Link className="menu-privacy" href="/about#privacy" onClick={() => setOpen(false)}>Privacy and accessibility <ArrowRight size={16} aria-hidden="true" /></Link>
                </DialogPrimitive.Popup>
              </DialogPrimitive.Portal>}
            </AnimatePresence>
          </DialogPrimitive.Root>
        </div>
      </header>
    </>
  );
}

export function Footer() {
  const pathname = usePathname();
  if (pathname === "/chat") return null;
  return (
    <footer className="site-footer">
      <div className="footer-intro"><p>Less searching.<br />More living.</p><Link href="/#journeys" className="pill-link">Find your next step <ArrowRight size={19} aria-hidden="true" /></Link></div>
      <div className="footer-signature" aria-hidden="true">British Columbia</div>
      <div className="footer-lower">
        <p>A service assistant pilot.<br /><span>Official services take it from here.</span></p>
        <nav aria-label="Footer navigation"><Link href="/how-it-works">How it works</Link><Link href="/about#privacy">Privacy</Link><Link href="/about#accessibility">Accessibility</Link><Link href="/sources">Our sources</Link><Link href="/credits">Photo credits</Link></nav>
        <a href="https://www2.gov.bc.ca/gov/content/governments/organizational-structure/ministries-organizations/ministries/citizens-services/servicebc" className="footer-help">Talk to Service BC <ArrowUpRight size={16} aria-hidden="true" /></a>
      </div>
      <FooterCredit />
    </footer>
  );
}

export function FooterCredit() {
  return <p className="footer-credit">Built with love in BC by <a href="https://github.com/VeVarunSharma" target="_blank" rel="noopener noreferrer">@VeVarunSharma</a></p>;
}
