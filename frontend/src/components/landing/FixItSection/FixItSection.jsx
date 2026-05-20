import { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import QaCard from '../QaCard/QaCard';
import styles from './FixItSection.module.css';

gsap.registerPlugin(ScrollTrigger);

const fixSteps = [
  {
    id: 'personalized',
    number: '01',
    icon: '/brain.png',
    title: 'Personalized practice that adapts to you',
    text: 'Practice questions tailored to your level and weak areas, so every question you solve actually helps you improve.',
    direction: 'left',
  },
  {
    id: 'analysis',
    number: '02',
    icon: '/graph.png',
    title: 'Clear insights that show your real progress',
    text: 'Get detailed performance analysis after every test so you know what is improving, what is not, and where to focus next.',
    direction: 'up',
  },
  {
    id: 'consistency',
    number: '03',
    icon: '/atom.png',
    title: 'A system that keeps you consistent and engaged',
    text: 'With structured tests, progress tracking, and a bit of competition, you stay motivated and keep moving forward.',
    direction: 'right',
  },
];

const matrixQa = {
  id: 'matrix-qa',
  title: 'What is a matrix?',
  shortText:
    'A matrix is a rectangular arrangement of numbers (or elements) arranged in rows and columns.',
  fullText:
    'A matrix is a rectangular arrangement of numbers (or elements) arranged in rows and columns, used to represent and solve systems of equations and transformations.',
  pinPosition: 'left',
  placement: {
    '--card-right': '0rem',
    '--card-top': '-10rem',
    '--card-rotation': '4deg',
  },
};

function FixItSection() {
  const sectionRef = useRef(null);
  const motionRefs = useRef([]);
  const timelineRef = useRef(null);

  useEffect(() => {
    const section = sectionRef.current;
    const items = motionRefs.current.filter(Boolean);

    if (!section || items.length === 0) return undefined;

    const ctx = gsap.context(() => {
      gsap.set(items, { opacity: 0 });

      const tl = gsap.timeline({ paused: true });

      items.forEach((item, index) => {
        const direction = item.dataset.direction;
        const fromVars =
          direction === 'left'
            ? { x: -160, y: 25 }
            : direction === 'right'
              ? { x: 160, y: 25 }
              : { x: 0, y: 140 };

        tl.fromTo(
          item,
          { ...fromVars, opacity: 0, rotate: direction === 'left' ? -8 : direction === 'right' ? 8 : 0 },
          {
            x: 0,
            y: 0,
            rotate: 0,
            opacity: 1,
            duration: 0.9,
            ease: 'power3.out',
          },
          index * 0.12,
        );
      });

      timelineRef.current = tl;

      const trigger = ScrollTrigger.create({
        trigger: section,
        start: 'top 70%',
        end: 'bottom 30%',
        onEnter: () => {
          tl.play();
        },
        onEnterBack: () => {
          tl.play();
        },
        onLeaveBack: () => {
          tl.reverse();
        },
      });

      return () => trigger.kill();
    }, section);

    return () => ctx.revert();
  }, []);

  return (
    <section className={styles.fixItSection} id="fix-it" ref={sectionRef}>
      <div className={styles.fixItSectionGrid} aria-hidden="true" />

      <div className={styles.fixItSectionHeader} ref={(el) => (motionRefs.current[0] = el)} data-direction="left">
        <p className={styles.fixItSectionEyebrow}>How We Fix It</p>
        <h2>A smarter way to prepare for exams</h2>
      </div>

      <div
        className={`${styles.fixItSectionQaCard} ${styles.fixItSectionQaCardNote}`}
        ref={(el) => (motionRefs.current[1] = el)}
        data-direction="up"
      >
        <QaCard
          card={matrixQa}
          pinPosition={matrixQa.pinPosition}
          style={matrixQa.placement}
        />
      </div>

      <div className={styles.fixItSectionCards}>
        {fixSteps.map((step, index) => (
          <article
            key={step.id}
            className={styles.fixItCard}
            data-tone={step.id}
            data-direction={step.direction}
            ref={(el) => {
              motionRefs.current[index + 2] = el;
            }}
          >
            <img className={styles.fixItCardIcon} src={step.icon} alt="" aria-hidden="true" />
            <span className={styles.fixItCardNumber}>{step.number}</span>
            <h3>{step.title}</h3>
            <p>{step.text}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

export default FixItSection;
