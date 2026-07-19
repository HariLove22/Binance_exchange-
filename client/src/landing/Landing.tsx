import { Navbar } from "./components/Navbar";
import { Hero } from "./components/Hero";
import { MarketBoard } from "./components/Ticker";
import { Stats } from "./components/Stats";
import { Features, HowItWorks } from "./components/Features";
import { CTA } from "./components/CTA";
import { Footer } from "./components/Footer";
import "./landing.css";

export function Landing() {
  return (
    <div className="landing">
      <Navbar />
      <main>
        <Hero />
        <Stats />
        <MarketBoard />
        <Features />
        <HowItWorks />
        <CTA />
      </main>
      <Footer />
    </div>
  );
}
