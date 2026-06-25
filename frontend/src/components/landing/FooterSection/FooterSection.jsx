import { useState } from 'react';
import PolicyModal from '../PolicyModal/PolicyModal';
import { SOCIAL_LINKS, CONTACT_EMAIL } from '../../../constants/links';
import privacyPolicy from '../../../content/legal/privacy-policy.md?raw';
import termsOfService from '../../../content/legal/terms-of-service.md?raw';
import refundPolicy from '../../../content/legal/refund-policy.md?raw';
import cookiePolicy from '../../../content/legal/cookie-policy.md?raw';
import styles from './FooterSection.module.css';

// Anchor targets — internal hashes for the on-page sections, mailto for
// contact (address lives in src/constants/links.js).
const navLinks = [
  { label: 'About Us',     href: '#insights' },
  { label: 'Is It Free?',  href: '#faq' },
  { label: 'Contact Us',   href: `mailto:${CONTACT_EMAIL}` },
  { label: 'FAQ',          href: '#faq' },
];

// Legal pages don't have standalone routes — each opens in a popup
// (PolicyModal) that renders its markdown source from src/content/legal/.
const legalLinks = [
  { label: 'Privacy Policy',   body: privacyPolicy },
  { label: 'Terms of Service', body: termsOfService },
  { label: 'Refund Policy',    body: refundPolicy },
  { label: 'Cookie Policy',    body: cookiePolicy },
];

/* ---------- Social icons (inline SVG, currentColor) ---------- */

const IconLinkedIn = (p) => (
  <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" {...p}>
    <path d="M4.98 3.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zM3 9h4v12H3V9zm6 0h3.8v1.7h.05c.53-1 1.83-2.05 3.78-2.05C20.4 8.65 21 11 21 14.1V21h-4v-6.05c0-1.45-.03-3.3-2-3.3-2.02 0-2.33 1.58-2.33 3.2V21H9V9z"/>
  </svg>
);

const IconFacebook = (p) => (
  <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" {...p}>
    <path d="M22 12a10 10 0 1 0-11.56 9.88v-6.99H7.9V12h2.54V9.8c0-2.51 1.49-3.89 3.78-3.89 1.09 0 2.24.19 2.24.19v2.47h-1.26c-1.24 0-1.63.77-1.63 1.56V12h2.78l-.44 2.89h-2.34v6.99A10 10 0 0 0 22 12z"/>
  </svg>
);

const IconInstagram = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...p}>
    <rect x="3" y="3" width="18" height="18" rx="5" />
    <circle cx="12" cy="12" r="4" />
    <circle cx="17.5" cy="6.5" r="1" fill="currentColor" />
  </svg>
);

const socials = [
  { label: 'Instagram', href: SOCIAL_LINKS.instagram, Icon: IconInstagram },
  { label: 'Facebook',  href: SOCIAL_LINKS.facebook,  Icon: IconFacebook  },
  { label: 'LinkedIn',  href: SOCIAL_LINKS.linkedin,  Icon: IconLinkedIn  },
];

/* ---------- Right-side link card (rounded panel) ---------- */
// When `onItemClick` is supplied the items render as buttons (legal popups);
// otherwise they're plain anchors (navigation).

function LinkCard({ title, items, onItemClick }) {
  return (
    <nav className={styles.linkCard} aria-label={title}>
      {/* Title is rendered only for SR — visually the card just shows
          the list, matching the reference layout. */}
      <h4 className={styles.linkCardTitleSr}>{title}</h4>
      <ul className={styles.linkList}>
        {items.map((item) => (
          <li key={item.label}>
            {onItemClick ? (
              <button
                type="button"
                className={styles.linkItem}
                onClick={() => onItemClick(item)}
              >
                {item.label}
              </button>
            ) : (
              <a className={styles.linkItem} href={item.href}>
                {item.label}
              </a>
            )}
          </li>
        ))}
      </ul>
    </nav>
  );
}

function FooterSection() {
  const [activePolicy, setActivePolicy] = useState(null);

  return (
    <>
      <footer className={styles.siteFooter} id="footer">
        {/* Subtle radial glow behind the content — gives the dark slab
            some depth without a hard gradient line. */}
        <div className={styles.glow} aria-hidden="true" />

        <div className={styles.inner}>
          {/* ---- Brand column ---- */}
          <div className={styles.brand}>
            <h3 className={styles.brandTitle}>Make My Mock</h3>
            <p className={styles.brandTagline}>
              Made with{' '}
              <span className={styles.heart} aria-hidden="true">❤</span>{' '}
              in India
            </p>

            <ul className={styles.socialList}>
              {socials.map(({ label, href, Icon }) => (
                <li key={label}>
                  <a
                    className={styles.socialLink}
                    href={href}
                    aria-label={label}
                    title={label}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <Icon width={18} height={18} />
                  </a>
                </li>
              ))}
            </ul>

            <p className={styles.copyright}>
              © 2026 Make My Mock. All Rights Reserved.
            </p>
          </div>

          {/* ---- Two link cards on the right ---- */}
          <LinkCard title="Navigation" items={navLinks} />
          <LinkCard title="Legal" items={legalLinks} onItemClick={setActivePolicy} />
        </div>
      </footer>

      {activePolicy ? (
        <PolicyModal
          title={activePolicy.label}
          body={activePolicy.body}
          onClose={() => setActivePolicy(null)}
        />
      ) : null}
    </>
  );
}

export default FooterSection;
