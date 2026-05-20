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
      'MakeMyMock is built for high-school and competitive-exam students who want personalised, adaptive practice. Whether you are preparing for board exams, JEE, or NEET, the platform adapts to your pace and your weak areas.',
  },
  {
    id: 'different-from-others',
    question: 'How is this different from other test series?',
    answer:
      'Most test series serve everyone the same paper. MakeMyMock analyses your performance after every session and serves the next question based on what you actually need to improve, not what is next in a fixed list.',
  },
  {
    id: 'personalized-practice',
    question: 'What is personalised practice?',
    answer:
      'Personalised practice means the system identifies the concepts you are getting wrong, the difficulty level you are ready for, and the topics you have not seen recently — then assembles each session around those signals instead of random questions.',
  },
  {
    id: 'suitable-for-beginners',
    question: 'Is this suitable for beginners?',
    answer:
      'Yes. The system starts with foundational concepts and increases difficulty only as your accuracy improves. Beginners get scaffolded practice; advanced learners get harder problems pulled from previous-year papers.',
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
