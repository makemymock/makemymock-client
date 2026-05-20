import HeroSection from '../../components/landing/HeroSection/HeroSection';
import InsightSection from '../../components/landing/InsightSection/InsightSection';
import FixItSection from '../../components/landing/FixItSection/FixItSection';
import FAQSection from '../../components/landing/FAQSection/FAQSection';
import FooterSection from '../../components/landing/FooterSection/FooterSection';
import AWaves from '../../components/landing/AWaves/AWaves';
import styles from './landing.module.css';

export default function Landing() {
  return (
    <main className={styles.pageShell}>
      <div className={styles.wavesLayer}>
        <AWaves flattenTargetId="fix-it" />
      </div>
      <div className={styles.content}>
        <HeroSection />
        <div id="insight"><InsightSection /></div>
        <div id="fix-it"><FixItSection /></div>
        <div id="faq"><FAQSection /></div>
        <FooterSection />
      </div>
    </main>
  );
}
