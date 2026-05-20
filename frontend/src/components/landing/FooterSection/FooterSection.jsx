import styles from './FooterSection.module.css';

const footerNav = ['About Us', 'Is It Free', 'Contact Us'];
const footerLegal = ['Privacy Policy', 'Terms Of Service', 'Refund Policy', 'Cookie Policy'];

function FooterLinks({ title, items }) {
  return (
    <div className={styles.siteFooterColumn}>
      <h4>{title}</h4>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function FooterSection() {
  return (
    <footer className={styles.siteFooter} id="footer">
      <div className={styles.siteFooterInner}>
        <div className={styles.siteFooterBrand}>
          <h3>Make My Mock</h3>
          <p>
            A focused practice space for learners who want direction, consistency, and measurable progress.
          </p>
        </div>

        <FooterLinks title="Navigation" items={footerNav} />
        <FooterLinks title="Legal" items={footerLegal} />
      </div>

      <div className={styles.siteFooterBar}>
        <span>© 2026 Make My Mock. All rights reserved.</span>
        <a href="mailto:make.my.mock@gmail.com">make.my.mock@gmail.com</a>
      </div>
    </footer>
  );
}

export default FooterSection;
