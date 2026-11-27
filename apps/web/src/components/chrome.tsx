"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ArrowUpRight, X, ArrowRight, Info } from "lucide-react";
import { ThemeControl } from "./theme-control";
import { Button } from "./ui/button";
import { jurisdiction, presentation } from "@/lib/jurisdiction";

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
      {!isChat && <div className="government-banner"><Link href="/about">{presentation.banner} <span className="banner-pilot">Pilot</span><Info size={13} aria-hidden="true" /></Link></div>}
      <header className={`site-header${isChat ? " chat-header" : ""}`}>
        <div className="header-inner">
          <div className="header-brand">
            <Link className="identity" href="/" aria-label={presentation.homeLabel}>
              <img className="identity-logo" src={jurisdiction.brand.logo} width={jurisdiction.brand.logoWidth} height={jurisdiction.brand.logoHeight} alt={jurisdiction.name} />
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
      <div className="footer-intro"><p>{jurisdiction.id === "sk" ? <>Saskatchewan services.<br />A place to start.</> : <>Less searching.<br />More living.</>}</p><Link href={jurisdiction.features.guidedJourneys ? "/#journeys" : "/services"} className="pill-link">{jurisdiction.id === "sk" ? "Browse official services" : "Find your next step"} <ArrowRight size={19} aria-hidden="true" /></Link></div>
      <div className="footer-signature" aria-hidden="true">{jurisdiction.shortName}</div>
      <div className="footer-lower">
        {jurisdiction.id === "sk"
          ? <p>Independent pilot.<br /><span>AI answers may be incomplete or wrong. Check information at saskatchewan.ca.</span></p>
          : <p>A service assistant pilot.<br /><span>Official services take it from here.</span></p>}
        <nav aria-label="Footer navigation"><Link href="/how-it-works">How it works</Link><Link href="/about#privacy">Privacy</Link><Link href="/about#accessibility">Accessibility</Link><Link href="/sources">Our sources</Link><Link href="/credits">{presentation.creditsTitle}</Link></nav>
        <a href={jurisdiction.helpChannel.url} className="footer-help">{presentation.helpLabel} <ArrowUpRight size={16} aria-hidden="true" /></a>
      </div>
      <FooterCredit />
    </footer>
  );
}

export function FooterCredit() {
  return <p className="footer-credit">{presentation.credit} <a href="https://github.com/VeVarunSharma" target="_blank" rel="noopener noreferrer">@VeVarunSharma</a></p>;
}
