import { useState } from 'react';
import useTheme from '../../../hooks/useTheme';
import QaCard from '../QaCard/QaCard';
import styles from './FAQSection.module.css';

const derivativeQa = {
  id: 'derivative-qa',
  title: 'What is a derivative?',
  shortText: 'A derivative measures the rate of change of a function at any point.',
  fullText:
    'A derivative represents how fast a function is changing at a specific point. Geometrically, it is the slope of the tangent line to the curve. Derivatives are fundamental to calculus and are used to find rates of change, optimize functions, and analyze motion in physics.',
  pinPosition: 'center',
  placement: {
    '--card-left': '0rem',
    '--card-top': '0rem',
    '--card-rotation': '-3.2deg',
  },
};

const faqs = [
  {
    id: 'who-is-it-for',
    question: 'Who is this platform for?',
    answer:
      "It's designed for students preparing for exams like JEE, NEET, CUET, and boards — whether you're just starting out or already deep into preparation.",
  },
  {
    id: 'different-from-others',
    question: 'How is this different from other test series?',
    answer:
      'Most platforms stop at giving tests. Here, the focus is also on what happens after the test — understanding mistakes, practising weak areas, and improving step by step.',
  },
  {
    id: 'personalized-practice',
    question: 'What is personalized practice?',
    answer:
      "After you attempt tests, you'll get questions based on your weak areas and performance, so you're not just practicing randomly.",
  },
  {
    id: 'suitable-for-beginners',
    question: 'Is this suitable for beginners?',
    answer:
      'Yes. You can start at your own level and gradually improve with practice and insights.',
  },
  {
    id: 'solutions-every-question',
    question: 'Will I get solutions for every question?',
    answer:
      "Yes, you'll get clear step-by-step solutions, so you can actually understand where you went wrong.",
  },
];

function FAQSection() {
  const [expandedId, setExpandedId] = useState(null);
  const { theme } = useTheme();
  const faqIconSrc = theme === 'dark' ? '/FAQ_Dark.png' : '/FAQ_Bright.png';

  const toggleFaq = (id) => {
    setExpandedId(expandedId === id ? null : id);
  };

  return (
    <section className={styles.faqSection} id="faq">
      <div className={styles.faqSectionGrid} aria-hidden="true" />

      <div className={styles.faqSectionQaCard}>
        <QaCard
          card={derivativeQa}
          pinPosition={derivativeQa.pinPosition}
          style={derivativeQa.placement}
          variant="fill"
        />
      </div>

      <div className={styles.faqSectionHeader}>
        <h2>FAQs</h2>
        <div className={styles.faqSectionIconContainer} aria-hidden="true">
          <img className={styles.faqSectionIcon} src={faqIconSrc} alt="" />
        </div>
      </div>

      <div className={styles.faqSectionContent}>
        {faqs.map((faq) => {
          const isExpanded = expandedId === faq.id;
          return (
            <div
              key={faq.id}
              className={`${styles.faqCard} ${isExpanded ? styles.faqCardExpanded : ''}`}
            >
              <button
                className={styles.faqCardQuestion}
                id={`faq-button-${faq.id}`}
                onClick={() => toggleFaq(faq.id)}
                aria-expanded={isExpanded}
                aria-controls={`faq-answer-${faq.id}`}
              >
                <span>{faq.question}</span>
                <span className={styles.faqCardChevron} aria-hidden="true">▼</span>
              </button>
              <div
                id={`faq-answer-${faq.id}`}
                className={styles.faqCardAnswer}
                role="region"
                aria-labelledby={`faq-button-${faq.id}`}
              >
                <p>{faq.answer}</p>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default FAQSection;
