import { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import styles from './InsightSection.module.css';

gsap.registerPlugin(ScrollTrigger);

// Each card now shows everything on a single face — no flip. The
// `tone` class drives the colour, the index drives the slide order.
const studyCards = [
  {
    id: 'direction',
    tone: 'insightCardAmber',
    title: 'Studying a lot, but not seeing real improvement?',
    detail:
      'Most of the time, the effort is there, but the practice is not directed toward your weak areas. That makes the progress feel slow even when the study time is high.',
  },
  {
    id: 'practice',
    tone: 'insightCardPink',
    title: 'Practising randomly without knowing your weak areas.',
    detail:
      'When practice is random, it is easy to miss the chapters and concepts that actually need more attention. A focused plan makes each session count.',
  },
  {
    id: 'consistency',
    tone: 'insightCardCyan',
    title: 'Losing consistency and motivation over time.',
    detail:
      'A clear study direction makes it easier to stay consistent. Seeing progress in the right places keeps motivation alive and helps you avoid the spiral of unfocused preparation.',
  },
];

function InsightSection() {
  const sectionRef = useRef(null);
  const cardRefs = useRef([]);
  const dotRefs = useRef([]);

  useEffect(() => {
    const section = sectionRef.current;
    const cards = cardRefs.current.filter(Boolean);
    const dots = dotRefs.current.filter(Boolean);

    if (!section || cards.length === 0) return undefined;

    const ctx = gsap.context(() => {
      // Resting state for non-active cards: parked off-stage to the
      // RIGHT, fully invisible. Card 0 starts on stage. zIndex keeps
      // the active card on top of the others without flicker.
      gsap.set(cards, { xPercent: 110, scale: 0.92, opacity: 0, zIndex: 0 });
      gsap.set(cards[0], { xPercent: 0, scale: 1, opacity: 1, zIndex: 3 });
      gsap.set(dots, { opacity: 0.35 });
      if (dots[0]) gsap.set(dots[0], { opacity: 1 });

      const tl = gsap.timeline({
        scrollTrigger: {
          trigger: section,
          start: 'top top',
          end: '+=220%',
          scrub: 1,
          pin: true,
          pinSpacing: true,
        },
      });

      // Sequential hand-off — the OUTGOING card slides off + fades in
      // the first 60% of the transition; the INCOMING card waits, then
      // slides on + fades in for the last 60%. The two windows overlap
      // by only 20% so the slider never shows two half-faded cards on
      // top of each other (that was the "overlap" bug in the previous
      // cross-fade version).
      cards.forEach((card, i) => {
        if (i === 0) return;
        const t = (i - 1) * 1.0;

        // Outgoing card (i - 1) — first 0.6 of the unit
        tl.to(
          cards[i - 1],
          {
            xPercent: -110,
            scale: 0.92,
            opacity: 0,
            zIndex: 1,
            ease: 'power3.in',
            duration: 0.6,
          },
          t,
        );

        // Incoming card (i) — last 0.6 of the unit, starts at +0.4
        tl.to(
          card,
          {
            xPercent: 0,
            scale: 1,
            opacity: 1,
            zIndex: 3,
            ease: 'power3.out',
            duration: 0.6,
          },
          t + 0.4,
        );

        // Pager dot crossfade — matches the card hand-off, slightly
        // longer so the pager state is always interpretable.
        if (dots[i - 1]) {
          tl.to(
            dots[i - 1],
            { opacity: 0.35, ease: 'power1.in', duration: 0.6 },
            t,
          );
        }
        if (dots[i]) {
          tl.to(
            dots[i],
            { opacity: 1, ease: 'power1.out', duration: 0.6 },
            t + 0.4,
          );
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

      <div className={styles.cardStage}>
        <div className={styles.cardTrack}>
          {studyCards.map((card, index) => (
            <article
              key={card.id}
              ref={(element) => { cardRefs.current[index] = element; }}
              className={`${styles.insightCard} ${styles[card.tone]}`}
            >
              <span className={styles.cardIndex}>
                {String(index + 1).padStart(2, '0')}
              </span>
              <span className={styles.cardEyebrow}>The honest truth</span>
              <h3 className={styles.cardTitle}>{card.title}</h3>
              <p className={styles.cardDetail}>{card.detail}</p>
              <span className={styles.cardCorner} aria-hidden="true" />
            </article>
          ))}
        </div>

        {/* Pager — small visual cue that there are 3 cards. */}
        <div className={styles.pager} aria-hidden="true">
          {studyCards.map((card, i) => (
            <span
              key={card.id}
              ref={(element) => { dotRefs.current[i] = element; }}
              className={styles.pagerDot}
            />
          ))}
        </div>
      </div>
    </section>
  );
}

export default InsightSection;
