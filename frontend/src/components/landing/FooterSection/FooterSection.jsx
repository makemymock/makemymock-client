import styles from './FooterSection.module.css';

// Anchor targets — internal hashes for the on-page sections, mailto
// for contact. Replace the `#` placeholders with real routes once the
// legal pages exist.
const navLinks = [
  { label: 'About Us',     href: '#insights' },
  { label: 'Is It Free?',  href: '#faq' },
  { label: 'Contact Us',   href: 'mailto:make.my.mock@gmail.com' },
  { label: 'FAQ',          href: '#faq' },
];

const legalLinks = [
  { label: 'Privacy Policy',   href: '#' },
  { label: 'Terms of Service', href: '#' },
  { label: 'Refund Policy',    href: '#' },
  { label: 'Cookie Policy',    href: '#' },
];

/* ---------- Social icons (inline SVG, currentColor) ---------- */

const IconLinkedIn = (p) => (
  <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" {...p}>
    <path d="M4.98 3.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zM3 9h4v12H3V9zm6 0h3.8v1.7h.05c.53-1 1.83-2.05 3.78-2.05C20.4 8.65 21 11 21 14.1V21h-4v-6.05c0-1.45-.03-3.3-2-3.3-2.02 0-2.33 1.58-2.33 3.2V21H9V9z"/>
  </svg>
);

const IconX = (p) => (
  <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" {...p}>
    <path d="M17.53 3H21l-7.39 8.45L22 21h-6.83l-5.36-7-6.13 7H.2l7.92-9.06L1.2 3H8.2l4.83 6.42L17.53 3zm-2.4 16h2.1L7.96 5H5.74l9.39 14z"/>
  </svg>
);

const IconGitHub = (p) => (
  <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" {...p}>
    <path d="M12 2a10 10 0 0 0-3.16 19.49c.5.09.68-.22.68-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.45-1.15-1.1-1.46-1.1-1.46-.9-.62.07-.6.07-.6 1 .07 1.52 1.03 1.52 1.03.89 1.52 2.34 1.08 2.91.83.09-.65.35-1.08.63-1.33-2.22-.25-4.55-1.11-4.55-4.95 0-1.1.39-1.99 1.03-2.69-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.5 9.5 0 0 1 5 0c1.91-1.29 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.69 0 3.85-2.34 4.69-4.57 4.94.36.31.68.92.68 1.85v2.74c0 .27.18.58.69.48A10 10 0 0 0 12 2z"/>
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
  { label: 'LinkedIn',  href: '#', Icon: IconLinkedIn  },
  { label: 'X',         href: '#', Icon: IconX         },
  { label: 'GitHub',    href: '#', Icon: IconGitHub    },
  { label: 'Instagram', href: '#', Icon: IconInstagram },
];

/* ---------- Right-side link card (rounded panel) ---------- */

function LinkCard({ title, items }) {
  return (
    <nav className={styles.linkCard} aria-label={title}>
      {/* Title is rendered only for SR — visually the card just shows
          the list, matching the reference layout. Drop the visually
          hidden style or unwrap if you want the heading shown. */}
      <h4 className={styles.linkCardTitleSr}>{title}</h4>
      <ul className={styles.linkList}>
        {items.map((item) => (
          <li key={item.label}>
            <a className={styles.linkItem} href={item.href}>
              {item.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function FooterSection() {
  return (
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
        <LinkCard title="Legal" items={legalLinks} />
      </div>
    </footer>
  );
}

export default FooterSection;
