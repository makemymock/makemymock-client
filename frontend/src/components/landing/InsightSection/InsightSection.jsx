import { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import styles from './InsightSection.module.css';

gsap.registerPlugin(ScrollTrigger);

const studyCards = [
  {
    id: 'direction',
    toneClass: 'insightCardAmber',
    title: 'Studying a lot, but not seeing real improvement?',
    shortText: 'You keep putting in hours, but the right topics still do not get enough attention.',
    fullText:
      'Most of the time, the effort is there, but the practice is not directed toward your weak areas. That makes the progress feel slow even when the study time is high.',
  },
  {
    id: 'practice',
    toneClass: 'insightCardPink',
    title: 'Practising randomly without knowing your weak areas.',
    shortText: 'Solving questions without a map can leave the real gaps hidden.',
    fullText:
      'When practice is random, it is easy to miss the chapters and concepts that actually need more attention. A focused plan makes each session count.',
  },
  {
    id: 'consistency',
    toneClass: 'insightCardCyan',
    title: 'Losing consistency and motivation over time.',
    shortText: 'Without a steady path, it becomes harder to keep momentum.',
    fullText:
      'A clear study direction makes it easier to stay consistent. Seeing progress in the right places keeps motivation alive and helps you avoid the spiral of unfocused preparation.',
  },
];

const FLIP_TIMES = [0.75, 1.75, 2.75];

function InsightSection() {
  const sectionRef = useRef(null);
  const cardRefs = useRef([]);
  const innerRefs = useRef([]);

  useEffect(() => {
    const section = sectionRef.current;
    const cards = cardRefs.current.filter(Boolean);
    const inners = innerRefs.current.filter(Boolean);

    if (!section || cards.length === 0) return undefined;

    const ctx = gsap.context(() => {
      gsap.set(cards, { yPercent: -50, y: '100vh', opacity: 0 });
      gsap.set(inners, { rotateX: 0, scale: 1 });

      const flipState = FLIP_TIMES.map(() => false);

      const flipForward = (inner) =>
        gsap.to(inner, {
          rotateX: 180,
          scale: 1.06,
          duration: 0.9,
          ease: 'power2.inOut',
          overwrite: 'auto',
        });

      const flipReverse = (inner) =>
        gsap.to(inner, {
          rotateX: 0,
          scale: 1,
          duration: 0.9,
          ease: 'power2.inOut',
          overwrite: 'auto',
        });

      const tl = gsap.timeline({
        onUpdate: () => {
          const t = tl.time();
          FLIP_TIMES.forEach((flipT, i) => {
            const shouldFlip = t >= flipT;
            if (shouldFlip && !flipState[i]) {
              flipForward(inners[i]);
              flipState[i] = true;
            } else if (!shouldFlip && flipState[i]) {
              flipReverse(inners[i]);
              flipState[i] = false;
            }
          });
        },
        scrollTrigger: {
          trigger: section,
          start: 'top top',
          end: '+=200%',
          scrub: 1,
          pin: true,
          pinSpacing: true,
        },
      });

      cards.forEach((card, index) => {
        const enterStart = index * 1.0;
        tl.to(card, { y: 0, opacity: 1, ease: 'none', duration: 0.5 }, enterStart);

        if (index < cards.length - 1) {
          tl.to(
            card,
            { y: '-100vh', opacity: 0, ease: 'none', duration: 0.5 },
            enterStart + 1.0,
          );
        } else {
          tl.to(card, { y: 0, duration: 0.5 }, enterStart + 0.5);
        }
      });
    }, section);

    return () => ctx.revert();
  }, []);

  return (
    <section className={styles.insightSection} id="insights" ref={sectionRef}>
      <div className={styles.insightSectionSticky} aria-hidden="true">
        <div className={styles.insightSectionGrid} />
        <div className={styles.insightSectionHeadline}>
          <p>Studying hard,</p>
          <h2>But not seeing real improvement?</h2>
        </div>
        <img className={`${styles.insightSectionOrnament} ${styles.insightSectionOrnamentOne}`} src="/atom.png" alt="" />
        <img className={`${styles.insightSectionOrnament} ${styles.insightSectionOrnamentTwo}`} src="/graph.png" alt="" />
        <img className={`${styles.insightSectionOrnament} ${styles.insightSectionOrnamentThree}`} src="/organic_compound.png" alt="" />
        <img className={`${styles.insightSectionOrnament} ${styles.insightSectionOrnamentFour}`} src="/chemical_tubes.png" alt="" />
      </div>

      <div className={styles.insightSectionCards}>
        {studyCards.map((card, index) => (
          <article
            className={`${styles.insightCard} ${styles[card.toneClass]}`}
            key={card.id}
            ref={(element) => {
              cardRefs.current[index] = element;
            }}
          >
            <div
              className={styles.insightCardInner}
              ref={(element) => {
                innerRefs.current[index] = element;
              }}
            >
              <div className={`${styles.insightCardFace} ${styles.insightCardFaceFront}`}>
                <h3>{card.title}</h3>
              </div>
              <div className={`${styles.insightCardFace} ${styles.insightCardFaceBack}`}>
                <p>{card.shortText}</p>
                <p>{card.fullText}</p>
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

export default InsightSection;
